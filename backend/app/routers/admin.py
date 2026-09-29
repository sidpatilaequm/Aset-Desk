"""Session info, the combined state feed, people & roles, settings and file storage."""
import uuid
from fastapi import APIRouter, Depends, File as UploadField, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import Session, selectinload
from ..auth import providers_available
from ..config import settings
from ..db import get_db, utcnow
from ..models import Asset, AssetReturn, File, Sale, Setting, Ticket, User
from ..perms import ROLES
from ..security import CurrentUser, current_user, get_config, role_of, is_bootstrap_admin
from ..serialize import asset_json, iso, return_json, sale_json, ticket_json

router = APIRouter()
ALLOWED_UPLOADS = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}


def person_json(u: User, cfg: dict) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "provider": u.provider, "signedInAt": iso(u.last_sign_in_at),
            "firstSeenAt": iso(u.first_seen_at), "role": role_of(u, cfg), "explicitRole": bool(u.role),
            "isOwner": is_bootstrap_admin(u), "signedIn": bool(u.provider)}


@router.get("/api/public-config")
def public_config(db: Session = Depends(get_db)):
    cfg = get_config(db)
    return {"providers": providers_available(db), "devLogin": settings.dev_login,
            "domains": {"microsoft": cfg["microsoft"].get("domain", ""), "google": cfg["google"].get("domain", "")}}


@router.get("/api/state")
def state(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Everything the signed-in person is allowed to see, in one response. The browser polls this."""
    cfg = get_config(db)
    me = cu.id
    aq = select(Asset).options(selectinload(Asset.allocations), selectinload(Asset.log))
    if not cu.can("assets.viewAll"):
        aq = aq.where(Asset.assigned_to == me)
    tq = select(Ticket)
    if not cu.can("tickets.viewAll"):
        tq = tq.where(or_(Ticket.requester_id == me, Ticket.assignee_id == me))
    rq = select(AssetReturn).options(selectinload(AssetReturn.items), selectinload(AssetReturn.history))
    if not cu.can("exits.viewAll"):
        rq = rq.where(AssetReturn.employee_id == me)
    sq = select(Sale).options(selectinload(Sale.schedule), selectinload(Sale.history))
    if not (cu.can("sales.create") or cu.can("sales.approve") or cu.can("sales.view")):
        sq = sq.where(Sale.employee_id == me)
    people = db.execute(select(User).order_by(User.name)).scalars().all()
    return {
        "me": {"id": me, "name": cu.user.name, "email": cu.user.email, "provider": cu.user.provider, "role": cu.role,
               "perms": sorted(cu.perms), "isOwner": cu.is_owner},
        "features": {"ai": settings.ai_enabled},
        "config": cfg,
        "people": [person_json(u, cfg) for u in people],
        "assets": [asset_json(a) for a in db.execute(aq).scalars().all()],
        "tickets": [ticket_json(t) for t in db.execute(tq).scalars().all()],
        "returns": [return_json(r) for r in db.execute(rq).scalars().all()],
        "sales": [sale_json(s) for s in db.execute(sq).scalars().all()],
    }


class ConfigIn(BaseModel):
    microsoft: dict
    google: dict
    currency: str = "INR"
    fyStartMonth: int = 4
    defaultMethod: str = "SL"


@router.put("/api/config")
def save_config(body: ConfigIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("settings.manage")
    if not (body.microsoft.get("enabled") or body.google.get("enabled")):
        raise HTTPException(400, "Keep at least one sign-in provider enabled.")
    for p in (body.microsoft, body.google):
        if p.get("defaultRole") not in ROLES:
            p["defaultRole"] = "Employee"
    value = {"microsoft": {k: body.microsoft.get(k, "") for k in ("enabled", "domain", "tenantId", "defaultRole", "groupRoles")},
             "google": {k: body.google.get(k, "") for k in ("enabled", "domain", "defaultRole")},
             "currency": body.currency[:3].upper(), "fyStartMonth": min(12, max(1, body.fyStartMonth)),
             "defaultMethod": body.defaultMethod if body.defaultMethod in ("SL", "WDV", "DDB", "SYD") else "SL"}
    row = db.get(Setting, "directory")
    if row:
        row.value = value; row.updated_by = cu.id
    else:
        db.add(Setting(key="directory", value=value, updated_by=cu.id))
    db.commit()
    return get_config(db)


class RoleIn(BaseModel):
    role: str


@router.put("/api/people/{uid}/role")
def set_role(uid: str, body: RoleIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("people.manage")
    if body.role not in ROLES:
        raise HTTPException(400, "Unknown role.")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "That person wasn't found.")
    u.role = body.role
    db.commit()
    return person_json(u, get_config(db))


class PersonIn(BaseModel):
    email: str
    name: str = ""


@router.post("/api/people")
def add_person(body: PersonIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Lets IT allocate to someone who hasn't signed in yet. They're matched by email when they do."""
    cu.require("people.add", "people.manage")
    email = body.email.strip().lower()
    if "@" not in email or len(email) > 255:
        raise HTTPException(400, "Enter a valid work email.")
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u:
        u = User(id=str(uuid.uuid4()), email=email, name=body.name.strip() or email.split("@")[0], created_at=utcnow())
        db.add(u); db.commit()
    return person_json(u, get_config(db))


@router.post("/api/files")
async def upload(file: UploadFile = UploadField(...), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return save_upload(db, cu, file.filename or "file", file.content_type or "", await file.read())


def save_upload(db: Session, cu: CurrentUser, filename: str, content_type: str, data: bytes) -> dict:
    if content_type not in ALLOWED_UPLOADS:
        raise HTTPException(400, "Upload a JPG, PNG, WebP, GIF or PDF file.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, f"Files must be under {settings.max_upload_mb} MB.")
    fid = uuid.uuid4().hex
    path = settings.upload_dir / fid
    path.write_bytes(data)
    db.add(File(id=fid, filename=filename[:255], content_type=content_type, size_bytes=len(data), storage_path=str(path), uploaded_by=cu.id, created_at=utcnow()))
    db.commit()
    return {"id": fid, "url": f"/files/{fid}", "contentType": content_type, "name": filename}


@router.get("/files/{fid}")
def get_file(fid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    f = db.get(File, fid)
    if not f:
        raise HTTPException(404, "File not found.")
    return FileResponse(f.storage_path, media_type=f.content_type, filename=f.filename, content_disposition_type="inline")
