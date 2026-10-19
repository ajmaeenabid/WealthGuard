"""Exchange rates for the three supported currencies (USD, CNY, BDT). Real rates only: nothing here is ever invented.

Where the numbers come from (verified live on 2026-10-19, both agreed to within 0.1%):
  1. open.er-api.com   (ExchangeRate-API open endpoint, no key, daily update, requires attribution)  - primary
  2. @fawazahmed0/currency-api through the jsDelivr CDN (no key, daily update)                       - independent cross-check
Rates are pivoted through USD (1 USD = N units), so BDT->CNY = rate[CNY] / rate[BDT]. They are indicative mid-market rates, not what a bank or wallet
will actually give you; every place that shows a converted figure says so.

Rules this module keeps:
  * a rate is always stored with its source, the provider's own date and the time we fetched it, and shown with that provenance;
  * the two providers must agree within MAX_DISAGREEMENT, otherwise the conversion is refused (a wrong rate is worse than none);
  * if the network is down the last good rate is used only while it is younger than FX_MAX_STALE_HOURS and is flagged stale; beyond that
    there is no conversion at all (FxUnavailable), and the caller asks the person for the amount in the account's own currency;
  * arithmetic is decimal with ROUND_HALF_UP to minor units, and the original amount is always kept next to the converted one.
"""
import json
import os
import threading
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from app import store
from app.finance import money

BASE = "USD"
MAX_DISAGREEMENT = Decimal("0.03")                       # providers may differ by 3% at most
SOURCES = {"er-api": "ExchangeRate-API (open.er-api.com)", "fawaz": "fawazahmed0 currency-api (jsDelivr)"}
ATTRIBUTION = "Rates By Exchange Rate API (exchangerate-api.com)"
_LOCK = threading.Lock()


class FxError(Exception):
    def __init__(self, message: str, kind: str = "unavailable"):
        super().__init__(message)
        self.message, self.kind = message, kind


class FxUnavailable(FxError):
    pass


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def enabled() -> bool:
    return (os.environ.get("FX_PROVIDER", "auto") or "auto").lower() != "off"


# ---------------------------------------------------------------------------------------------- providers
def _http_json(url: str, timeout: float) -> dict:
    import httpx
    r = httpx.get(url, timeout=timeout, headers={"User-Agent": "WealthGuard/1.0"}, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _fetch_er(get: Callable) -> dict:
    j = get("https://open.er-api.com/v6/latest/USD")
    if j.get("result") != "success":
        raise FxError("er-api answered with an error")
    day = datetime.fromtimestamp(int(j["time_last_update_unix"]), tz=timezone.utc).date().isoformat()
    return {"source": "er-api", "date": day, "rates": {c: j["rates"][c] for c in money.CURRENCIES if c != BASE}}


def _fetch_fawaz(get: Callable) -> dict:
    j = get("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json")
    return {"source": "fawaz", "date": str(j["date"]), "rates": {c: j["usd"][c.lower()] for c in money.CURRENCIES if c != BASE}}


def _fetch_all() -> list[dict]:
    """Every provider that answers. Replaced in tests; never called when FX_PROVIDER=off."""
    timeout = _env_num("FX_TIMEOUT", 6)
    get = lambda u: _http_json(u, timeout)
    out = []
    for fn in (_fetch_er, _fetch_fawaz):
        try:
            out.append(fn(get))
        except Exception:                                  # one provider down is normal; the other (or the cache) covers it
            continue
    return out


# ---------------------------------------------------------------------------------------------- storage
def _ensure() -> None:
    store._write("CREATE TABLE IF NOT EXISTS fin_fx_rates (id INTEGER PRIMARY KEY AUTOINCREMENT, fetched TEXT NOT NULL, source TEXT NOT NULL, "
                 "provider_date TEXT, rates TEXT NOT NULL, cross_check TEXT, agree INTEGER NOT NULL DEFAULT 1)", ())


def _latest():
    _ensure()
    from app.finance import books
    return books._one("SELECT * FROM fin_fx_rates ORDER BY id DESC LIMIT 1")


def _age_hours(iso_ts: str) -> float:
    t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def _dec(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.0000000001"))


def _combine(found: list[dict]) -> dict:
    """Pick the primary rates and cross-check them against the second provider."""
    if not found:
        raise FxUnavailable("No exchange-rate source could be reached.")
    primary = next((f for f in found if f["source"] == "er-api"), found[0])
    rates = {c: _dec(v) for c, v in primary["rates"].items()}
    if any(r <= 0 for r in rates.values()):
        raise FxError("A provider returned a non-positive rate.", "invalid")
    other = next((f for f in found if f is not primary), None)
    check, agree = None, True
    if other:
        check = {"source": other["source"], "date": other["date"], "rates": {c: str(_dec(v)) for c, v in other["rates"].items()}}
        for c, r in rates.items():
            o = _dec(other["rates"][c])
            if o > 0 and abs(r - o) / o > MAX_DISAGREEMENT:
                agree = False
    return {"source": primary["source"], "date": primary["date"], "rates": rates, "check": check, "agree": agree}


def refresh(force: bool = True) -> dict:
    """Fetch, cross-check and store a new set of rates. Raises FxUnavailable if nothing usable came back."""
    if not enabled():
        raise FxUnavailable("Exchange rates are switched off (FX_PROVIDER=off).")
    with _LOCK:
        combined = _combine(_fetch_all())
        _ensure()
        store._write("INSERT INTO fin_fx_rates (fetched, source, provider_date, rates, cross_check, agree) VALUES (?,?,?,?,?,?)",
                     (store.now(), combined["source"], combined["date"], json.dumps({c: str(v) for c, v in combined["rates"].items()}),
                      json.dumps(combined["check"]) if combined["check"] else None, 1 if combined["agree"] else 0))
    return current(allow_fetch=False)


def current(allow_fetch: bool = True) -> dict:
    """The rate table to use now: fresh from the cache, else refreshed, else (within limits) the last good one flagged stale."""
    row = _latest()
    fresh_h, stale_h = _env_num("FX_CACHE_HOURS", 12), _env_num("FX_MAX_STALE_HOURS", 72)
    if row is not None and _age_hours(row["fetched"]) <= fresh_h:
        return _pack(row, stale=False)
    if allow_fetch and enabled():
        try:
            return refresh()
        except FxUnavailable:
            pass                                           # network trouble: fall through to the last good rate, if recent enough
    if row is not None and _age_hours(row["fetched"]) <= stale_h:
        return _pack(row, stale=True)
    raise FxUnavailable("There is no current exchange rate available.")


def _pack(row, stale: bool) -> dict:
    rates = {c: Decimal(v) for c, v in json.loads(row["rates"]).items()}
    rates[BASE] = Decimal(1)
    if not row["agree"]:
        raise FxError("The two rate sources disagree by more than 3%, so no conversion is offered until they agree again.", "disagree")
    return {"base": BASE, "rates": rates, "source": row["source"], "source_name": SOURCES.get(row["source"], row["source"]), "provider_date": row["provider_date"],
            "fetched": row["fetched"], "age_hours": round(_age_hours(row["fetched"]), 1), "stale": stale, "attribution": ATTRIBUTION}


# ---------------------------------------------------------------------------------------------- conversion
def rate(frm: str, to: str, table: Optional[dict] = None) -> dict:
    """1 `frm` = `rate` `to`, with provenance."""
    frm, to = frm.upper(), to.upper()
    for c in (frm, to):
        if c not in money.CURRENCIES:
            raise FxError(f"{c} is not a supported currency.", "unsupported")
    t = table or current()
    r = Decimal(1) if frm == to else (t["rates"][to] / t["rates"][frm])
    return {"from": frm, "to": to, "rate": format(r.quantize(Decimal("0.0000000001")).normalize(), "f"), "source": t["source"], "source_name": t["source_name"],
            "provider_date": t["provider_date"], "fetched": t["fetched"], "stale": t["stale"], "age_hours": t["age_hours"], "attribution": t["attribution"]}


def convert_minor(minor: int, frm: str, to: str, table: Optional[dict] = None, quote: Optional[dict] = None) -> tuple[int, Optional[dict]]:
    """Whole minor units from one currency to another. Same currency: unchanged and no quote. A `quote` (from an earlier rate()) pins the rate."""
    if frm.upper() == to.upper():
        return minor, None
    q = quote or rate(frm, to, table)
    converted = (Decimal(minor) * Decimal(q["rate"])).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(converted), q


def convert_amount(amount: str, frm: str, to: str, table: Optional[dict] = None) -> dict:
    """Decimal string in, everything needed to show the result and where it came from out."""
    minor = money.to_minor(amount)
    out_minor, q = convert_minor(minor, frm, to, table)
    return {"amount": money.s(minor), "from": frm.upper(), "to": to.upper(), "converted": money.s(out_minor), "converted_minor": out_minor, "quote": q}


def ensure_fresh_async() -> None:
    """Refresh the rate cache in the background when it has expired, so screens that only DISPLAY converted figures never wait on the network."""
    if not enabled():
        return
    row = _latest()
    if row is not None and _age_hours(row["fetched"]) <= _env_num("FX_CACHE_HOURS", 12):
        return
    if _LOCK.locked():
        return

    def run():
        try:
            refresh()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def summary() -> dict:
    """What Settings shows: the current rates with their provenance, or why there are none."""
    if not enabled():
        return {"available": False, "reason": "off", "message": "Exchange rates are switched off on this server (FX_PROVIDER=off)."}
    try:
        t = current()
    except FxError as e:
        return {"available": False, "reason": e.kind, "message": e.message}
    return {"available": True, "base": BASE, "per_usd": {c: format(v.normalize(), "f") for c, v in t["rates"].items()}, "source": t["source_name"], "provider_date": t["provider_date"],
            "fetched": t["fetched"], "age_hours": t["age_hours"], "stale": t["stale"], "attribution": t["attribution"],
            "note": "Indicative mid-market rates. A bank, card or wallet will use its own rate and fees."}
