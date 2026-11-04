"""Date/time and money helpers (single place to change time handling)."""
import datetime as dt


def today() -> dt.date:
    return dt.date.today()


def today_iso() -> str:
    return today().isoformat()


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def in_minutes(minutes: float) -> str:
    return (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def add_days(iso: str, days: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=days)).isoformat()


def nights(check_in: str, check_out: str) -> int:
    return (dt.date.fromisoformat(check_out) - dt.date.fromisoformat(check_in)).days


def date_range(start: str, end: str):
    """Yields ISO dates from start to end inclusive."""
    d, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while d <= e:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def money(value) -> float:
    return round(float(value or 0) + 0.0, 2)
