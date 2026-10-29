"""Fixed offline capabilities exposed through the stock #1513 settings page."""

# Stock GameplaySetting returns None when unavailable. SettingsParams forwards
# that sentinel to the original Flash control, which owns its disabled state.
LOCKED = frozenset(('gameplay_ctf', 'gameplay_domination', 'gameplay_assault',
                    'gameplay_nations', 'gameplay_epicStandard',
                    'gameplay_epicDomination', 'useServerAim'))


def pack(values):
    result = dict(values)
    for name in LOCKED:
        if name in result:
            # The stock standard-mode control is intrinsically fixed, but
            # still needs True as its displayed check value. None clears it.
            result[name] = True if name == 'gameplay_ctf' else None
    return result


def editable(diff):
    return dict((name, value) for name, value in diff.items() if name not in LOCKED)
