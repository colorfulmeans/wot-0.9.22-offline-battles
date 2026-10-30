"""Beijing 08:00 resets coincide with UTC midnight; no external calendar."""
import calendar
import time

DAY = 86400


def bounds(now, period='day'):
    day = int(now) // DAY
    date = time.gmtime(day * DAY)
    if period == 'week':
        start = day - date.tm_wday
        return start * DAY, (start + 7) * DAY
    if period == 'month':
        start = calendar.timegm((date.tm_year, date.tm_mon, 1, 0, 0, 0))
        return start, start + calendar.monthrange(date.tm_year, date.tm_mon)[1] * DAY
    return day * DAY, (day + 1) * DAY


def first_win_factor(now=None):
    return 5 if time.gmtime(time.time() if now is None else now).tm_wday >= 5 else 2
