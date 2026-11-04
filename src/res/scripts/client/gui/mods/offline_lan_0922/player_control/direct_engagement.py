"""Fixed-order shot and ammunition decisions for foreground direct fire."""
from __future__ import division

# Lower 35th percentile of the existing truncated three-sigma shell roll.
PENETRATION_FACTOR_65 = 0.9679810530375992

_HIGH_HE = {
    ('uk:GB24_Centurion_Mk3', '_105mm_Gun_L7', '_105mm_HESH_L7'),
    ('uk:GB80_Charioteer', '_105mm_AT_Gun_L7', '_105mm_HESH_L7'),
    ('uk:GB81_FV4004', '_5_5inch_AT_Gun', '_5_5inch_HESH_Mk_1'),
    ('uk:GB48_FV215b_183', '_183mm_L4', '_183mm_HESH'),
    ('uk:GB83_FV4005', '_183mm_AT_Gun', '_183mm_HESH'),
}


class DirectEngagement(object):
    def __init__(self, descriptor):
        from ..default_loadouts import value
        self.vehicle = value(value(descriptor, 'type', {}), 'name', '')
        self.gun = value(value(descriptor, 'gun', {}), 'name', '')
        self.target = None
        self.stage = None
        self.return_proof = None
        self.return_cursor = 0
        self.background = 0
        self.search_tick = 0
        self.alternate_stages = {}
        self.he_zero_hits = 0
        self.retry = 0.
        self.last_solution = None
        self.last_receipt = None

    def stages(self, policy, inventory):
        rows = [row for row in policy.shells if inventory[row['index']] > 0]
        if not rows:
            return []
        primary = next((row for row in rows if row['index'] == policy.main), rows[0])
        he = [row for row in rows if row['kind'] == 'HIGH_EXPLOSIVE']
        high_he = [row for row in he
                   if (self.vehicle, self.gun, row['name']) in _HIGH_HE]
        ordinary = sorted([row for row in he if row not in high_he],
                          key=lambda row: not row['premium'])
        primary_he = primary in ordinary
        stages = [(primary['index'], None if primary_he else PENETRATION_FACTOR_65)]
        stages.extend((row['index'], PENETRATION_FACTOR_65) for row in rows
                      if row is not primary and (row not in he or row in high_he))
        if primary in high_he:
            stages.append((primary['index'], None))
        stages.extend((row['index'], None) for row in ordinary if row is not primary)
        return stages

    def result(self, row):
        if (self.stage is None or self.stage[1] is not None or
                row['target'] != self.target or row['shell'] != self.stage[0] or
                not row.get('known') or not row.get('hit') or row.get('rejected')):
            return
        self.he_zero_hits = self.he_zero_hits + 1 if row['damage'] <= 0. else 0

    def adopt(self, target, stage):
        self.target, self.stage = target, stage
        self.return_proof = None
        self.return_cursor = 0
        self.he_zero_hits = 0
        self.last_solution = None

    def update(self, control, candidates, now):
        owner = control.owner
        gun, policy, aiming = owner._gun_state, control.ammo_policy, control.aiming
        stages = self.stages(policy, gun.ammo)
        if not candidates or not stages:
            self.adopt(None, None)
            return None, None, False
        by_id = dict((item.id, item) for item in candidates)
        if self.target not in by_id:
            self.adopt(candidates[0].id, stages[0])
        elif self.stage not in stages:
            self.adopt(self.target, stages[0])
        target = by_id[self.target]

        def scan(item, stage, physical=False):
            return aiming.ordered(item, stage[0], stage[1], now,
                                  lambda a, b: control.lane_from(item, a, b),
                                  physical=physical)

        stage = self.stage
        if gun.shot_index != stage[0]:
            control.queue_automatic_shell(stage[0])
            return None, None, False
        status, solution = scan(target, stage, physical=True)
        sample = solution.get('sample') if solution is not None else None
        receipt = (target.id, stage, status, sample)
        if status != 'pending' and receipt != self.last_receipt:
            self.last_receipt = receipt
            control.record('direct_engagement', target=target.id, shell=stage[0],
                           penetration_gate=stage[1] is not None, verdict=status, point=sample)
        if status == 'ready':
            self.last_solution = solution
        elif status == 'armor':
            next_index = stages.index(stage) + 1
            if next_index < len(stages):
                self.adopt(target.id, stages[next_index])
                control.queue_automatic_shell(self.stage[0])
                return None, None, False
        elif status in ('unavailable', 'lost'):
            self.last_solution = None

        self.alternate_stages = dict((identity, value)
            for identity, value in self.alternate_stages.items() if identity in by_id)
        self.search_tick += 1
        if (stage[1] is None and self.search_tick % 2 == 0 or
                status not in ('ready', 'laying') and now >= self.retry):
            alternatives = [item for item in candidates if item.id != target.id]
            if alternatives:
                item = alternatives[(self.background + self.search_tick // 24) % len(alternatives)]
                eligible = [other for other in stages if other[1] is not None or
                            self.he_zero_hits >= 2 or status == 'unavailable']
                if eligible:
                    other = self.alternate_stages.get(item.id)
                    if other not in eligible:
                        other = eligible[0]
                    verdict, unused = scan(item, other)
                    if verdict == 'ready':
                        self.adopt(item.id, other)
                        control.queue_automatic_shell(other[0])
                        return None, None, False
                    if verdict in ('armor', 'unavailable'):
                        self.background += 1
                        self.alternate_stages[item.id] = eligible[
                            (eligible.index(other) + 1) % len(eligible)]
        if status == 'ready':
            self.retry = now + .7
        if stage != stages[0] and (gun.reload_time > 0. or status != 'ready'):
            earlier_stages = [earlier for earlier in stages[:stages.index(stage)]
                              if earlier[1] is not None]
            if earlier_stages:
                proof_stage = self.return_proof[0] if self.return_proof else None
                earlier = (proof_stage if proof_stage in earlier_stages else
                           earlier_stages[self.return_cursor % len(earlier_stages)])
                verdict, better = scan(target, earlier)
                if verdict == 'ready':
                    key = (earlier, better['key'])
                    if self.return_proof == key:
                        self.adopt(target.id, earlier)
                        control.queue_automatic_shell(earlier[0])
                        return None, None, False
                    self.return_proof = key
                elif verdict in ('armor', 'unavailable', 'lost'):
                    self.return_proof = None
                    self.return_cursor += 1
        if status == 'ready':
            return target, solution, True
        if status == 'laying':
            return target, solution, False
        if solution is not None and solution.get('geometry_clear'):
            return target, solution, False
        if (status == 'pending' and self.last_solution is not None and
                now - self.last_solution['created'] < .5):
            return target, self.last_solution, False
        return None, None, False
