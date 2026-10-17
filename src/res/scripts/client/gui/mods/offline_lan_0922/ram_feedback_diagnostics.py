"""Observe stock ribbon lifecycle; never hide, reset or replace its display."""


class RibbonProbe(object):
    METHODS = ('_addRibbon', '_updateRibbon', 'onShow', 'onChange', 'onHide', '_dispose')

    def __init__(self, panel_class, kinds, clock, write, token):
        self.panel_class, self.kinds = panel_class, tuple(kinds)
        self.clock, self.write, self.token = clock, write, token
        self.rows, self.methods = {}, {}
        self.last_damage = None
        self.next_poll = 0.
        # Validate the whole boundary before mutating any method.
        # Read raw functions: Python 2 class attribute access manufactures an
        # unbound method, which is not identical to the installed wrapper.
        originals = [(name, panel_class.__dict__[name]) for name in self.METHODS]
        for name, original in originals:
            if not callable(original):
                raise RuntimeError('stock ribbon observer boundary is not callable: '+name)
        for name, original in originals:
            wrapper = self._wrapper(name, original)
            self.methods[name] = (original, wrapper)
            setattr(panel_class, name, wrapper)
        self._emit('installed')

    def _emit(self, phase, **fields):
        fields.update(phase=phase, token=self.token, at=self.clock(),
                      last_damage=self.last_damage)
        try:
            self.write('RAM RIBBON LIFECYCLE', fields)
        except Exception as error:
            if not getattr(self, 'write_failed', False):
                self.write_failed = True
                import sys
                sys.stdout.write('[Offline LAN 0.9.22] ram ribbon diagnostic write failed: %s\n' % error)

    def _wrapper(self, name, original):
        def observe(panel, *args, **kwargs):
            # Diagnose only. The stock method keeps its exact arguments,
            # return value, exception and animation ownership.
            try:
                self._observe(panel, name, args, kwargs)
            except Exception as error:
                if not getattr(self, 'observe_failed', False):
                    self.observe_failed = True
                    self._emit('observer_failure', method=name, error=str(error))
            try:
                return original(panel, *args, **kwargs)
            except Exception as error:
                self._emit('stock_call_error', method=name, error=str(error))
                raise
        return observe

    def _observe(self, panel, name, args, kwargs):
        if name == '_dispose':
            for key in [key for key in self.rows if key[0] == id(panel)]:
                self._emit('dispose', ribbon=key[1], state=self.rows.pop(key))
            return
        ribbon = kwargs.get('ribbonID', args[0] if args else None)
        key = (id(panel), ribbon)
        if name in ('_addRibbon', '_updateRibbon'):
            kind = kwargs.get('ribbonType', args[1] if len(args) > 1 else None)
            if kind not in self.kinds:
                return
            row = self.rows.setdefault(key, dict(kind=kind, shown=False))
            row.update(updated=self.clock(), phase=name)
        else:
            row = self.rows.get(key)
            if row is None:
                return
            if name == 'onShow':
                row['shown'] = True
            elif name == 'onHide':
                row['shown'] = False
            row['phase'] = name
        self._emit(name, ribbon=ribbon, state=dict(row))
        if name == 'onHide':
            self.rows.pop(key, None)

    def note(self, event, received):
        self.last_damage = self.clock()
        self._emit('combat_event', event_id=event.get('event_id'),
                   damage=event.get('damage'), received=received,
                   source=event.get('source'), reason=event.get('attack_reason'))

    def poll(self):
        now = self.clock()
        if now < self.next_poll:
            return
        self.next_poll = now+5.
        for key, row in self.rows.items():
            age = now-row['updated']
            if age >= 5.:
                self._emit('no_hide_callback', ribbon=key[1], age=age,
                           state=dict(row), visibility_basis='stock_callbacks_only')

    def close(self):
        self._emit('closed', remaining=[dict(row, ribbon=key[1]) for key, row in self.rows.items()])
        for name, (original, wrapper) in self.methods.items():
            if self.panel_class.__dict__.get(name) is wrapper:
                setattr(self.panel_class, name, original)
        self.methods.clear()
        self.rows.clear()
