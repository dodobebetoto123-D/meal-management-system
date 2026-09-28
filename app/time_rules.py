from datetime import datetime


def parse_hhmm(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise ValueError("time must use HH:MM") from exc


def meal_status(now, starts_at, ends_at):
    """Return approved, before_meal, or after_meal for a timezone-local time."""
    start, end = parse_hhmm(starts_at), parse_hhmm(ends_at)
    if start >= end:
        raise ValueError("meal start must be before meal end")
    current = now.time() if hasattr(now, "time") else now
    if current < start:
        return "before_meal"
    if current >= end:
        return "after_meal"
    return "approved"
