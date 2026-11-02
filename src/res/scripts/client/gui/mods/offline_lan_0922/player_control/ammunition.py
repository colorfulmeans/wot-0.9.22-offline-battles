"""Player-only shell decisions using actual inventory and ordered hit receipts."""
from __future__ import division


class Ammunition(object):
    def __init__(self, shells, main, loaded, clip_size=1, artillery=False):
        self.shells = shells
        self.main = main
        self.desired = loaded
        self.protected = True
        self.clip_size = max(1, clip_size)
        self.artillery = artillery
        self.phase = loaded
        self.fired = self.failures = 0
        self.target = None
        self.pending = []
        self.rows = {}

    def available(self, inventory):
        return [s['index'] for s in self.shells if inventory[s['index']] > 0]

    def choose(self, inventory):
        available = self.available(inventory)
        if self.desired not in available and available:
            self.desired = available[0]
        return self.desired

    def launch(self, projectile, shell, target, now):
        if projectile in self.rows:
            return
        if shell != self.phase:
            self.phase, self.fired, self.failures = shell, 0, 0
        if target != self.target:
            self.target, self.failures = target, 0
        self.fired += 1
        row = dict(id=projectile, shell=shell, target=target, launched=now,
                   terminal=None, hit=None, damage=0., penetrated=False)
        self.rows[projectile] = row
        self.pending.append(row)
        if self.protected:
            self.protected = False
            self.desired = self.main

    def hit(self, event):
        row = self.rows.get(str(event.get('projectile_id')))
        if row is not None:
            row['hit'] = True
            row['damage'] += max(0., float(event.get('damage', 0)))
            row['penetrated'] |= int(event.get('shot_result', -1)) == 2

    def terminal(self, event, now):
        row = self.rows.get(str(event.get('projectile_id')))
        if row is not None and row['terminal'] is None:
            row['terminal'] = now
            row['vehicle_contact'] = bool(event.get('hit_vehicle'))

    def settle(self, inventory, now):
        results = []
        while self.pending:
            row = self.pending[0]
            if row['terminal'] is None:
                break
            # The server deliberately publishes impact BEFORE combat effects.
            # A contact flag is not a zero-damage receipt. Wait for the effect;
            # missing feedback is unknown and never counts as a failure.
            unknown = row['vehicle_contact'] and row['hit'] is None
            if unknown and now-row['terminal'] < 2.:
                break
            self.pending.pop(0)
            self.rows.pop(row['id'], None)
            row['known'] = not unknown
            results.append(row)
            if row['target'] != self.target or row['shell'] != self.phase:
                continue
            if unknown:
                self.failures = 0
                continue
            shell = next(s for s in self.shells if s['index'] == row['shell'])
            main = next(s for s in self.shells if s['index'] == self.main)
            success = row['damage'] > 0
            he_main = main['kind'] == 'HIGH_EXPLOSIVE'
            if he_main and row['shell'] == self.main and not self.artillery:
                success = row['penetrated']
            if success:
                self.failures = 0
            elif row['hit'] or (self.artillery and not row['vehicle_contact']):
                self.failures += 1
            available = self.available(inventory)
            # Alternate HE returns after two fired rounds, irrespective of hits;
            # HE-primary's AP probe returns after one. A live clip is retained.
            limit = self.clip_size if self.clip_size > 1 else (1 if he_main and not self.artillery else 2)
            if (row['shell'] != self.main and self.fired >= limit and
                    (he_main or shell['kind'] == 'HIGH_EXPLOSIVE' or self.clip_size > 1)):
                self.desired = self.main if self.main in available else self.choose(inventory)
            elif self.failures >= 2 and row['shell'] in available and len(available) > 1:
                self.desired = available[(available.index(row['shell'])+1) % len(available)]
                self.failures = 0
        return results
