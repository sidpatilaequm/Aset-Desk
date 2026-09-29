"""Asset register: create, edit, import from invoice, allocate, take back, sign for."""
from datetime import date
from fastapi import APIRouter, Depends, File as UploadField, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .. import ai
from ..db import get_db, next_id, parse_dt, utcnow
from ..models import Asset
from ..security import CurrentUser, current_user
from ..serialize import asset_json
from ..services import ASSET_STATUS, allocate, get_asset, get_user, log_asset, take_back
from .admin import save_upload

router = APIRouter(prefix="/api")

CATEGORIES = set(ai.CATEGORIES)
METHODS = {"SL", "WDV", "DDB", "SYD"}
DEPR_FIELDS = {"inServiceDate", "salvage", "life", "method", "rate"}
COLUMN = {"name": "name", "category": "category", "status": "status", "serial": "serial", "model": "model", "vendor": "vendor",
          "location": "location", "department": "department", "notes": "notes", "invoiceNumber": "invoice_number",
          "purchaseDate": "purchase_date", "inServiceDate": "in_service_date", "cost": "cost", "salvage": "salvage",
          "life": "life_years", "method": "method", "rate": "wdv_rate"}


def _date(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, f"Invalid date: {v}")


def _clean(field: str, v):
    if field in ("purchaseDate", "inServiceDate"):
        return _date(v)
    if field in ("cost", "salvage"):
        n = float(v or 0)
        if n < 0:
            raise HTTPException(400, f"{field} can't be negative.")
        return round(n, 2)
    if field == "life":
        n = int(float(v or 1))
        if not 1 <= n <= 50:
            raise HTTPException(400, "Useful life must be 1–50 years.")
        return n
    if field == "rate":
        return None if v in (None, "") else min(100.0, max(0.0, float(v)))
    if field == "method":
        if v not in METHODS:
            raise HTTPException(400, "Unknown depreciation method.")
        return v
    if field == "category":
        return v if v in CATEGORIES else "Other"
    if field == "status":
        if v not in ASSET_STATUS or v == "Sold":
            raise HTTPException(400, "Use the sale workflow to mark an asset as sold.")
        return v
    s = (str(v) if v is not None else "").strip()
    return s or None


def _apply(a: Asset, data: dict) -> list[str]:
    changed = []
    for k, v in data.items():
        if k not in COLUMN:
            continue
        val = _clean(k, v)
        col = COLUMN[k]
        if str(getattr(a, col) if getattr(a, col) is not None else "") != str(val if val is not None else ""):
            setattr(a, col, val); changed.append(k)
    return changed


@router.post("/assets")
def create_asset(body: dict, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.create")
    if not str(body.get("name", "")).strip():
        raise HTTPException(400, "Give the asset a name.")
    if float(body.get("cost") or 0) <= 0:
        raise HTTPException(400, "Enter a cost above zero.")
    if float(body.get("salvage") or 0) > float(body.get("cost") or 0):
        raise HTTPException(400, "Salvage value can't exceed cost.")
    now = utcnow()
    a = Asset(id=next_id(db, "AST"), name="", created_at=now, updated_at=now, created_by=cu.id, source="manual", status="In stock")
    _apply(a, {**body, "status": body.get("status") if body.get("status") in ("In stock", "Under repair", "Retired", "Disposed") else "In stock"})
    db.add(a); db.flush()
    log_asset(db, a, cu.id, "Created manually")
    db.commit()
    return asset_json(get_asset(db, a.id))


@router.patch("/assets/{asset_id}")
def edit_asset(asset_id: str, body: dict, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.edit", "depr.edit")
    a = get_asset(db, asset_id, lock=True)
    if not cu.can("assets.edit"):
        body = {k: v for k, v in body.items() if k in DEPR_FIELDS}  # Finance: depreciation settings only
    if "status" in body and body["status"] in ("In use",) and not a.assigned_to:
        raise HTTPException(400, "Allocate the asset to set it In use.")
    if "status" in body and a.assigned_to and body["status"] not in ("In use", "Under repair"):
        raise HTTPException(400, "Take the asset back from the employee first.")
    old_status = a.status
    changed = _apply(a, body)
    if float(a.salvage or 0) > float(a.cost or 0):
        raise HTTPException(400, "Salvage value can't exceed cost.")
    if a.status in ("Disposed", "Retired") and old_status != a.status:
        a.disposed_at = utcnow()
    if changed:
        log_asset(db, a, cu.id, "Edited: " + ", ".join(changed))
    db.commit()
    return asset_json(get_asset(db, a.id))


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.delete")
    a = get_asset(db, asset_id)
    if a.assigned_to:
        raise HTTPException(409, "Take the asset back before deleting it.")
    db.delete(a); db.commit()
    return {"ok": True}


class AllocateIn(BaseModel):
    to: str
    when: str | None = None
    note: str = ""


@router.post("/assets/{asset_id}/allocate")
def allocate_asset(asset_id: str, body: AllocateIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.assign")
    a = get_asset(db, asset_id, lock=True)
    to = get_user(db, body.to)
    when = parse_dt(body.when) or utcnow()
    allocate(db, a, to, when, body.note.strip(), cu.id)
    db.commit()
    return asset_json(get_asset(db, a.id))


class TakeBackIn(BaseModel):
    condition: str = Field(pattern="^(Good|Damaged|Lost)$")
    note: str = ""
    when: str | None = None


@router.post("/assets/{asset_id}/return")
def return_asset(asset_id: str, body: TakeBackIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.assign")
    a = get_asset(db, asset_id, lock=True)
    take_back(db, a, body.condition, body.note.strip(), parse_dt(body.when) or utcnow(), cu.id)
    db.commit()
    return asset_json(get_asset(db, a.id))


class AckIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)


@router.post("/assets/{asset_id}/acknowledge")
def acknowledge(asset_id: str, body: AckIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    a = get_asset(db, asset_id, lock=True)
    if a.assigned_to != cu.id:
        raise HTTPException(403, "Only the person the asset is allocated to can sign for it.")
    a.acknowledged_at = utcnow(); a.acknowledged_by = cu.id; a.acknowledged_name = body.name.strip()
    log_asset(db, a, cu.id, f"Signed for by {body.name.strip()}")
    db.commit()
    return asset_json(get_asset(db, a.id))


@router.post("/ocr")
async def read_invoice(file: UploadFile = UploadField(...), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.import")
    data = await file.read()
    stored = save_upload(db, cu, file.filename or "invoice", file.content_type or "", data)
    result = ai.read_invoice(data, file.content_type or "")
    return {"result": result, "fileId": stored["id"]}


class ImportLine(BaseModel):
    name: str
    category: str = "Other"
    qty: int = Field(ge=1, le=500)
    unitCost: float = Field(ge=0)
    life: int = Field(ge=1, le=50)
    serials: list[str] = []


class ImportIn(BaseModel):
    vendor: str = ""
    vendorTaxId: str = ""
    invoiceNumber: str = ""
    date: str | None = None
    fileId: str | None = None
    taxRatio: float = 0
    lines: list[ImportLine]


@router.post("/assets/import")
def import_assets(body: ImportIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("assets.import")
    if not body.lines:
        raise HTTPException(400, "Select at least one line.")
    from ..security import get_config
    method = get_config(db).get("defaultMethod", "SL")
    d = _date(body.date) or date.today(); now = utcnow(); created = []
    for ln in body.lines:
        for k in range(ln.qty):
            a = Asset(id=next_id(db, "AST"), name=ln.name.strip() or "Untitled asset", category=ln.category if ln.category in CATEGORIES else "Other",
                      status="In stock", serial=(ln.serials[k].strip() if k < len(ln.serials) else "") or None,
                      vendor=body.vendor or None, vendor_tax_id=body.vendorTaxId or None, invoice_number=body.invoiceNumber or None,
                      invoice_file_id=body.fileId, purchase_date=d, in_service_date=d,
                      cost=round(ln.unitCost * (1 + max(0.0, body.taxRatio)), 2), salvage=0, life_years=ln.life, method=method,
                      source="invoice-ocr", created_at=now, updated_at=now, created_by=cu.id)
            db.add(a); db.flush()
            log_asset(db, a, cu.id, f"Created from invoice {body.invoiceNumber}".strip())
            created.append(a.id)
    db.commit()
    return {"created": created}
