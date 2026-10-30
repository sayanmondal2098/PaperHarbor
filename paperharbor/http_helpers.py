"""Bounded Retry-After parsing shared by metadata and PDF requests."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(value, now=None):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return max(0.0, (deadline - (now or datetime.now(timezone.utc))).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None
