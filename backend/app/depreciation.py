"""Same depreciation maths as the browser, used when the server needs a book value
(sale offers, exit clearances). Monthly pro-rating from the in-service date."""
from datetime import date, datetime


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def yearly_dep(cost, salvage, life, method, rate) -> list[float]:
    cost = _num(cost); salv = min(_num(salvage), cost); life = max(1, int(round(_num(life) or 1)))
    base = cost - salv; out: list[float] = []; open_ = cost
    if method == "SYD":
        s = life * (life + 1) / 2
        out = [base * (life - i) / s for i in range(life)]
    elif method == "WDV":
        r = _num(rate) / 100
        if not r:
            r = 1 - (max(salv, cost * 0.05) / max(cost, 1)) ** (1 / life)
        for i in range(life):
            d = open_ - salv if i == life - 1 else open_ * r
            d = max(0.0, min(d, open_ - salv)); out.append(d); open_ -= d
    elif method == "DDB":
        r = 2 / life
        for i in range(life):
            sl = (open_ - salv) / (life - i)
            d = max(0.0, min(max(open_ * r, sl), open_ - salv)); out.append(d); open_ -= d
    else:
        out = [base / life] * life
    return out


def _months_between(a: datetime, b: datetime) -> float:
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.44


def book_value(asset, when: datetime | None = None) -> float:
    when = when or datetime.utcnow()
    start = asset.in_service_date or asset.purchase_date or date.today()
    start_dt = datetime(start.year, start.month, start.day)
    ys = yearly_dep(asset.cost, asset.salvage, asset.life_years, asset.method, asset.wdv_rate)
    m = max(0.0, min(len(ys) * 12, _months_between(start_dt, when)))
    if asset.status in ("Disposed", "Sold", "Retired") and asset.disposed_at:
        m = min(m, max(0.0, _months_between(start_dt, asset.disposed_at)))
    acc = 0.0; i = 0
    while m > 0 and i < len(ys):
        take = min(12.0, m); acc += ys[i] * take / 12; m -= take; i += 1
    return round(_num(asset.cost) - acc, 2)
