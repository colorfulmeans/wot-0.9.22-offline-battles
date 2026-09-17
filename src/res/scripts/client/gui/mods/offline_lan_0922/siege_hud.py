"""Battle-scoped persistence for the stock Siege mode key hint."""


class PersistentSiegeHints(object):
    """Keep the offline hint available without spending the tutorial counter.

    The native indicator still chooses the text, key binding, animation and
    visibility for transitions, destruction, observers and postmortem.  Only
    its finite tutorial quota is bypassed, and only for this battle provider.
    AccountSettings retains its original value when the indicator disposes.
    """

    _HINT_METHOD = '_SiegeModeIndicator__updateHintView'
    _STATE_METHOD = '_SiegeModeIndicator__updateSiegeState'

    def __init__(self, indicator_type, session_provider):
        self._indicator_type = indicator_type
        self._session_provider = session_provider
        self._patches = []
        self._installed = False

    def install(self):
        if self._installed:
            return False
        indicator_type = self._indicator_type
        originals = [(name, indicator_type.__dict__[name]) for name in (
            self._HINT_METHOD, self._STATE_METHOD)]
        for name, original in originals:
            if not callable(original):
                raise RuntimeError('stock Siege hint callback is unavailable')
        owner = self

        def wrap(original, allow_hint):
            def persistent_hint(indicator, *args, **kwargs):
                if (not owner._installed or
                        indicator.sessionProvider is not owner._session_provider):
                    return original(indicator, *args, **kwargs)
                hints_left = indicator._hintsLeft
                try:
                    if allow_hint:
                        indicator._hintsLeft = 1
                    return original(indicator, *args, **kwargs)
                finally:
                    indicator._hintsLeft = hints_left
            return persistent_hint

        for name, original in originals:
            replacement = wrap(original, name == self._HINT_METHOD)
            setattr(indicator_type, name, replacement)
            self._patches.append((name, original, replacement))
        self._installed = True
        return True

    def close(self):
        self._installed = False
        for name, original, replacement in reversed(self._patches):
            # A later mod owns its own hook; never overwrite it during exit.
            if self._indicator_type.__dict__.get(name) is replacement:
                setattr(self._indicator_type, name, original)
        self._patches = []
        self._session_provider = None
