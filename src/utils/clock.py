"""Time helpers, kept in one place so formats stay consistent."""
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())