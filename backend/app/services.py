"""Shared business rules used by several routers."""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from .db import utcnow
from .models import (Asset, Allocation, AssetLog, AssetReturn, ReturnHistory, Sale, SaleHistory, User)
from .serialize import num

ASSET_STATUS = ["In stock", "In use", "Under repair", "Retired", "Disposed", "Sold"]
OPEN_RETURN_STAGES = {"Asset handover", "Awaiting handover", "IT manager review", "Finance review"}
OPEN_SALE_STAGES = {"Finance approval", "Employee acceptance"}


def money(v, cur="INR") -> str:
    return f"{cur} {float(v or 0):,.0f}"


def user_name(db: Session, uid: str | None) -> str:
    if not uid:
        return "—"
    u = db.get(User, uid)
    return (u.name or u.email) if u else "Someone"


def fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%d %b %Y, %H:%M UTC") if dt else "—"


def log_asset(db: Session, asset: Asset, by: str | None, text: str, at: datetime | None = None):
    asset.log.append(AssetLog(asset_id=asset.id, at=at or utcnow(), by_user=by, text=text[:1000]))
    asset.updated_at = utcnow()


def hist_return(r: AssetReturn, by: str | None, text: str):
    r.history.append(ReturnHistory(return_id=r.id, at=utcnow(), by_user=by, text=text[:1000]))
    r.updated_at = utcnow()


def hist_sale(s: Sale, by: str | None, text: str):
    s.history.append(SaleHistory(sale_id=s.id, at=utcnow(), by_user=by, text=text[:1000]))
    s.updated_at = utcnow()


def get_asset(db: Session, asset_id: str, lock: bool = False) -> Asset:
    q = select(Asset).where(Asset.id == asset_id).options(selectinload(Asset.allocations), selectinload(Asset.log))
    if lock:
        q = q.with_for_update()
    a = db.execute(q).scalar_one_or_none()
    if not a:
        raise HTTPException(404, f"Asset {asset_id} wasn't found.")
    return a


def get_user(db: Session, uid: str) -> User:
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "That person wasn't found.")
    return u


def _close_open_allocation(asset: Asset, when: datetime, condition: str, note: str = ""):
    closed = False
    for x in asset.allocations:
        if x.until_at is None:
            x.until_at = when; x.return_condition = condition; x.return_note = (note or "")[:500]; closed = True
    if not closed and asset.assigned_to:  # data imported without allocation rows
        asset.allocations.append(Allocation(asset_id=asset.id, employee_id=asset.assigned_to, from_at=asset.allocated_at or when,
                                            until_at=when, return_condition=condition, return_note=(note or "")[:500]))


def allocate(db: Session, asset: Asset, to: User, when: datetime, note: str, by: str):
    if asset.status in ("Sold", "Disposed", "Retired"):
        raise HTTPException(409, f"{asset.id} is {asset.status.lower()} and can't be allocated.")
    if asset.assigned_to == to.id:
        raise HTTPException(409, "It's already with them.")
    if asset.assigned_to:
        _close_open_allocation(asset, when, "Reallocated")
    asset.allocations.append(Allocation(asset_id=asset.id, employee_id=to.id, from_at=when, allocated_by=by, note=(note or "")[:500]))
    asset.assigned_to = to.id; asset.allocated_at = when; asset.allocated_by = by; asset.status = "In use"
    asset.acknowledged_at = None; asset.acknowledged_by = None; asset.acknowledged_name = None
    log_asset(db, asset, by, f"Allocated to {to.name or to.email} on {fmt_dt(when)}" + (f" — {note}" if note else ""))


def take_back(db: Session, asset: Asset, condition: str, note: str, when: datetime, by: str):
    """condition: Good | Damaged | Lost"""
    if not asset.assigned_to:
        raise HTTPException(409, f"{asset.id} isn't allocated to anyone.")
    holder = user_name(db, asset.assigned_to)
    _close_open_allocation(asset, when, condition, note)
    asset.status = {"Good": "In stock", "Lost": "Retired"}.get(condition, "Under repair")
    if condition == "Lost":
        asset.disposed_at = when
    asset.assigned_to = None; asset.allocated_at = None
    asset.acknowledged_at = None; asset.acknowledged_by = None; asset.acknowledged_name = None
    log_asset(db, asset, by, f"Returned by {holder} on {fmt_dt(when)} ({condition})" + (f" — {note}" if note else ""))


def sell_asset(db: Session, asset: Asset, sale: Sale, when: datetime, by: str):
    if asset.assigned_to:
        _close_open_allocation(asset, when, "Sold to employee")
    asset.status = "Sold"; asset.disposed_at = when; asset.sold_to = sale.employee_id
    asset.sale_price = sale.price; asset.sale_id = sale.id; asset.assigned_to = None
    log_asset(db, asset, by, f"Sold to {user_name(db, sale.employee_id)} for {money(sale.price)} ({sale.id})")


def outstanding_for(db: Session, employee_id: str) -> float:
    sales = db.execute(select(Sale).where(Sale.employee_id == employee_id, Sale.stage == "Sold")
                       .options(selectinload(Sale.schedule))).scalars().all()
    return round(sum(float(i.amount) for s in sales for i in s.schedule if i.status == "Scheduled"), 2)


def add_months(month: str, n: int) -> str:
    y, m = [int(x) for x in month.split("-")]
    m0 = (m - 1) + n
    return f"{y + m0 // 12:04d}-{m0 % 12 + 1:02d}"


def build_schedule(price: float, n: int, start: str) -> list[tuple[int, str, float]]:
    price = round(float(price), 2); n = max(1, int(n))
    per = int(price / n * 100) / 100
    return [(i + 1, add_months(start, i), round(price - per * (n - 1), 2) if i == n - 1 else per) for i in range(n)]
