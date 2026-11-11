"""Native stationary plans cross the complete player combat consumers.

The scene supplies flat native support, empty catalog/world observations and
physical body/barrel feedback. Planning, bounded arc work, armour evaluation,
the engagement owner, copied turn input and the first-trigger gate are real.
These are deterministic consumer tests, not Windows frame-time certification.
"""
import copy
import math
import types
import unittest
from unittest import mock

from test_player_stationary_plan import NativePlanScene, install_plan_observations
from test_player_siege_engagement import SiegeScene
from gui.mods.offline_lan_0922 import shot_geometry, siege_mechanics
from gui.mods.offline_lan_0922.vehicle_control import stationary_plan
from gui.mods.offline_lan_0922.vehicle_control.geometry import SharedBattleGeometry


class NativeStationaryCombatTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = NativePlanScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        bearing = kwargs.pop('bearing', .7)
        # Establish a normal combat stop through an actually executable
        # head-on point, before the observed enemy changes its bearing. An
        # unadmitted pending review may not park the route; an already
        # admitted native pivot must not be silently frozen by this suite.
        scene.configure_plan(bearing=0., **kwargs)
        self.assertTrue(scene.runtime.combat_stop.combat_owned)
        self.assertIsNone(scene.runtime.combat_stop.pivot)
        scene.bearing = bearing
        scene.pose(scene.target, (math.sin(bearing) * 40., 0., math.cos(bearing) * 40.))
        scene.plan_receipts = []
        scene.runtime.attack_policy.reset()
        scene.runtime.attack_policy.atomic_time_budget = .25
        self.restore_native_sweep(scene)
        physical = scene.actuate

        def actuate(seconds):
            physical(seconds)
            rotator = scene.battle._avatar.gunRotator
            scene.origin = shot_geometry.shot_origin_and_direction(
                scene.entity.typeDescriptor, tuple(scene.body.translation),
                scene.body.yaw, scene.body.pitch, scene.body.roll,
                rotator.turretYaw, rotator.gunPitch)[0]

        scene.actuate = actuate
        return scene

    @staticmethod
    def restore_native_sweep(scene):
        # The older base fixture advertises an unavailable optional preview.
        # This richer fixture has the complete catalog/support/world inputs,
        # so reconnect the actual original preview to both real consumers.
        geometry = scene.runtime.geometry
        geometry._probe_bot_local_motion = types.MethodType(
            SharedBattleGeometry._probe_bot_local_motion, geometry)
        scene.runtime.engine.local_sweep_probe = geometry._probe_bot_local_motion

    @staticmethod
    def piercing(scene, index, value):
        scene.battle._gun_state.shots[index].piercingPower = (value, value)
        scene.battle.client.effective_params['gun']['shots'][index][
            'source_shot']['piercingPower'] = (value, value)

    @staticmethod
    def admit_contacts(scene):
        # Advance only the original observation/planner schedule after adding
        # another real entity. The evaluator may not silently include every
        # red dot before the original BOT has admitted its lane.
        scene.observe()
        for target in scene.runtime.visible_targets():
            scene.runtime.engine._shot_clear(scene.runtime.state, target, scene.now, force=True)
        scene.runtime._strategic_due = 0.
        scene.runtime._planner_order(scene.now)
        scene.runtime.attack_policy.reset()

    def test_multi_yaw_negative_domain_finishes_before_original_turn_can_erase_it(self):
        scene = self.scene(limits=(-.1, .1), clip=6, burst=1, bearing=.65, rate=.8)
        scene.vehicle(43, (math.sin(-.85) * 40., 0., math.cos(-.85) * 40.), team=2)
        self.admit_contacts(scene)
        self.piercing(scene, 0, 1.)
        self.piercing(scene, 1, 1000.)
        scene.battle._gun_state.clip = 3
        policy = scene.runtime.attack_policy
        receipts = []
        for unused in range(80):
            scene.tick()
            receipts.append(dict(now=scene.now, yaw=scene.body.yaw,
                decision=copy.deepcopy(policy.decision),
                sender=(scene.battle._sender.forward, scene.battle._sender.turn),
                arcs=len(scene.planner._arcs)))
            self.assertIsNone(scene.control.last_control_failure)
            if policy.decision['reason'] == 'ordered_penetration_exhausted':
                break
        final = receipts[-1]
        self.assertEqual('ordered_penetration_exhausted', final['decision']['reason'],
                         [(r['decision']['reason'], r['yaw'], r['arcs']) for r in receipts])
        self.assertGreater(len(receipts), 1)
        self.assertTrue(any(r['decision']['reason'] == 'stationary_domain_review_pending'
                            for r in receipts[:-1]))
        self.assertTrue(all(abs(r['yaw']) < 1.e-8 for r in receipts), receipts)
        self.assertEqual(2, len(policy.frame['targets']))
        self.assertEqual(1, final['decision']['shell_index'])
        jobs = policy._jobs(shell_index=0)
        rows = [policy._current(job, require_line=True) for job in jobs]
        self.assertTrue(all(policy._reviewed(row, 'penetration') for row in rows))
        self.assertFalse(any(policy._plannable(row) for row in rows))
        self.assertTrue(any((policy._planned_evidence(row) or {}).get('armor') == 'failed'
                            for row in rows))
        self.assertFalse(hasattr(policy, 'search_started'))
        self.assertFalse(scene.launches())

    def test_proved_future_penetration_turns_then_requires_actual_muzzle_before_fire(self):
        scene = self.scene(limits=(-.1, .1), clip=6, burst=1, bearing=.7, rate=.8)
        self.piercing(scene, 0, 1000.)
        scene.rotator_enabled = True
        policy, planned = scene.runtime.attack_policy, []
        for unused in range(160):
            scene.tick()
            decision = policy.decision
            candidate = decision.get('candidate')
            if decision['reason'] == 'current_penetration_after_stationary_turn':
                planned.append(candidate)
                self.assertTrue(policy._plannable(candidate))
                self.assertFalse(policy._executable(candidate))
                self.assertFalse(scene.launches())
            self.assertIsNone(scene.control.last_control_failure)
            if scene.launches():
                self.assertEqual('aim', decision['action'])
                self.assertTrue(policy._executable(candidate))
                break
        self.assertTrue(planned, scene.trace[-4:])
        self.assertEqual(1, len(scene.launches()), scene.trace[-4:])
        self.assertGreater(abs(scene.body.yaw), .2)
        self.assertEqual([19, 10], scene.battle._gun_state.ammo)
        self.assertFalse(hasattr(policy, 'search_started'))

    def test_budget_wait_stays_physically_stopped_until_real_native_work_can_resume(self):
        scene = self.scene(limits=(-.1, .1), clip=6, burst=1, bearing=.7, rate=.8)
        policy = scene.runtime.attack_policy
        observed = []
        # Real native pending from a saturated shared budget, not a supplied
        # row or a fabricated failure/projection receipt.
        with mock.patch.object(stationary_plan, 'SLICES_PER_TICK', 0):
            for unused in range(35):
                scene.tick()
                observed.append((scene.now, policy.decision['action'],
                    policy.decision['reason'], scene.battle._sender.forward,
                    scene.battle._sender.turn, policy._evidence_wait_since))
        waits = [r for r in observed if r[1:3] == ('wait', 'stationary_domain_review_pending')]
        self.assertTrue(waits, observed)
        self.assertTrue(all(r[3:5] == (0, 0) for r in waits), waits)
        self.assertEqual(1, len(set(r[5] for r in waits)))
        self.assertGreater(waits[-1][0] - waits[0][0], 3.)
        self.assertFalse(any(r[1] == 'firing_position' for r in observed), observed)
        self.assertFalse(hasattr(policy, 'search_started'))
        self.assertFalse(scene.launches())
        # Releasing the same real native budget, not waiting out a timer,
        # permits the stationary plan to complete and the original turn.
        for unused in range(80):
            scene.tick()
            if policy.decision['action'] == 'firing_position':
                break
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertTrue(policy._plannable(policy.decision['candidate']))
        self.assertFalse(scene.launches())

    def test_whitelisted_hesh_fallback_does_not_start_another_targets_yaw_domain(self):
        scene = self.scene(limits=(-.1, .1), clip=6, burst=1, bearing=0., rate=.8)
        other = scene.vehicle(43, (math.sin(.8) * 40., 0., math.cos(.8) * 40.), team=2)
        self.admit_contacts(scene)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            for material in getattr(other.typeDescriptor, name).materials.values():
                material.armor = 10000.
        scene.set_he(1.)
        # The held target owns both the full HESH penetration review and
        # the blast ranking. The other target's yaw domain cannot delay it.
        descriptor = scene.entity.typeDescriptor
        descriptor.name = descriptor.type.name = 'uk:GB83_FV4005'
        descriptor.gun.name = '_183mm_AT_Gun'
        scene.battle._gun_state.shots[0].shell.name = '_183mm_HESH'
        self.piercing(scene, 1, 1000.)
        scene.rotator_enabled = True
        policy, qualified = scene.runtime.attack_policy, None
        started = scene.now
        for unused in range(120):
            scene.tick()
            candidate = policy.decision.get('candidate')
            if (policy.decision['action'] == 'aim' and candidate is not None and
                    candidate.get('mode') == 'he_fallback'):
                self.assertEqual(('bot', 42), candidate['target_key'])
                key = candidate['key'][:3] + ('penetration',)
                proof = policy.rows[key]
                self.assertEqual(('clear', 'reachable', 'failed'),
                                 (proof['line'], proof['mechanical'], proof['armor']))
                self.assertEqual({('bot', 42)}, {row['target_key'] for row in policy.rows.values()})
                self.assertEqual(set(policy.frame['targets'][0]['samples']),
                    {row['sample'] for row in policy.rows.values()
                     if row['mode'] == 'penetration' and row['armor'] == 'failed'})
                fallback = [row for row in policy.rows.values() if row['mode'] == 'he_fallback']
                self.assertEqual(set(policy.frame['targets'][0]['samples']),
                                 {row['sample'] for row in fallback})
                self.assertEqual(max(row['expected_damage'] for row in fallback),
                                 candidate['expected_damage'])
                qualified = copy.deepcopy(proof)
            self.assertFalse(hasattr(policy, 'search_started'))
            self.assertEqual(0, scene.battle._gun_state.shot_index)
            self.assertIsNone(policy.reload_authority)
            if scene.launches():
                break
        self.assertIsNotNone(qualified)
        self.assertEqual(1, len(scene.launches()), scene.trace[-3:])
        self.assertLess(scene.now - started, 8.)
        self.assertEqual('he_fallback', policy.decision['candidate']['mode'])
        self.assertEqual((0, 5), (scene.battle._gun_state.shot_index,
                                scene.battle._gun_state.clip))
        self.assertTrue(policy._executable(policy.decision['candidate'], 'he_fallback'))

    def test_repeated_atomic_evaluation_never_promotes_cached_future_ray_to_actual(self):
        scene = self.scene(limits=(-.1, .1), bearing=.7)
        self.piercing(scene, 0, 1000.)
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'])
        policy, evaluator = scene.runtime.attack_policy, scene.runtime.attack_policy.evaluator
        policy.frame = frame
        job = policy._jobs(shell_index=0)[0]
        evaluator.atomic_deadline = evaluator.atomic_clock() + .25
        self.assertTrue(evaluator.begin_atomic(frame, (job,), scene.now))
        for unused in range(2):
            row = policy._evaluate(job, scene.now, 'atomic')
            self.assertEqual(('hull_laying', 'unknown'), (row['mechanical'], row['armor']))
            self.assertTrue(policy._plannable(row))
            self.assertFalse(policy._executable(row))
            self.assertEqual('hull_laying', evaluator._atomic_predictions[job[0]]['reach']['status'])
        self.assertFalse(scene.launches())

    def test_native_review_cannot_override_original_implicit_capture_owner(self):
        scene = self.scene(limits=(-.1, .1), clip=6, burst=1, bearing=.7, rate=.8)
        scene.battle._last_snapshot = dict(capture_bases={
            '1': [dict(id='1:0', x=0., y=0., z=-45., radius=6.)],
            '2': [dict(id='2:0', x=45., y=0., z=0., radius=6.)]},
            capture_contributors={})
        runtime = scene.runtime
        # The original implicit route-to-cap handoff creates its own mission;
        # no explicit user command or capture-start state is manufactured.
        runtime._mission_order(dict(combat_mode='base_capture'), scene.now)
        self.assertFalse(runtime._mission['explicit'])
        self.assertFalse(runtime._mission.get('capture_started'))
        with mock.patch.object(stationary_plan, 'SLICES_PER_TICK', 0):
            for unused in range(8):
                scene.tick()
                self.assertFalse(runtime.combat_stop.active)
                self.assertFalse(runtime.attack_policy.stationary_review_wait())
                self.assertEqual('original_navigation', runtime.attack_policy.decision['reason'])
                self.assertEqual('base_capture', runtime.combat_stop.task_order['combat_mode'])
                self.assertEqual((45., 0., 0.),
                    runtime._last_order['control_trace']['strategic_move_position'])
                self.assertFalse(hasattr(runtime.attack_policy, 'search_started'))
                self.assertFalse(runtime._mission.get('capture_started'))
                self.assertFalse(scene.launches())

    def test_active_hydraulic_input_cannot_reacquire_motion_during_native_review_wait(self):
        scene = SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(enabled=True, clip=6, enabled_pitch=(0., 0.))
        scene.position = (0., 0., 0.)
        scene.pose(scene.target, (math.sin(.7) * 40., 6., math.cos(.7) * 40.))
        install_plan_observations(scene)
        self.restore_native_sweep(scene)
        scene.entity.siegeState = siege_mechanics.ENABLED
        scene.observe()
        runtime, policy = scene.runtime, scene.runtime.attack_policy
        policy.frame = policy.evaluator.snapshot(scene.now)
        row = policy._evaluate(policy._jobs(shell_index=0)[0], scene.now, 'foreground')
        policy._choose('firing_position', 'unverified_points_obstructed', row)
        runtime._refresh_siege_aim(scene.now)
        self.assertIsNotNone(runtime.siege_aim_candidate(), runtime.siege_aim.status())
        old_motion_point = runtime.siege_aim_candidate()['solution']['source_point']
        with mock.patch.object(stationary_plan, 'SLICES_PER_TICK', 0):
            scene.tick(actuate=False)
            self.assertTrue(policy.stationary_review_wait(), policy.status())
            self.assertIsNone(runtime.siege_aim_candidate())
            self.assertIsNone(runtime._siege_aim_candidate)
            self.assertIsNone(runtime._siege_pending)
            self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
            self.assertEqual((0, 0), (scene.battle._sender.forward, scene.battle._sender.turn))
            # A native hull-forward gun-rest source is permitted; it is not
            # reacquisition of the cached enemy/hydraulic preaim target.
            self.assertIsNone(runtime.weapon.target)
            self.assertIsNone(runtime.weapon.solution)
            self.assertNotEqual(old_motion_point, runtime.weapon.motion_point)
            self.assertFalse(runtime.state.get('gun_aligned'))
            self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
