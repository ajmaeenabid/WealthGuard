"""Decimal-safe money. Amounts are integer minor units (1/100) in storage and Decimal strings at the API."""
import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

SCALE = 100
MAX_MINOR = 10**14            # 1 trillion units; anything above is a typo
SYMBOLS = {"BDT": "৳", "CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}
DEFAULT_CURRENCY = "BDT"


class MoneyError(ValueError):
    pass


def to_minor(value, *, allow_negative: bool = False) -> int:
    """'850', '1,250.50', Decimal, int -> minor units. Floats are rejected on purpose: they are not exact."""
    if isinstance(value, float):
        raise MoneyError("Amounts must be sent as strings or integers, not floating point numbers.")
    if isinstance(value, bool) or value is None:
        raise MoneyError("An amount is required.")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise MoneyError(f"'{value}' is not a valid amount.")
    if not d.is_finite():
        raise MoneyError("The amount must be a finite number.")
    if d < 0 and not allow_negative:
        raise MoneyError("The amount cannot be negative.")
    minor = int((d * SCALE).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if abs(minor) > MAX_MINOR:
        raise MoneyError("That amount is too large.")
    return minor


def to_dec(minor: Optional[int]) -> Optional[Decimal]:
    return None if minor is None else (Decimal(minor) / SCALE).quantize(Decimal("0.01"))


def s(minor: Optional[int]) -> Optional[str]:
    """Minor units -> '850.00' (a string, never a float)."""
    return None if minor is None else f"{to_dec(minor):.2f}"


def fmt(minor: int, currency: str = DEFAULT_CURRENCY) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{SYMBOLS.get(currency, currency + ' ')}{abs(Decimal(minor) / SCALE):,.2f}"


def ratio(a: int, b: int) -> Optional[float]:
    """a / b as a float for display only (percentages), None when b is zero."""
    return None if not b else round(a / b, 4)


# ---------------------------------------------------------------------------------------------- time
_TZ = None


def tz():
    """The user's time zone (Dhaka by default; FIN_TZ overrides). Falls back to a fixed UTC+6 when tzdata is missing."""
    global _TZ
    if _TZ is None:
        import os
        name = os.environ.get("FIN_TZ", "Asia/Dhaka")
        try:
            from zoneinfo import ZoneInfo
            _TZ = ZoneInfo(name)
        except Exception:
            _TZ = timezone(timedelta(hours=6))
    return _TZ


def now() -> datetime:
    return datetime.now(tz()).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def parse_ts(value) -> str:
    """Accepts 'YYYY-MM-DD' (taken as that day at the current time of day if today, else noon) or a full ISO datetime."""
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return iso(datetime.combine(value, datetime.min.time()).replace(hour=12))
    txt = str(value).strip()
    try:
        if len(txt) == 10:
            d = date.fromisoformat(txt)
            n = now()
            return iso(n.replace(year=d.year, month=d.month, day=d.day)) if d == n.date() else iso(datetime.combine(d, datetime.min.time()).replace(hour=12))
        return iso(datetime.fromisoformat(txt.replace("Z", "")).replace(tzinfo=None))
    except ValueError:
        raise MoneyError(f"'{value}' is not a valid date.")


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    last = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))
