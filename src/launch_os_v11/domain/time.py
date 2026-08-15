from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        msg = "datetime values must be timezone-aware"
        raise ValueError(msg)
    return value
