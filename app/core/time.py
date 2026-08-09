"""
Timezone helpers.

Python 3.12+ deprecates ``datetime.utcnow()``. SQLite and the existing
serializers expect *naive* UTC datetimes, so we build the same value via
timezone-aware arithmetic instead of switching storage to tz-aware values
(which would change the DB format and can trip up the sqlite driver).
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (DB-friendly)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
