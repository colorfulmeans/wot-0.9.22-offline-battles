"""Exact-query reuse owned by one synchronous support solve, never a frame."""

class SupportQueries(object):
    def __init__(self, clock):
        self.clock = clock
        self.started = clock()
        self.cache = {}
        self.references = []
        self.calls = {}
        self.milliseconds = {}

    def count(self, name):
        self.calls[name] = self.calls.get(name, 0)+1

    def call(self, name, function, *args, **kwargs):
        if name == 'native.projectile.armour':
            name = 'native_bsp'
        self.count(name)
        started = self.clock()
        try:
            return function(*args, **kwargs)
        finally:
            self.milliseconds[name] = self.milliseconds.get(name, 0.) + max(0.,self.clock()-started)*1000.

    def get(self, name, key, function, *args, **kwargs):
        cache = self.cache.setdefault(name, {})
        if key in cache:
            self.count(name+'_cache_hit')
            return cache[key]
        self.count(name+'_cache_miss')
        result = self.call(name, function, *args, **kwargs)
        cache[key] = result
        return result
