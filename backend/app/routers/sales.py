"""Selling company assets to employees, with salary-deduction schedules and the monthly payroll input."""
import csv, io, re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..db import get_db, next_id, utcnow
from ..depreciation import book_value
from ..models import AssetReturn, Sale, SaleInstalment
from ..security import CurrentUser, current_user
from ..serialize import sale_json
from ..services import OPEN_SALE_STAGES, build_schedule, get_asset, get_user, hist_return, hist_sale, money, sell_asset, user_name

router = APIRouter(prefix="/api")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _load(db, sid, lock=False) -> Sale:
    q = select(Sale).where(Sale.id == sid).options(selectinload(Sale.schedule), selectinload(Sale.history))
    if lock:
        q = q.with_for_update()
    s = db.execute(q).scalar_one_or_none()
    if not s:
        raise HTTPException(404, f"{sid} wasn't found.")
    return s


class SaleIn(BaseModel):
    assetId: str
    employeeId: str
    price: float = Field(gt=0)
    instalments: int = Field(ge=1, le=24)
    startMonth: str
    note: str = ""


@router.post("/sales")
def create_sale(b: SaleIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("sales.create")
    if b.employeeId == cu.id:
        raise HTTPException(400, "You can't create a sale to yourself.")
    if not MONTH.match(b.startMonth):
        raise HTTPException(400, "Pick the first salary month.")
    a = get_asset(db, b.assetId, lock=True); emp = get_user(db, b.employeeId)
    if a.status in ("Sold", "Disposed"):
        raise HTTPException(409, f"{a.id} can't be sold.")
    if db.execute(select(Sale).where(Sale.asset_id == a.id, Sale.stage.in_(OPEN_SALE_STAGES))).first():
        raise HTTPException(409, "There's already an open offer for this asset.")
    now = utcnow(); fin = cu.can("sales.approve")
    s = Sale(id=next_id(db, "SAL"), asset_id=a.id, tag=a.id, name=a.name, serial=a.serial, employee_id=emp.id, price=round(b.price, 2),
             cost_at_offer=a.cost, book_value_at_offer=round(book_value(a)), instalments=b.instalments, start_month=b.startMonth,
             note=b.note.strip()[:500] or None, stage="Employee acceptance" if fin else "Finance approval", created_by=cu.id,
             created_at=now, updated_at=now, fin_by=cu.id if fin else None, fin_at=now if fin else None, fin_comment="Created by Finance" if fin else None)
    s.schedule = [SaleInstalment(no=n, month=m, amount=amt, status="Scheduled") for n, m, amt in build_schedule(b.price, b.instalments, b.startMonth)]
    db.add(s)
    hist_sale(s, cu.id, f"Offer created: {money(b.price)} over {b.instalments} month{'s' if b.instalments > 1 else ''} from {b.startMonth}")
    db.commit()
    return sale_json(_load(db, s.id))


class Decision(BaseModel):
    approve: bool
    comment: str = ""


@router.post("/sales/{sid}/approve")
def approve(sid: str, b: Decision, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("sales.approve")
    s = _load(db, sid, lock=True)
    if s.stage != "Finance approval":
        raise HTTPException(409, "This offer isn't waiting for Finance.")
    if cu.id in (s.created_by, s.employee_id):
        raise HTTPException(403, "Another Finance approver must review this offer.")
    c = b.comment.strip()
    if b.approve:
        s.stage = "Employee acceptance"; s.fin_by = cu.id; s.fin_at = utcnow(); s.fin_comment = c or None
        hist_sale(s, cu.id, "Approved by Finance" + (f": {c}" if c else ""))
    else:
        if not c:
            raise HTTPException(400, "Give a reason for rejecting.")
        s.stage = "Rejected"; hist_sale(s, cu.id, f"Rejected by Finance: {c}")
    db.commit()
    return sale_json(_load(db, s.id))


class Accept(BaseModel):
    accept: bool
    consent: bool = False
    name: str = ""


@router.post("/sales/{sid}/accept")
def accept(sid: str, b: Accept, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    s = _load(db, sid, lock=True)
    if s.employee_id != cu.id or s.stage != "Employee acceptance":
        raise HTTPException(409, "This offer isn't waiting for you.")
    now = utcnow()
    if not b.accept:
        s.stage = "Declined"; hist_sale(s, cu.id, "Declined by the employee")
    else:
        if not b.consent or len(b.name.strip()) < 2:
            raise HTTPException(400, "Authorise the salary deductions and type your full name.")
        a = get_asset(db, s.asset_id, lock=True) if s.asset_id else None
        if a is None or a.status in ("Sold", "Disposed"):
            raise HTTPException(409, "The asset is no longer available.")
        s.book_value_at_sale = round(book_value(a, now))
        s.stage = "Sold"; s.sold_at = now; s.accepted_at = now; s.accepted_name = b.name.strip()
        hist_sale(s, cu.id, f"Accepted by {b.name.strip()} — salary deductions authorised")
        sell_asset(db, a, s, now, cu.id)
    db.commit()
    return sale_json(_load(db, s.id))


@router.post("/sales/{sid}/cancel")
def cancel(sid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    s = _load(db, sid, lock=True)
    if s.stage not in OPEN_SALE_STAGES or s.employee_id == cu.id or not (s.created_by == cu.id or cu.can("sales.approve")):
        raise HTTPException(409, "This offer can't be cancelled.")
    s.stage = "Cancelled"; hist_sale(s, cu.id, "Offer cancelled")
    db.commit()
    return sale_json(_load(db, s.id))


def _payroll_lines(db: Session, month: str) -> list[dict]:
    lines = []
    for s in db.execute(select(Sale).where(Sale.stage == "Sold").options(selectinload(Sale.schedule))).scalars():
        for i in s.schedule:
            if i.month == month:
                lines.append({"kind": "sale", "ref": s.id, "no": i.no, "employeeId": s.employee_id, "amount": float(i.amount), "status": i.status,
                              "what": f"Asset purchase — {s.name}, serial {s.serial or '—'} (instalment {i.no} of {s.instalments})", "link": f"sales/{s.id}"})
    for r in db.execute(select(AssetReturn).where(AssetReturn.type == "exit", AssetReturn.stage == "Cleared", AssetReturn.fin_deduction > 0)).scalars():
        if r.last_day and r.last_day.strftime("%Y-%m") == month:
            lines.append({"kind": "exit", "ref": r.id, "no": None, "employeeId": r.employee_id, "amount": float(r.fin_deduction), "status": r.ff_status or "Scheduled",
                          "what": f"Full and final settlement deduction — exit clearance {r.id}", "link": f"exits/{r.id}"})
    names = {}
    return sorted(lines, key=lambda l: names.setdefault(l["employeeId"], user_name(db, l["employeeId"])).lower())


def _payroll_access(cu: CurrentUser):
    cu.require("payroll.view", "sales.approve")


@router.get("/payroll")
def payroll(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    _payroll_access(cu)
    return {"month": month, "lines": _payroll_lines(db, month)}


@router.get("/payroll.csv")
def payroll_csv(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    _payroll_access(cu)
    from ..models import User
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Salary month", "Employee", "Email", "Reference", "Deduction for", "Amount", "Status"])
    for l in _payroll_lines(db, month):
        u = db.get(User, l["employeeId"])
        w.writerow([month, u.name if u else "", u.email if u else "", l["ref"], l["what"], f"{l['amount']:.2f}", l["status"]])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="salary-deductions-{month}.csv"'})


class DeductRef(BaseModel):
    kind: str = Field(pattern="^(sale|exit)$")
    ref: str
    no: int | None = None


class DeductIn(BaseModel):
    lines: list[DeductRef] = Field(min_length=1)


@router.post("/payroll/deduct")
def deduct(b: DeductIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("sales.approve")
    now = utcnow(); by_sale: dict[str, list[int]] = {}
    for l in b.lines:
        if l.kind == "sale":
            by_sale.setdefault(l.ref, []).append(int(l.no or 0))
        else:
            r = db.execute(select(AssetReturn).where(AssetReturn.id == l.ref).options(selectinload(AssetReturn.history))).scalar_one_or_none()
            if r and r.stage == "Cleared" and r.ff_status != "Deducted":
                r.ff_status = "Deducted"; r.ff_deducted_at = now
                hist_return(r, cu.id, f"F&F deduction of {money(r.fin_deduction)} processed in payroll")
    for sid, nos in by_sale.items():
        s = _load(db, sid, lock=True)
        done = []
        for i in s.schedule:
            if i.no in nos and i.status == "Scheduled":
                i.status = "Deducted"; i.at = now; i.by_user = cu.id; done.append(i.no)
        if done:
            hist_sale(s, cu.id, f"Deducted in payroll: instalment{'s' if len(done) > 1 else ''} {', '.join(map(str, done))}")
    db.commit()
    return {"ok": True}
