"""Independent foreground artillery deployment and observed-shot recovery.

Authored positions are suggestions. Their height, route and current occupancy
still need the player's own navigator and native movement checks. There are no
team reservation slots, Bot actors or hidden-worker callbacks in this module.
"""
from __future__ import division
import copy
import math
from .missions import distance, horizontal, legal_support, STOP_SPEED, SETTLE_SECONDS


MAX_PARKING_GRADE = math.tan(math.radians(12.))
PARKING_CANDIDATE_BUDGET = 8


def parking_candidates(positions, team, half_length=2., half_width=1.):
    result = []
    footprint = math.hypot(half_length, half_width)
    for row in positions:
        if row.get('disabled') or int(row.get('team', 0)) != team:
            continue
        point = horizontal(row['point'])
        radius = max(0., float(row.get('radius', 2.)))
        offsets = [(0., 0.)]
        reach = min(radius * .65, max(6., footprint * 2. + 1.))
        if reach >= 4.:
            offsets.extend((math.sin(i * math.pi / 4.) * reach,
                            math.cos(i * math.pi / 4.) * reach) for i in range(8))
        for index, offset in enumerate(offsets):
            result.append(dict(id='%s:%d' % (row['id'], index), zone=row['id'],
                point=(point[0] + offset[0], point[1] + offset[1]), radius=2.,
                priority=float(row.get('priority', 0)), heading=row.get('heading')))
    return result


class Artillery(object):
    def __init__(self, positions, team, home):
        self.positions = copy.deepcopy(positions)
        self.team = int(team)
        self.home = copy.deepcopy(home)
        self.mode = 'deploying'
        self.current = None
        self.saved = None
        self.rejected = {}
        self.retry_at = 0.
        self.relocate_after = 0.
        self.chosen_at = 0.
        self.progress_at = 0.
        self.progress_position = None
        self.best_distance = None
        self.settle_at = None
        self.ready_since = None
        self.failure_count = 0
        self.failure_at = None
        self.fire_seq = None
        self.endgame_since = None
        self.failed_zone = None
        self.last_relocation_reason = None
        self.pending_candidates = None
        self.return_goal = None
        self.return_started = None
        self.return_progress_at = None
        self.return_position = None
        self.sortie_home_failed = False
        self.receipt = dict(phase=self.mode, reason='initial_deployment')

    def suspend(self, now):
        if self.mode == 'defending':
            return
        self.saved = dict(mode=self.mode, current=copy.deepcopy(self.current))
        self.mode = 'defending'
        self._reset_failure()
        self.receipt = dict(phase='defending', reason='base_alarm',
                            resume_phase=self.saved['mode'])

    def resume(self, now):
        if self.saved is None:
            return
        self.mode, self.current = self.saved['mode'], self.saved['current']
        self.saved = None
        self.chosen_at = self.progress_at = now
        self.progress_position = None
        self.best_distance = None
        self.settle_at = None
        self._reset_failure()
        if self.mode == 'sortie_return':
            self.return_started = self.return_progress_at = now
            self.return_position = None
        self.receipt = dict(phase=self.mode, reason='resumed_after_defence')

    def _reset_failure(self):
        self.ready_since = self.failure_at = None
        self.failure_count = 0

    def _occupied(self, point, state, context):
        own_radius = math.hypot(state.get('half_length', 2.), state.get('half_width', 1.))
        # Contacts/neighbours are local observations. A roster row without a
        # position cannot be used as a hidden parking reservation.
        rows = list(context.get('allies') or ()) + list(context.get('contacts') or ())
        rows += [row for row in context.get('neighbours') or ()
                 if row.get('team') == self.team or row.get('visible')]
        for row in rows:
            if row.get('id') == state.get('engine_id', state.get('id')) or row.get('position') is None:
                continue
            shape = row.get('collision_shape') or (1., 2.)
            other_radius = math.hypot(float(shape[0]), float(shape[1]))
            if distance(row['position'], point) < own_radius + other_radius + 2.5:
                return True
        return False

    def _choose(self, state, context, height):
        now, position = state['now'], state['position']
        self.rejected = dict((key, until) for key, until in self.rejected.items() if until > now)
        if self.pending_candidates is None:
            self.pending_candidates = parking_candidates(self.positions, self.team,
                state.get('half_length', 2.), state.get('half_width', 1.))
            self.pending_candidates.sort(key=lambda row: (row['zone'] == self.failed_zone,
                -row['priority'], distance(position, row['point']), row['id']))
        for unused in range(PARKING_CANDIDATE_BUDGET):
            if not self.pending_candidates:
                break
            row = self.pending_candidates.pop(0)
            if row['id'] in self.rejected or self._occupied(row['point'], state, context):
                continue
            supported = self._parking_height(row['point'], state, height)
            if supported is None:
                continue
            self.current = dict(row, goal=(row['point'][0], supported, row['point'][1]))
            self.chosen_at = self.progress_at = now
            self.progress_position = tuple(position)
            self.best_distance = distance(position, row['point'])
            self.settle_at = None
            self._reset_failure()
            self.pending_candidates = None
            self.receipt = dict(phase=self.mode, reason='parking_candidate',
                                parking=row['id'], goal=self.current['goal'],
                                relocation_reason=self.last_relocation_reason)
            return True
        if self.pending_candidates:
            self.receipt = dict(phase=self.mode, reason='checking_parking_geometry',
                                remaining_candidates=len(self.pending_candidates))
            return False
        self.pending_candidates = None
        self.current = None
        self.mode = 'fallback'
        self.retry_at = now + 5.
        self.receipt = dict(phase=self.mode, reason='no_supported_unoccupied_parking')
        return False

    @staticmethod
    def _parking_height(point, state, height):
        centre = height(point, state['position'][1])
        if centre is None:
            return None
        # Use the current profile's static parking limit and a full hull-turn
        # footprint, not just a supported centre on a steep edge. Movement
        # collision and actual stopped support still need fresh native proof.
        reach = math.hypot(state.get('half_length', 2.), state.get('half_width', 1.)) + 2.5
        for index in range(8):
            heading = index * math.pi / 4.
            sample = (point[0] + math.sin(heading) * reach,
                      point[1] + math.cos(heading) * reach)
            supported = height(sample, centre)
            if supported is None or abs(supported - centre) > reach * MAX_PARKING_GRADE:
                return None
        return centre

    def _reject(self, state, reason):
        now = state['now']
        if self.current is not None:
            self.rejected[self.current['id']] = now + 45.
            self.failed_zone = self.current['zone']
        self.last_relocation_reason = reason
        self.current = None
        self.pending_candidates = None
        self.mode = 'relocating'
        self.relocate_after = now + 45.
        self.settle_at = None
        self._reset_failure()
        self.receipt = dict(phase=self.mode, reason=reason)

    def _endgame(self, state, context):
        # Unknown or incomplete public classification conservatively counts as
        # a surviving combat vehicle. Never infer death from lost visibility.
        if 'allies' not in context or context.get('allies_complete') is False:
            self.endgame_since = None
            return False
        alive = [row for row in context.get('allies') or ()
                 if row.get('id') != state.get('engine_id', state.get('id')) and
                 row.get('alive', row.get('health', 1) > 0)]
        only_artillery = not any(row.get('class_tag') != 'SPG' for row in alive)
        if not only_artillery:
            self.endgame_since = None
            return False
        if self.endgame_since is None:
            self.endgame_since = state['now']
        return state['now'] - self.endgame_since >= 5.

    def update(self, state, context, height):
        now, position = state['now'], state['position']
        if self.mode == 'defending':
            return
        if (self.mode not in ('sortie_return', 'sortie') and
                not context.get('empty_ammo') and self._endgame(state, context)):
            self.mode = 'sortie_return' if self.home is not None else 'sortie'
            self.return_started = self.return_progress_at = now
            self.return_position = tuple(position)
            self.return_goal = None
            self.settle_at = None
            self._reset_failure()
            self.receipt = dict(phase=self.mode, reason='public_roster_only_artillery')
        if self.mode == 'sortie_return':
            supported = height((position[0], position[2]), position[1])
            if (distance(position, self.home['point']) <= self.home['radius'] and
                    legal_support(state, context, supported)):
                self.mode = 'sortie'
                self.receipt = dict(phase='sortie', reason='home_route_entry_reached')
            elif (self.return_position is None or
                    distance(position, self.return_position) >= 2.):
                self.return_position, self.return_progress_at = tuple(position), now
            elif (now - self.return_progress_at >= 30. or
                    now - self.return_started >= 120.):
                # A failed return cannot own the hull for the rest of the
                # match. The normal connected-entry proof may try another
                # authored attack node; it is never a position snap.
                self.mode, self.sortie_home_failed = 'sortie', True
                self.receipt = dict(phase='sortie', reason='home_return_timeout_connected_rejoin')
            return
        if self.mode == 'sortie':
            return
        if self.mode == 'fallback':
            if now < self.retry_at:
                return
            self.mode = 'deploying'
        if self.current is None and not self._choose(state, context, height):
            return
        goal = self.current['goal']
        remaining = distance(position, goal)
        occupied_height = height((position[0], position[2]), position[1])
        supported = legal_support(state, context, occupied_height)
        arrived = remaining <= self.current['radius'] and supported
        if arrived:
            if abs(state.get('speed', 0.)) <= STOP_SPEED:
                if self.settle_at is None:
                    self.settle_at = now
                if now - self.settle_at >= SETTLE_SECONDS:
                    self.mode = 'holding'
            else:
                self.settle_at = None
        else:
            self.settle_at = None
            if self.mode == 'holding':
                self.mode = 'deploying'
                self.progress_at = self.chosen_at = now
                self.progress_position = tuple(position)
                self.best_distance = remaining
                self._reset_failure()
            if self.progress_position is None or (remaining < (self.best_distance or remaining) - .5 or
                    distance(position, self.progress_position) >= 2.):
                self.progress_position, self.progress_at = tuple(position), now
                self.best_distance = remaining
            if now - self.progress_at >= 30. or now - self.chosen_at >= 120.:
                self._reject(state, 'parking_movement_timeout')
                self._choose(state, context, height)
                return
        self.receipt.update(phase=self.mode, parking=self.current['id'], goal=goal,
                            arrived=arrived, settled=self.mode == 'holding')
        if self.mode != 'holding':
            return
        sequence = context.get('fire_seq')
        if sequence != self.fire_seq:
            self.fire_seq = sequence
            self._reset_failure()
        observed = context.get('target') is not None or bool(context.get('contacts'))
        failed = bool(context.get('fire_failure') or
                      (observed and (not context.get('fire_clear') or
                                     not context.get('aligned') or sequence == self.fire_seq)))
        if (not observed or not context.get('gun_ready') or not failed or
                context.get('aim_progress') or sequence is None):
            self._reset_failure()
            return
        if self.ready_since is None:
            self.ready_since = now
        if self.failure_at is None or now - self.failure_at >= 1.:
            self.failure_at = now
            self.failure_count += 1
        elapsed = now - self.ready_since
        self.receipt.update(failure_elapsed=elapsed, failures=self.failure_count,
                            failure=context.get('fire_failure') or 'no_usable_shot')
        if elapsed >= 30. and self.failure_count >= 2 and now >= self.relocate_after:
            self._reject(state, 'persistent_firing_failure')
            self._choose(state, context, height)

    def goal(self, state, height):
        if self.mode == 'sortie_return' and self.home is not None:
            if self.return_goal is None:
                x, z = self.home['point']
                reach = self.home['radius'] * .65
                points = [(x, z)] + [(x + math.sin(i * math.pi / 4.) * reach,
                                     z + math.cos(i * math.pi / 4.) * reach) for i in range(8)]
                for point in sorted(points, key=lambda candidate: distance(state['position'], candidate)):
                    y = height(point, state['position'][1])
                    if y is not None:
                        self.return_goal = (point[0], y, point[1])
                        break
            return self.return_goal
        return self.current['goal'] if self.current is not None else None

    def holding(self, state, context, height):
        if self.current is None or self.mode not in ('deploying', 'relocating', 'holding'):
            return False
        point = state['position']
        return bool(distance(point, self.current['goal']) <= self.current['radius'] and
                    legal_support(state, context, height((point[0], point[2]), point[1])))

    def snapshot(self):
        return dict(self.receipt, phase=self.mode,
                    resume_phase=self.saved['mode'] if self.saved else None)
