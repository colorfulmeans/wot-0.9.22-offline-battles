# -*- coding: utf-8 -*-
"""Shared SPG acquisition from proved arcs and real HE contact estimates.

Ranking is advisory target intent, not a launch receipt. The existing bounded
arc queue and native first-trigger/exact-launch checks retain their ownership.
Only the actually loaded HE slot participates; this policy never changes ammo.
"""
from __future__ import division

import math

from .. import combat_rules
from .actor_observation import observation
from .attack_policy import native_target_pose
from .target_selection import artillery_damage_key, live_contact, ordinary_initial_key


REVIEWS_PER_STEP = 2
REVIEW_SECONDS = .25


def _point(raw):
    result = tuple(float(raw[index]) for index in range(3))
    if any(math.isnan(value) or math.isinf(value) for value in result):
        raise ValueError('non-finite artillery observation')
    return result


def _key(target):
    return (str(target.get('kind') or ''),
            int(target.get('network_id', target.get('id', 0))))


def _velocity(target):
    value = target.get('velocity')
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return _point(value)
    yaw, speed = float(target.get('yaw', 0.)), float(target.get('speed', 0.))
    return _point((math.sin(yaw) * speed, 0., math.cos(yaw) * speed))


class ArtillerySelection(object):
    """One acquisition frontier per controlled actor, independent of rating."""

    def __init__(self, reviews_per_step=REVIEWS_PER_STEP):
        self.reviews_per_step = max(1, int(reviews_per_step))
        self.reset()

    def reset(self):
        self.identity = None
        self.current = None
        self.fire_seq = None
        self.rows = {}
        self.cursor = 0
        self.review_at = 0.
        self.retry_at = 0.
        self.receipt = dict(status='idle', reason='no_acquisition')

    @staticmethod
    def _frame(runtime):
        physical = observation(runtime)
        entity = physical.source_entity()
        descriptor = entity.typeDescriptor
        gun = runtime.gun
        shell_index = int(gun.shot_index)
        shot = gun.shots[shell_index]
        source = runtime.current_source()
        shell = dict(index=shell_index, shot=shot, is_he=combat_rules.is_he(shot))
        identity = (tuple(physical.weapon_identity()), id(entity), id(descriptor),
                    id(shot), shell_index)
        return dict(source=source, descriptor=descriptor, shell=shell,
                    identity=identity, fire_seq=int(source.get('fire_seq', 0)),
                    trigger_active=bool(physical.trigger_active()),
                    intent_active=bool(physical.fire_intent_active()),
                    ammo=int(gun.ammo[shell_index]), clip=int(gun.clip),
                    reloading=float(gun.reload_time) > 0.)

    @staticmethod
    def _review(runtime, frame, raw, now):
        """Complete one real arc and reuse the common armour/blast evaluator."""
        geometry = runtime.geometry
        controller = getattr(geometry, '_artillery', None)
        if controller is None:
            return dict(status='unknown', reason='artillery_owner_unavailable')
        try:
            entity = runtime.target_entity(raw)
            if entity is None or not entity.isAlive():
                return dict(status='invalid', reason='target_dead')
            pose, matrix, chassis = native_target_pose(runtime.owner, entity)
            velocity = _velocity(raw)
            position = _point(matrix.translation)
            target = dict(raw, position=position, x=position[0], y=position[1],
                z=position[2], yaw=float(matrix.yaw), pitch=float(matrix.pitch),
                roll=float(matrix.roll), velocity=velocity)
            source, descriptor, shell = frame['source'], frame['descriptor'], frame['shell']
            ready, proved = controller.request(source, target, descriptor, shell['index'], now)
            if not ready:
                return dict(status='pending', reason='arc_pending')
            if not isinstance(proved, dict):
                return dict(status='blocked', reason='arc_unreachable')
            solution = controller.solution(source, target, descriptor, shell['index'], now)
            if not isinstance(solution, dict):
                return dict(status='blocked', reason='current_intercept_unreachable')
            # This is the same full-path friendly/wreck check used by physical
            # SPG launches. A direct line of sight is not an artillery proof.
            lane = geometry._bot_artillery_friendly_lane(
                source, target, descriptor, shell['index'], solution)
            if not isinstance(lane, dict) or lane.get('clear') is not True:
                return dict(status='blocked', reason='friendly_or_wreck_blocked', lane=lane)
            flight = float(solution['flight_time'])
            yaw, pitch = float(solution['yaw']), float(solution['pitch'])
            direction = (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                         math.cos(yaw) * math.cos(pitch))
            # The native collider is at its observed pose. Remove the solved
            # lead from the aim point; _armour_geometry applies gravity and
            # relative target velocity to the terminal incidence direction.
            sample_point = tuple(float(solution['aim_position'][index]) -
                                 velocity[index] * flight for index in range(3))
            target_row = dict(key=_key(raw), entity=entity, pose=pose,
                matrix=matrix, chassis=chassis, velocity=velocity, value=raw)
            evaluator = runtime.attack_policy.evaluator
            native_frame = dict(origin=_point(solution['path'][0]),
                                identity=frame['identity'])
            contact = evaluator._armour_geometry(
                native_frame, shell, target_row, sample_point, direction, flight)
            if contact is None:
                return dict(status='unknown', reason='he_contact_unproved')
            estimate = evaluator._he_damage(shell, target_row, contact)
            damage = estimate.get('expected_damage')
            if estimate.get('contact') is not True or damage is None:
                return dict(status='unknown', reason='he_damage_unproved')
            damage = float(damage)
            if math.isnan(damage) or math.isinf(damage) or damage < 0.:
                return dict(status='unknown', reason='he_damage_invalid')
            return dict(status='ready', reason='reachable_he_contact',
                damage=damage, arc=solution.get('arc'), target_pose=pose,
                solution=solution, he_contact=estimate.get('he_contact'))
        except (AttributeError, TypeError, ValueError, KeyError, IndexError,
                RuntimeError, OverflowError, ZeroDivisionError) as error:
            return dict(status='unknown', reason='native_observation_unavailable',
                        exception=type(error).__name__)

    def _apply(self, order, target, frame, permit):
        result = dict(order)
        if target is None:
            result.update(target_kind=None, target_id=None, aim_position=None,
                          fire_allowed=False)
        else:
            result.update(target_kind=target.get('kind'), target_id=_key(target)[1],
                          aim_position=target.get('position'))
            if order.get('fire_allowed'):
                result['face_position'] = target.get('position')
            result['fire_allowed'] = bool(permit and order.get('fire_allowed') and
                frame['ammo'] > 0 and
                frame['clip'] > 0 and not frame['reloading'] and
                not frame['trigger_active'] and not frame['intent_active'])
        evidence = dict(result.get('tactical_evidence') or {})
        evidence['artillery_selection'] = dict(self.receipt)
        result['tactical_evidence'] = evidence
        return result

    def select(self, runtime, order, now):
        """Return shared target intent without advancing queues or firing."""
        now = float(now)
        try:
            frame = self._frame(runtime)
        except (AttributeError, TypeError, ValueError, IndexError, KeyError,
                RuntimeError, OverflowError) as error:
            self.receipt = dict(status='unknown', reason='source_observation_unavailable',
                                exception=type(error).__name__)
            return dict(order, fire_allowed=False)
        if not frame['shell']['is_he']:
            self.reset()
            self.receipt = dict(status='not_applicable', reason='loaded_shell_is_not_he')
            return order
        if frame['identity'] != self.identity:
            self.reset()
            self.identity = frame['identity']
        visible = {}
        for raw in runtime.visible_targets():
            if (live_contact(raw) and raw.get('visible') is not False and
                    raw.get('team') != frame['source'].get('team')):
                visible[_key(raw)] = raw
        if self.current not in visible:
            self.current = None
        active = frame['trigger_active'] or frame['intent_active']
        if active and self.current is None:
            # Adopting control mid-trigger cannot replace its frozen target.
            retained = (str(order.get('target_kind') or ''),
                        int(order.get('target_id') or 0))
            if retained in visible:
                self.current = retained
        completed = (self.fire_seq is not None and self.fire_seq != frame['fire_seq'] and
                     not active)
        if completed:
            self.current, self.rows, self.cursor = None, {}, 0
        if not active:
            self.fire_seq = frame['fire_seq']
        if self.current is not None:
            target = visible[self.current]
            if active:
                self.receipt = dict(status='held', reason='native_trigger_owns_target',
                                    target=self.current)
                return self._apply(order, target, frame, False)
            if now >= self.review_at:
                row = self._review(runtime, frame, target, now)
                self.rows[self.current] = row
                self.review_at = now + REVIEW_SECONDS
            else:
                row = self.rows.get(self.current) or dict(status='pending')
            if row['status'] in ('ready', 'pending'):
                self.receipt = dict(status='held', reason=row.get('reason'),
                    target=self.current, expected_he_damage=row.get('damage'))
                return self._apply(order, target, frame, row['status'] == 'ready')
            self.current, self.rows, self.cursor = None, {}, 0
        for key in list(self.rows):
            if key not in visible:
                self.rows.pop(key, None)
        for key in visible:
            if key not in self.rows:
                self.rows[key] = dict(status='pending', reason='not_reviewed')
        keys = sorted(visible, key=lambda key: ordinary_initial_key(frame['source'], visible[key]))
        if not keys:
            self.receipt = dict(status='idle', reason='no_live_visible_target')
            return self._apply(order, None, frame, False)
        if now < self.retry_at:
            return self._apply(order, None, frame, False)
        # Queue work is already native-ray-budgeted. Bound native material
        # and blast observations independently; never synchronously drain it.
        reviewed, visited = 0, 0
        while reviewed < self.reviews_per_step and visited < len(keys):
            key = keys[self.cursor % len(keys)]
            self.cursor += 1
            visited += 1
            if self.rows[key]['status'] != 'pending':
                continue
            self.rows[key] = self._review(runtime, frame, visible[key], now)
            reviewed += 1
        pending = sum(row['status'] == 'pending' for row in self.rows.values())
        self.receipt = dict(status='reviewing', reason='all_target_arc_review',
            candidates=len(keys), pending=pending, reviewed=reviewed,
            unknown=sum(row['status'] == 'unknown' for row in self.rows.values()))
        if pending:
            return self._apply(order, None, frame, False)
        candidates = [(artillery_damage_key(frame['source'], visible[key], row['damage']), key)
                      for key, row in self.rows.items() if row['status'] == 'ready']
        while candidates:
            if reviewed >= self.reviews_per_step:
                self.receipt.update(reason='selected_contact_recheck_pending')
                return self._apply(order, None, frame, False)
            unused_rank, selected = min(candidates)
            # The frontier can span native frames. The chosen identity needs
            # a current contact before it acquires the stable engagement lock.
            current = self._review(runtime, frame, visible[selected], now)
            reviewed += 1
            self.rows[selected] = current
            self.receipt.update(reviewed=reviewed,
                pending=sum(row['status'] == 'pending' for row in self.rows.values()),
                unknown=sum(row['status'] == 'unknown' for row in self.rows.values()))
            if current['status'] == 'pending':
                self.receipt.update(reason='selected_contact_recheck_pending')
                return self._apply(order, None, frame, False)
            candidates = [(artillery_damage_key(frame['source'], visible[key], row['damage']), key)
                          for key, row in self.rows.items() if row['status'] == 'ready']
            if current['status'] != 'ready' or not candidates:
                continue
            if min(candidates)[1] != selected:
                # A changed contact can reduce the former winner's damage.
                # Re-rank and prove its successor within this same budget;
                # an old maximum is not authority to acquire the new lock.
                continue
            self.current = selected
            self.review_at = now + REVIEW_SECONDS
            self.receipt.update(status='selected', reason='highest_reachable_he_damage',
                target=selected, expected_he_damage=current['damage'],
                shell_index=frame['shell']['index'])
            return self._apply(order, visible[selected], frame, True)
        self.receipt.update(status='blocked', reason='no_proved_reachable_he_contact')
        self.rows = {}
        self.retry_at = now + REVIEW_SECONDS
        return self._apply(order, None, frame, False)
