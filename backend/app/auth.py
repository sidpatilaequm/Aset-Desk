"""Sign-in with Microsoft Entra ID (Azure AD) or Google Workspace via OpenID Connect."""
import uuid
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db, utcnow
from .models import User
from .perms import ROLES, norm_role
from .security import get_config

router = APIRouter()
oauth = OAuth()
if settings.microsoft_configured:
    oauth.register("microsoft", client_id=settings.ms_client_id, client_secret=settings.ms_client_secret,
                   server_metadata_url=f"https://login.microsoftonline.com/{settings.ms_tenant_id}/v2.0/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid email profile"})
if settings.google_configured:
    oauth.register("google", client_id=settings.google_client_id, client_secret=settings.google_client_secret,
                   server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid email profile"})


def providers_available(db: Session) -> list[str]:
    cfg = get_config(db); out = []
    if settings.microsoft_configured and cfg["microsoft"].get("enabled", True): out.append("microsoft")
    if settings.google_configured and cfg["google"].get("enabled", True): out.append("google")
    return out


def _group_role(cfg: dict, groups: list[str]) -> str | None:
    """microsoft.groupRoles: one mapping per line, 'group-object-id = Role'."""
    for line in str(cfg["microsoft"].get("groupRoles") or "").splitlines():
        if "=" in line:
            gid, role = [x.strip() for x in line.split("=", 1)]
            role = norm_role(role)
            if gid in groups and role in ROLES:
                return role
    return None


def sign_in(db: Session, request: Request, provider: str, email: str, name: str, subject: str | None, groups: list[str] | None = None):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Your account didn't share an email address.")
    cfg = get_config(db)
    domain = (cfg.get(provider, {}) or {}).get("domain", "").strip().lower().lstrip("@") if provider in ("microsoft", "google") else ""
    if domain and not email.endswith("@" + domain):
        raise HTTPException(403, f"{email} isn't in the {domain} directory.")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = utcnow()
    if not user:
        user = User(id=str(uuid.uuid4()), email=email, name=name or email.split("@")[0], created_at=now)
        db.add(user)
    user.name = name or user.name
    user.provider = provider
    user.provider_subject = subject
    user.first_seen_at = user.first_seen_at or now
    user.last_sign_in_at = now
    if provider == "microsoft" and groups and not user.role:
        mapped = _group_role(cfg, groups)
        if mapped:
            user.role = mapped
    db.commit()
    request.session.clear()
    request.session["uid"] = user.id
    return user


@router.get("/auth/login/{provider}")
async def login(provider: str, request: Request, db: Session = Depends(get_db)):
    if provider not in providers_available(db):
        raise HTTPException(404, "That sign-in option isn't enabled.")
    client = oauth.create_client(provider)
    return await client.authorize_redirect(request, f"{settings.base_url}/auth/callback/{provider}")


@router.get("/auth/callback/{provider}")
async def callback(provider: str, request: Request, db: Session = Depends(get_db)):
    if provider not in providers_available(db):
        raise HTTPException(404, "That sign-in option isn't enabled.")
    client = oauth.create_client(provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as e:
        return RedirectResponse(f"/?signin_error={e.error}", status_code=302)
    info = token.get("userinfo") or {}
    email = info.get("email") or info.get("preferred_username") or info.get("upn")
    if provider == "google":
        cfg_domain = get_config(db)["google"].get("domain", "").strip().lower()
        if cfg_domain and info.get("hd", "").lower() != cfg_domain:
            return RedirectResponse("/?signin_error=wrong_domain", status_code=302)
        if not info.get("email_verified", False):
            return RedirectResponse("/?signin_error=unverified_email", status_code=302)
    try:
        sign_in(db, request, provider, email, info.get("name", ""), info.get("sub"), info.get("groups") or [])
    except HTTPException as e:
        return RedirectResponse(f"/?signin_error={'wrong_domain' if e.status_code == 403 else 'no_email'}", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.post("/auth/dev")
async def dev_login(request: Request, email: str = Form(...), name: str = Form(""), db: Session = Depends(get_db)):
    if not settings.dev_login:
        raise HTTPException(404)
    sign_in(db, request, "dev", email, name, None)
    return RedirectResponse("/", status_code=303)


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
