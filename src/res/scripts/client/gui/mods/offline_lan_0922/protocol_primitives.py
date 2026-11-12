"""Shared neutral protocol primitives; deliberately no network/Bot imports."""

WORKER_AUTHORITY_ID = -1

SNAPSHOT_STALL_SECONDS = 2.0

try:
    integer_types = (int, long)
except NameError:
    integer_types = (int,)

def _exact_int(value, default=None):
    if isinstance(value, bool):
        return default
    if isinstance(value, integer_types):
        return value
    try:
        parsed = int(value)
        if float(value) != parsed:
            return default
        return parsed
    except (TypeError, ValueError, OverflowError):
        return default
