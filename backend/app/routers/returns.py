"""Routine returns and exit clearance (handover → IT manager → Finance → cleared for F&F)."""
from datetime import date
from html import escape
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..db import get_db, next_id, parse_dt, utcnow
from ..depreciation import book_value
from ..models import Asset, AssetReturn, ReturnItem, Sale
from ..security import CurrentUser, current_user, get_config
from ..serialize import return_json
from ..services import OPEN_RETURN_STAGES, get_asset, hist_return, hist_sale, money, outstanding_for, take_back, user_name

router = APIRouter(prefix="/api")
RETURN_REASONS = ["Routine return", "No longer needed", "Getting a replacement", "Faulty or damaged", "Moving role or team", "Other"]
EXIT_REASONS = ["Resignation", "Retirement", "End of contract", "Termination", "Other"]


def _load(db: Session, rid: str, lock=False) -> AssetReturn:
    q = select(AssetReturn).where(AssetReturn.id == rid).options(selectinload(AssetReturn.items), selectinload(AssetReturn.history))
    if lock:
        q = q.with_for_update()
    r = db.execute(q).scalar_one_or_none()
    if not r:
        raise HTTPException(404, f"{rid} wasn't found.")
    return r


def _visible(r: AssetReturn, cu: CurrentUser):
    if not (cu.can("exits.viewAll") or r.employee_id == cu.id):
        raise HTTPException(403, "You don't have access to this.")


def _not_self(r: AssetReturn, cu: CurrentUser):
    if r.employee_id == cu.id:
        raise HTTPException(403, "You can't process your own return or clearance.")


def _asset_item(a: Asset) -> ReturnItem:
    return ReturnItem(item_key=f"a-{a.id}", kind="asset", asset_id=a.id, tag=a.id, name=a.name, serial=a.serial,
                      cost=a.cost, book_value=round(book_value(a)), state="Pending", recovery=0)


def _open_items_for(db: Session, asset_ids: list[str]) -> set[str]:
    rows = db.execute(select(ReturnItem.asset_id).join(AssetReturn, AssetReturn.id == ReturnItem.return_id)
                      .where(ReturnItem.asset_id.in_(asset_ids), ReturnItem.state == "Pending", AssetReturn.stage.in_(OPEN_RETURN_STAGES))).scalars().all()
    return set(rows)


def _undeclared(db: Session, r: AssetReturn) -> list[Asset]:
    if r.type != "exit" or r.stage not in OPEN_RETURN_STAGES:
        return []
    listed = {i.asset_id for i in r.items if i.asset_id}
    held = db.execute(select(Asset).where(Asset.assigned_to == r.employee_id)).scalars().all()
    return [a for a in held if a.id not in listed]


class ReturnIn(BaseModel):
    assetIds: list[str] = Field(min_length=1)
    reason: str = "Routine return"
    plannedAt: str | None = None
    note: str = ""


@router.post("/returns")
def create_return(b: ReturnIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    if b.reason not in RETURN_REASONS:
        raise HTTPException(400, "Choose a reason.")
    assets = [get_asset(db, x) for x in dict.fromkeys(b.assetIds)]
    if any(a.assigned_to != cu.id for a in assets):
        raise HTTPException(403, "You can only return assets allocated to you.")
    if _open_items_for(db, [a.id for a in assets]):
        raise HTTPException(409, "A return is already in progress for one of these assets.")
    now = utcnow(); planned = parse_dt(b.plannedAt)
    r = AssetReturn(id=next_id(db, "RET"), type="return", employee_id=cu.id, reason=b.reason, note=b.note.strip()[:4000] or None,
                    planned_at=planned, stage="Awaiting handover", created_at=now, updated_at=now)
    r.items = [_asset_item(a) for a in assets]
    db.add(r)
    hist_return(r, cu.id, f"{b.reason}: {len(assets)} asset{'s' if len(assets) > 1 else ''} to hand over" + (f" on {planned:%d %b %Y %H:%M} UTC" if planned else ""))
    db.commit()
    return return_json(_load(db, r.id))


class ExitIn(BaseModel):
    lastDay: str
    reason: str = "Resignation"
    department: str = ""
    personalEmail: str = ""
    assetIds: list[str] = []
    otherItems: list[str] = []
    note: str = ""
    confirm: bool


@router.post("/exits")
def create_exit(b: ExitIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    if not b.confirm:
        raise HTTPException(400, "Confirm that the list is complete.")
    if b.reason not in EXIT_REASONS:
        raise HTTPException(400, "Choose a reason.")
    try:
        last_day = date.fromisoformat(b.lastDay)
    except ValueError:
        raise HTTPException(400, "Enter your last working day.")
    if db.execute(select(AssetReturn).where(AssetReturn.employee_id == cu.id, AssetReturn.type == "exit",
                                            AssetReturn.stage.in_(OPEN_RETURN_STAGES))).first():
        raise HTTPException(409, "You already have an exit clearance in progress.")
    assets = [get_asset(db, x) for x in dict.fromkeys(b.assetIds)]
    if any(a.assigned_to != cu.id for a in assets):
        raise HTTPException(403, "List only assets allocated to you.")
    others = [o.strip()[:200] for o in b.otherItems if o.strip()]
    if not assets and not others:
        raise HTTPException(400, "List at least one item to return.")
    now = utcnow()
    r = AssetReturn(id=next_id(db, "EXT"), type="exit", employee_id=cu.id, reason=b.reason, last_day=last_day,
                    department=b.department.strip()[:120] or None, personal_email=b.personalEmail.strip()[:255] or None,
                    note=b.note.strip()[:4000] or None, stage="Asset handover", created_at=now, updated_at=now)
    r.items = [_asset_item(a) for a in assets] + [ReturnItem(item_key=f"o-{i}", kind="other", name=o, state="Pending", recovery=0) for i, o in enumerate(others)]
    db.add(r)
    held = db.execute(select(Asset.id).where(Asset.assigned_to == cu.id)).scalars().all()
    skipped = len(set(held) - {a.id for a in assets})
    n = len(r.items)
    hist_return(r, cu.id, f"Exit clearance submitted — {n} item{'s' if n > 1 else ''} to return" + (f", {skipped} allocated asset{'s' if skipped > 1 else ''} not listed" if skipped else ""))
    # routine returns for the same assets are folded into the exit
    listed = {a.id for a in assets}
    for o in db.execute(select(AssetReturn).where(AssetReturn.employee_id == cu.id, AssetReturn.type == "return",
                                                  AssetReturn.stage == "Awaiting handover").options(selectinload(AssetReturn.items), selectinload(AssetReturn.history))).scalars():
        if all(i.asset_id in listed for i in o.items if i.state == "Pending"):
            o.stage = "Withdrawn"; hist_return(o, cu.id, f"Merged into exit clearance {r.id}")
    db.commit()
    return return_json(_load(db, r.id))


class ReceiveIn(BaseModel):
    condition: str = Field(pattern="^(Good|Damaged|Missing)$")
    recovery: float = Field(default=0, ge=0)
    note: str = ""


@router.post("/returns/{rid}/items/{key}/receive")
def receive(rid: str, key: str, b: ReceiveIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("returns.receive")
    r = _load(db, rid, lock=True); _not_self(r, cu)
    if r.stage not in ("Asset handover", "Awaiting handover"):
        raise HTTPException(409, "Handover is already complete.")
    item = next((i for i in r.items if i.item_key == key), None)
    if not item:
        raise HTTPException(404, "Item not found.")
    now = utcnow(); first = item.state == "Pending"
    item.state = "Missing" if b.condition == "Missing" else "Received"
    item.condition = None if b.condition == "Missing" else b.condition
    item.recovery = round(b.recovery, 2); item.note = b.note.strip()[:500] or None; item.by_user = cu.id; item.at = now
    if first and item.asset_id:
        a = get_asset(db, item.asset_id, lock=True)
        if a.assigned_to == r.employee_id:
            take_back(db, a, "Lost" if b.condition == "Missing" else b.condition, f"{r.id}" + (f" — {b.note.strip()}" if b.note.strip() else ""), now, cu.id)
    hist_return(r, cu.id, f"{item.name}: {'not returned' if b.condition == 'Missing' else 'received ' + b.condition.lower()}" + (f", recovery {money(b.recovery)}" if b.recovery else ""))
    db.flush()
    if not any(i.state == "Pending" for i in r.items) and not _undeclared(db, r):
        r.stage = "IT manager review" if r.type == "exit" else "Completed"
        hist_return(r, cu.id, "All items accounted for — sent to the IT manager for sign-off" if r.type == "exit" else "Return completed")
    db.commit()
    return return_json(_load(db, r.id))


class AddAssetIn(BaseModel):
    assetId: str


@router.post("/returns/{rid}/add-asset")
def add_asset(rid: str, b: AddAssetIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("returns.receive")
    r = _load(db, rid, lock=True); _not_self(r, cu)
    if r.type != "exit" or r.stage not in OPEN_RETURN_STAGES:
        raise HTTPException(409, "Assets can only be added to an open exit clearance.")
    a = get_asset(db, b.assetId)
    if a.assigned_to != r.employee_id or any(i.asset_id == a.id for i in r.items):
        raise HTTPException(409, "That asset isn't held by this employee, or is already listed.")
    r.items.append(_asset_item(a)); r.stage = "Asset handover"
    hist_return(r, cu.id, f"Added {a.id} {a.name} — allocated but not listed by the employee")
    db.commit()
    return return_json(_load(db, r.id))


@router.post("/returns/{rid}/withdraw")
def withdraw(rid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    r = _load(db, rid, lock=True)
    if r.employee_id != cu.id or r.stage not in ("Asset handover", "Awaiting handover") or any(i.state != "Pending" for i in r.items):
        raise HTTPException(409, "This can't be withdrawn now.")
    r.stage = "Withdrawn"; hist_return(r, cu.id, "Withdrawn by the employee")
    db.commit()
    return return_json(_load(db, r.id))


class SignIn(BaseModel):
    approve: bool
    comment: str = ""
    deduction: float | None = Field(default=None, ge=0)


@router.post("/returns/{rid}/it-signoff")
def it_signoff(rid: str, b: SignIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("exits.itApprove")
    r = _load(db, rid, lock=True); _not_self(r, cu)
    if r.type != "exit" or r.stage != "IT manager review":
        raise HTTPException(409, "This clearance isn't waiting for the IT manager.")
    c = b.comment.strip()
    if b.approve:
        if any(i.state == "Pending" for i in r.items) or _undeclared(db, r):
            raise HTTPException(409, "Items are still pending or the employee holds unlisted assets.")
        r.stage = "Finance review"; r.it_signoff_by = cu.id; r.it_signoff_at = utcnow(); r.it_comment = c or None
        hist_return(r, cu.id, "IT manager signed off" + (f": {c}" if c else ""))
    else:
        if not c:
            raise HTTPException(400, "Say what needs fixing before sending it back.")
        r.stage = "Asset handover"; hist_return(r, cu.id, f"Sent back by IT manager: {c}")
    db.commit()
    return return_json(_load(db, r.id))


@router.post("/returns/{rid}/finance-signoff")
def finance_signoff(rid: str, b: SignIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("exits.financeApprove")
    r = _load(db, rid, lock=True); _not_self(r, cu)
    if r.type != "exit" or r.stage != "Finance review":
        raise HTTPException(409, "This clearance isn't waiting for Finance.")
    c = b.comment.strip(); now = utcnow()
    if b.approve:
        ded = round(b.deduction or 0, 2)
        r.stage = "Cleared"; r.cleared_at = now; r.fin_signoff_by = cu.id; r.fin_signoff_at = now; r.fin_comment = c or None
        r.fin_deduction = ded; r.ff_status = "Scheduled" if ded > 0 else None
        hist_return(r, cu.id, f"Finance signed off — cleared for full and final settlement, deduction {money(ded)}" + (f". {c}" if c else ""))
        for s in db.execute(select(Sale).where(Sale.employee_id == r.employee_id, Sale.stage == "Sold")
                            .options(selectinload(Sale.schedule), selectinload(Sale.history))).scalars():
            pending = [i for i in s.schedule if i.status == "Scheduled"]
            for i in pending:
                i.status = "Recovered in F&F"; i.at = now; i.by_user = cu.id
            if pending:
                hist_sale(s, cu.id, f"Remaining balance recovered in full and final settlement ({r.id})")
    else:
        if not c:
            raise HTTPException(400, "Say what needs fixing before sending it back.")
        r.stage = "IT manager review"; r.it_signoff_by = None; r.it_signoff_at = None; r.it_comment = None
        hist_return(r, cu.id, f"Sent back by Finance: {c}")
    db.commit()
    return return_json(_load(db, r.id))


@router.get("/returns/{rid}/outstanding")
def outstanding(rid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    r = _load(db, rid); _visible(r, cu)
    return {"outstanding": outstanding_for(db, r.employee_id)}


@router.get("/returns/{rid}/certificate", response_class=HTMLResponse)
def certificate(rid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    r = _load(db, rid); _visible(r, cu)
    if r.stage != "Cleared":
        raise HTTPException(409, "The certificate is available once Finance has signed off.")
    cur = get_config(db).get("currency", "INR")
    rows = "".join(f"<tr><td>{escape(i.tag or '')}</td><td>{escape(i.name)}</td><td>{escape(i.serial or '')}</td>"
                   f"<td>{'Not returned' if i.state == 'Missing' else 'Received' + (' (' + i.condition.lower() + ')' if i.condition else '')}</td>"
                   f"<td style='text-align:right'>{money(i.recovery, cur) if float(i.recovery or 0) else '—'}</td></tr>" for i in r.items)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Clearance certificate {r.id}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:760px;margin:2rem auto;color:#16213A}}table{{width:100%;border-collapse:collapse;margin:1rem 0}}td,th{{border:1px solid #ccd;padding:.4rem .5rem;text-align:left}}.sig{{display:flex;gap:2rem;margin-top:2rem}}.sig div{{flex:1;border-top:1px solid #16213A;padding-top:.4rem}}</style></head><body>
<h1>Asset clearance certificate</h1><p>Reference <b>{r.id}</b> · issued {r.fin_signoff_at:%d %b %Y}</p>
<p>This certifies that <b>{escape(user_name(db, r.employee_id))}</b>{' (' + escape(r.department) + ')' if r.department else ''}, last working day {r.last_day:%d %b %Y}, has completed asset clearance.</p>
<table><thead><tr><th>Tag</th><th>Item</th><th>Serial</th><th>Outcome</th><th>Recovery</th></tr></thead><tbody>{rows}</tbody></table>
<p><b>Deduction in full and final settlement: {money(r.fin_deduction, cur)}</b></p>{'<p>Finance note: ' + escape(r.fin_comment) + '</p>' if r.fin_comment else ''}
<div class="sig"><div>IT manager<br><b>{escape(user_name(db, r.it_signoff_by))}</b><br>{r.it_signoff_at:%d %b %Y %H:%M} UTC</div>
<div>Finance<br><b>{escape(user_name(db, r.fin_signoff_by))}</b><br>{r.fin_signoff_at:%d %b %Y %H:%M} UTC</div></div></body></html>"""
    return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="clearance-{r.id}.html"'})
