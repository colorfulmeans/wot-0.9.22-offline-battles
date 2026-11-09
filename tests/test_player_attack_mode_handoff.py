"""Mode rebinding preserves aim intention, never an old shot certificate.

The finite observations exercise the real AttackPolicy with new plate/lane
facts. The native case changes the real composite descriptor and GunState
through the foreground mode echo. Neither fixture is a Windows play test.
"""
import unittest

from test_player_rebuilt_attack_policy import Observations
from test_player_siege_engagement import SiegeScene
from gui.mods.offline_lan_0922 import siege_mechanics


class AttackModeIntentTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = Observations(**kwargs)
        scene.frame['weapon_identity'] = ('round', 'same_physical_gun')
        return scene

    @staticmethod
    def rebind(scene, name='siege'):
        scene.frame['identity'] = ('round', name)
        scene.frame['pose'] = ('actual_mode_pose', name)

    def select_later_point(self, scene):
        scene.passed(target=2, sample=1)
        scene.prime(index=0)
        result = scene.tick(0., background=False)
        self.assertEqual(('aim', ('bot', 2), 1), (result['action'],
            result['candidate']['target_key'], result['candidate']['sample']))
        return result['candidate']

    def test_same_weapon_mode_rebind_checks_retained_point_first_with_new_evidence(self):
        scene = self.scene()
        first = self.select_later_point(scene)
        scene.passed(target=1, sample=0)
        self.rebind(scene)
        start = len(scene.calls)
        result = scene.tick(.1, background=False)
        self.assertEqual(first['key'], result['candidate']['key'])
        self.assertEqual(('bot', 2), scene.calls[start][3])
        self.assertEqual(1, scene.calls[start][4])
        self.assertNotEqual(first['pose_stamp'], result['candidate']['pose_stamp'])
        self.assertEqual(scene.frame['identity'], result['candidate']['pose_stamp'][0])
        self.assertEqual(.1, result['candidate']['observed_at'])
        self.assertTrue(all(row is not first for row in scene.policy.rows.values()))

    def test_combat_authority_change_discards_old_proofs_but_keeps_aim_preference(self):
        scene = self.scene()
        scene.frame['combat_signature'] = ('admitted', 1)
        first = self.select_later_point(scene)
        scene.prime()
        scene.policy.background(0.)
        self.assertIsNotNone(scene.policy.next_plan)
        scene.policy.load_started(0, first)
        self.assertIsNotNone(scene.policy.loading_plan)
        scene.tick(.01, background=False)
        self.assertEqual(first['key'], scene.policy.selected)
        identity = scene.frame['identity']
        for shell in scene.frame['shells']:
            for target in (1, 2):
                for sample in (0, 1):
                    scene.value(shell['index'], target, sample,
                                armor='unknown', line='pending')
        scene.frame['combat_signature'] = ('admitted', 2)
        result = scene.tick(.1, background=False)
        self.assertEqual(identity, scene.frame['identity'])
        self.assertNotEqual('aim', result['action'])
        self.assertEqual(first['key'], scene.policy.selected)
        refreshed = scene.policy.current_row(first)
        if refreshed is not None:
            self.assertIsNot(first, refreshed)
            self.assertNotEqual(first['pose_stamp'], refreshed['pose_stamp'])
            self.assertEqual(('unknown', 'pending'),
                             (refreshed['armor'], refreshed['line']))
        self.assertIsNone(scene.policy.next_plan)
        self.assertIsNone(scene.policy.loading_plan)
        self.assertIsNone(scene.policy.trigger)
        self.assertIsNone(scene.policy.search_authority)
        self.assertIsNone(scene.policy.reload_authority)
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertTrue(scene.policy.rows)
        for row in scene.policy.rows.values():
            self.assertEqual(('admitted', 2), row['pose_stamp'][-1])
            self.assertNotEqual(first['pose_stamp'], row['pose_stamp'])

    def test_combat_domain_change_preserves_already_granted_reload_transaction(self):
        scene = self.scene(clips=6, targets=1, points=1)
        scene.frame.update(limited_traverse=True, clip=3,
                           combat_signature=('combat', True))
        scene.passed(1)
        scene.prime()
        decision = scene.tick(0.)
        self.assertEqual(('reload_clip', True),
                         (decision['action'], decision['early_reload']))
        authority = scene.policy.reload_authority
        self.assertIsNotNone(authority)
        scene.frame['combat_signature'] = ('route_movement', False)
        scene.frame['pose'] = ('moving_on_route', 1)
        scene.value(1, armor='unknown', line='pending')
        decision = scene.tick(.1, background=False)
        self.assertIs(authority, scene.policy.reload_authority)
        self.assertEqual(('reload_clip', True, authority['qualified_at']),
            (decision['action'], decision['early_reload'], decision['reload_qualified_at']))
        self.assertIsNone(scene.policy.search_authority)

    def test_failed_retained_point_prefers_another_point_of_the_same_target(self):
        scene = self.scene()
        first = self.select_later_point(scene)
        scene.value(0, target=2, sample=1, armor='failed')
        scene.passed(target=2, sample=0)
        scene.passed(target=1, sample=0)
        self.rebind(scene)
        result = scene.tick(.1, background=False)
        self.assertEqual(('aim', ('bot', 2), 0), (result['action'],
            result['candidate']['target_key'], result['candidate']['sample']))
        self.assertNotEqual(first['key'], result['candidate']['key'])

    def test_mode_change_does_not_reuse_armour_line_loading_or_next_proof(self):
        scene = self.scene()
        first = self.select_later_point(scene)
        scene.prime()
        scene.policy.background(0.)
        self.assertIsNotNone(scene.policy.next_plan)
        scene.policy.load_started(0, first)
        self.assertIsNotNone(scene.policy.loading_plan)
        scene.tick(.01, background=False)
        self.assertEqual(first['key'], scene.policy.selected)
        for shell in scene.frame['shells']:
            for target in (1, 2):
                for sample in (0, 1):
                    scene.value(shell['index'], target, sample,
                                armor='unknown', line='pending')
        self.rebind(scene)
        result = scene.tick(.1, background=False)
        self.assertNotEqual('aim', result['action'])
        self.assertEqual(first['key'], scene.policy.selected)
        self.assertIsNone(scene.policy.next_plan)
        self.assertIsNone(scene.policy.next_shell)
        self.assertIsNone(scene.policy.loading_plan)
        self.assertIsNone(scene.policy.trigger)
        self.assertFalse(scene.policy.fallback)
        self.assertIsNone(scene.policy.search_authority)
        self.assertTrue(scene.policy.rows)
        for row in scene.policy.rows.values():
            self.assertEqual(('unknown', 'pending'), (row['armor'], row['line']))
            self.assertEqual(scene.frame['identity'], row['pose_stamp'][0])
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_absent_target_cannot_keep_an_intent_across_the_mode_change(self):
        scene = self.scene()
        self.select_later_point(scene)
        scene.frame['targets'] = scene.frame['targets'][:1]
        scene.passed(target=1, sample=0)
        self.rebind(scene)
        result = scene.tick(.1, background=False)
        self.assertEqual(('bot', 1), result['candidate']['target_key'])
        self.assertTrue(all(key[1] == ('bot', 1) for key in scene.policy.rows))

    def test_different_physical_weapon_resets_intent_even_if_geometry_identity_repeats(self):
        scene = self.scene()
        self.select_later_point(scene)
        scene.passed(target=1, sample=0)
        scene.frame['weapon_identity'] = ('round', 'replacement_gun')
        result = scene.tick(.1, background=False)
        self.assertEqual(('bot', 1), result['candidate']['target_key'])
        self.assertEqual(.1, result['candidate']['observed_at'])
        self.assertIsNone(scene.policy.reload_authority)

    def test_he_fallback_point_becomes_penetration_without_losing_aim_intent(self):
        for limited in (False, True):
            with self.subTest(limited=limited):
                scene = self.scene(clips=6)
                scene.frame.update(loaded=2, clip=3, limited_traverse=limited)
                scene.he(100., target=2, sample=1)
                scene.prime()
                scene.prime('he_fallback')
                first = scene.tick(0., background=False)['candidate']
                self.assertEqual(('he_fallback', ('bot', 2), 1),
                    (first['mode'], first['target_key'], first['sample']))
                scene.passed(2, target=2, sample=1)
                scene.passed(2, target=1, sample=0)
                self.rebind(scene)
                result = scene.tick(.1, background=False)
                self.assertEqual(('aim', 'penetration', 2, ('bot', 2), 1),
                    (result['action'], result['candidate']['mode'],
                     result['candidate']['shell_index'], result['candidate']['target_key'],
                     result['candidate']['sample']))
                self.assertIsNone(scene.policy.reload_authority)
                self.assertIsNone(scene.policy.search_started)
                self.assertNotIn('shell_index', result)

    def test_unresolved_preferred_target_does_not_starve_other_targets(self):
        scene = self.scene(points=5)
        scene.passed(target=2, sample=1)
        scene.prime(index=0)
        first = scene.tick(0., background=False)['candidate']
        self.assertEqual(('bot', 2), first['target_key'])
        for target in (1, 2):
            for sample in range(5):
                scene.value(0, target, sample, armor='unknown', line='pending')
        scene.passed(0, target=1, sample=4)
        self.rebind(scene)
        scene.allow_atomic = False
        for step in range(1, 13):
            result = scene.tick(step * .1, background=False)
            if result['action'] == 'aim':
                break
        self.assertEqual(('aim', ('bot', 1), 4), (result['action'],
            result['candidate']['target_key'], result['candidate']['sample']))
        self.assertIsNone(scene.policy.search_started)

    def test_retained_target_never_overrides_next_clip_ammunition_rank(self):
        scene = self.scene(clips=6)
        self.select_later_point(scene)
        self.rebind(scene)
        scene.passed(2, target=1, sample=0)
        result = scene.tick(.1, background=False)
        self.assertEqual((0, ('bot', 2)),
            (result['candidate']['shell_index'], result['candidate']['target_key']))
        scene.prime()
        scene.policy.background(.1)
        self.assertEqual((2, ('bot', 1)),
            (scene.policy.next_shell, scene.policy.next_plan['target_key']))


class NativeModeIntentTests(unittest.TestCase):
    def test_actual_mode_descriptor_echo_preserves_target_but_expires_all_old_rows(self):
        scene = SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(enabled=True, enabled_pitch=(-.8, .8))
        other = scene.vehicle(43, (0., 0., 80.), team=2)
        scene.battle._records['bot:42']['spot_visible'] = False
        scene.observe()
        for target in scene.runtime.visible_targets():
            scene.runtime.engine._shot_clear(scene.runtime.state, target, scene.now, force=True)
        scene.runtime._strategic_due = 0.
        scene.runtime._planner_order(scene.now)
        self.assertEqual((('bot', other.id),),
                         scene.runtime.combat_stop.receipt['admitted'])
        policy = scene.runtime.attack_policy
        for unused in range(60):
            scene.step(.1)
            decision = policy.update(scene.now)
            if decision['action'] == 'aim':
                break
        self.assertEqual('aim', decision['action'], policy.status())
        first = decision['candidate']
        self.assertEqual(('bot', other.id), first['target_key'])
        original_weapon = policy.frame['weapon_identity']
        scene.battle._records['bot:42']['spot_visible'] = True
        scene.echo_mode(siege_mechanics.SWITCHING_OFF, 1)
        scene.step(.1)
        policy.update(scene.now)
        self.assertEqual(original_weapon, policy.frame['weapon_identity'])
        self.assertNotEqual(first['pose_stamp'][0], policy.frame['identity'])
        self.assertEqual(first['key'], policy.selected)
        refreshed = policy.current_row(first)
        if refreshed is not None:
            self.assertIsNot(first, refreshed)
            self.assertNotEqual(first['pose_stamp'], refreshed['pose_stamp'])
        scene.echo_mode(siege_mechanics.DISABLED, 1)
        scene.step(.1)
        policy.update(scene.now)
        self.assertEqual(first['key'], policy.selected)
        scene.echo_mode(siege_mechanics.ENABLED, 2)
        for unused in range(60):
            scene.step(.1)
            decision = policy.update(scene.now)
            if decision['action'] == 'aim':
                break
        self.assertEqual('aim', decision['action'], policy.status())
        self.assertEqual(first['key'], decision['candidate']['key'])
        self.assertIsNot(first, decision['candidate'])
        self.assertGreater(decision['candidate']['observed_at'], first['observed_at'])
        self.assertFalse(scene.launches())


class NativeHydraulicMagazineRulesTests(unittest.TestCase):
    def scene(self):
        from test_player_siege_planning import ActualHydraulicScene
        scene = ActualHydraulicScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_plan(enabled=True, enabled_pitch=(0., 0.), clip=3)
        scene.runtime.gun.clip = 2
        scene.runtime.attack_policy.atomic_time_budget = .25
        return scene

    def review_until(self, scene, predicate):
        policy = scene.runtime.attack_policy
        for unused in range(160):
            scene.observe()
            decision = policy.update(scene.now)
            policy.background(scene.now)
            self.assertIsNone(policy.search_started)
            self.assertIsNone(policy.search_authority)
            if predicate(decision):
                return decision
            scene.fixture.now += .11
        self.fail('native enabled-mode magazine review did not complete: %r' % policy.status())

    def test_actual_enabled_nonhe_partial_clip_waits_for_verified_replacement_then_reloads(self):
        scene = self.scene()
        runtime, gun = scene.runtime, scene.runtime.gun
        gun.shots[0].piercingPower = (0., 0.)
        # An incomplete alternative is not a global negative certificate or
        # permission to discard the current cassette. Once the same native
        # descriptor becomes complete and penetrable, reload it in place.
        speed = gun.shots[1].speed
        gun.shots[1].speed = None
        before = tuple(gun.ammo)
        self.review_until(scene, lambda row:
            runtime.attack_policy._failure_domain((0,))['all_failed'])
        domain = runtime.attack_policy._failure_domain((0,))
        self.assertTrue(domain['all_failed'], domain)
        self.assertGreater(domain['projected_failed'], 0)
        for unused in range(12):
            scene.fixture.now += .11
            scene.observe()
            decision = runtime.attack_policy.update(scene.now)
            runtime.attack_policy.background(scene.now)
            self.assertNotIn(decision['action'], ('reload_clip', 'switch_shell',
                                                 'search_penetration'))
            self.assertIsNone(runtime.attack_policy.reload_authority)
            self.assertIsNone(runtime.attack_policy.search_authority)
            runtime._apply_shell_intent()
            self.assertEqual((0, 2, before),
                             (gun.shot_index, gun.clip, tuple(gun.ammo)))
        gun.shots[1].speed = speed
        gun.shots[1].piercingPower = (1000., 1000.)
        decision = self.review_until(scene, lambda row:
            row['action'] == 'reload_clip' and row.get('early_reload'))
        self.assertEqual('current_shell_all_armour_failed', decision['reason'])
        self.assertIsNotNone(runtime.attack_policy.reload_authority)
        self.assertIsNotNone(decision['candidate'])
        self.assertEqual((1, 'penetration'),
            (decision['shell_index'], decision['candidate']['mode']))
        self.assertTrue(runtime.attack_policy._plannable(decision['candidate']))
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        order = dict(combat_mode='engage', target_id=scene.target.id,
            target_kind='bot', move_position=(0., 0., 0.),
            face_position=scene.target.position, fire_allowed=False)
        self.assertFalse(hasattr(runtime, '_reload_order'))
        self.assertFalse(hasattr(runtime, '_reload_retreat'))
        self.assertFalse(runtime.combat_stop.navigation_owns(order))
        self.assertTrue(runtime.siege_desired(runtime.state, order, runtime._targets[0]))
        self.assertEqual((0, 2, before), (gun.shot_index, gun.clip, tuple(gun.ammo)))
        runtime._apply_shell_intent()
        self.assertEqual((1, 0, before), (gun.shot_index, gun.clip, tuple(gun.ammo)))
        self.assertGreater(gun.reload_time, 0.)
        self.assertIsNone(runtime.attack_policy.reload_authority)
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        self.assertFalse(scene.launches())

    def test_actual_enabled_he_partial_clip_fallback_keeps_verified_ap_for_next_clip(self):
        scene = self.scene()
        runtime, gun = scene.runtime, scene.runtime.gun
        scene.set_he(piercing=0.)
        gun.shots[1].shell.kind = 'ARMOR_PIERCING'
        gun.shots[1].piercingPower = (1000., 1000.)
        before = tuple(gun.ammo)
        policy = runtime.attack_policy
        decision = self.review_until(scene, lambda row:
            (row.get('candidate') or {}).get('mode') == 'he_fallback' and
            policy.next_shell == 1)
        self.assertEqual((0, 'he_fallback'),
            (decision['candidate']['shell_index'], decision['candidate']['mode']))
        self.assertIn(decision['action'], ('aim', 'firing_position'))
        domain = policy._failure_domain((0,))
        self.assertTrue(domain['all_failed'], domain)
        self.assertGreater(domain['projected_failed'], 0)
        self.assertIsNotNone(policy._best_penetration(exclude=0, plannable=True))
        self.assertEqual('penetration', policy.next_plan['mode'])
        self.assertIsNone(policy.reload_authority)
        runtime._apply_shell_intent()
        runtime._apply_next_shell()
        self.assertEqual((0, 2, 1, before),
            (gun.shot_index, gun.clip, gun.pending_index, tuple(gun.ammo)))
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        self.assertEqual(0., scene.battle._local_siege_aim_pitch)
        self.assertFalse(scene.launches())

    def test_plain_enabled_child_keeps_real_fire_and_navigation_mode_boundaries(self):
        scene = self.scene()
        runtime, gun = scene.runtime, scene.runtime.gun
        # Native enabled children may omit the outer composite's marker.
        # This changes the observed descriptor, not the installed vehicle.
        scene.enabled_descriptor.hasSiegeMode = False
        self.assertIs(scene.enabled_descriptor, scene.entity.typeDescriptor)
        self.assertTrue(runtime.siege_capable())
        before = tuple(gun.ammo)
        for unused in range(120):
            scene.tick()
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()), dict(
            policy=runtime.attack_policy.decision.get('reason'),
            hydraulic=runtime.siege_aim.status(),
            pitch=scene.battle._local_siege_aim_pitch,
            position=runtime.combat_stop.receipt))
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        self.assertTrue(runtime.weapon.verified)
        self.assertEqual(before[0] - 1, gun.ammo[0])
        self.assertTrue(runtime.siege_navigation_owns(dict(combat_mode='base_defense')))

        runtime.set_mission('return_base', dict(timeout=180.))
        for unused in range(20):
            scene.tick(actuate=False)
            self.assertTrue(runtime.siege_navigation_owns(runtime._last_order))
            self.assertFalse(runtime._last_order['fire_allowed'])
            if runtime._siege_pending is not None:
                break
        self.assertIsNotNone(runtime._siege_pending)
        self.assertFalse(runtime._siege_pending['enabled'])
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        self.assertFalse(runtime._siege_fire_ready())
        self.assertEqual('original_combat_not_admitted', runtime.authorize_trigger(
            dict(source_pose=runtime.pose_stamp()), scene.entity, gun, None))
        self.assertEqual(1, len(scene.launches()))
        self.assertTrue(scene.battle._local_siege_drive_locked(scene.entity))
        sequence = runtime._siege_pending['sequence']
        scene.echo_mode(siege_mechanics.SWITCHING_OFF, sequence)
        # The mode echo is authoritative even when its active descriptor is
        # still the plain enabled child while the switch is in progress.
        scene.entity.typeDescriptor = scene.enabled_descriptor
        self.assertTrue(scene.battle._local_siege_drive_locked(scene.entity))
        scene.tick(actuate=False)
        self.assertIsNotNone(scene.battle._local_siege_pending)
        self.assertIsNotNone(runtime._siege_pending)
        self.assertFalse(runtime._last_order['fire_allowed'])
        scene.echo_mode(siege_mechanics.DISABLED, sequence)
        scene.tick(actuate=False)
        self.assertIsNone(scene.battle._local_siege_pending)
        self.assertIsNone(runtime._siege_pending)
        self.assertFalse(scene.battle._local_siege_drive_locked(scene.entity))
        self.assertEqual('team_return_base', runtime._last_order['combat_mode'])
        self.assertFalse(runtime.combat_stop.active)
        self.assertIsNone(runtime.attack_policy.decision.get('candidate'))
        self.assertEqual('original_combat_not_admitted', runtime.authorize_trigger(
            dict(source_pose=runtime.pose_stamp()), scene.entity, gun, None))
        self.assertEqual(1, len(scene.launches()))

    def test_remote_vehicle_cannot_borrow_installed_local_siege_capability(self):
        scene = self.scene()
        battle = scene.battle
        scene.enabled_descriptor.hasSiegeMode = False
        scene.target.typeDescriptor.hasSiegeMode = False
        self.assertTrue(battle._local_has_siege_mode(scene.entity))
        self.assertFalse(battle._local_has_siege_mode(scene.target))
        self.assertFalse(battle._local_has_siege_mode(None))
        battle._local_siege_pending = (False, 17)
        self.assertFalse(battle._local_siege_drive_locked(scene.target))
        record = battle._records['bot:%s' % scene.target.id]
        with self.assertRaisesRegex(RuntimeError, 'without Siege mode'):
            battle._apply_siege_state(record, dict(
                siege_state=siege_mechanics.ENABLED,
                siege_time_left_ms=0, input_seq=17))
        self.assertEqual((False, 17), battle._local_siege_pending)
        self.assertFalse(scene.launches())

    def test_actual_hydraulic_source_is_revoked_before_navigation_exit_debounce(self):
        scene = self.scene()
        runtime, gun = scene.runtime, scene.runtime.gun
        before = tuple(gun.ammo)
        for unused in range(40):
            scene.tick(actuate=False)
            if runtime.siege_aim_candidate() is not None:
                break
        candidate = runtime.siege_aim_candidate()
        self.assertIsNotNone(candidate, runtime.siege_aim.status())
        self.assertIsNotNone(runtime.siege_aim._lease)
        old_point = runtime.weapon.motion_point
        self.assertIsNotNone(old_point)
        self.assertIsNotNone(runtime.weapon.target)

        runtime.set_mission('return_base', dict(timeout=180.))
        scene.tick(actuate=False)
        self.assertEqual('team_return_base', runtime._last_order['combat_mode'])
        self.assertEqual((0., 0., -45.), runtime.mission_status()['destination'])
        self.assertTrue(runtime.siege_navigation_owns(runtime._last_order))
        # Navigation has already accepted this frame, but the unchanged
        # native mode debounce has not submitted an exit request yet.
        self.assertEqual(siege_mechanics.ENABLED, scene.entity.siegeState)
        self.assertIsNone(runtime._siege_pending)
        self.assertFalse(runtime.combat_stop.active)
        self.assertIsNone(runtime.attack_policy.decision.get('candidate'))
        self.assertEqual('original_combat_not_admitted', runtime.authorize_trigger(
            dict(source_pose=runtime.pose_stamp()), scene.entity, gun, None))
        self.assertNotEqual(old_point, runtime.weapon.motion_point)
        self.assertIsNone(runtime.siege_aim_candidate())
        self.assertIsNone(runtime.siege_aim._lease)
        self.assertIsNone(runtime.hydraulic_aim_point(scene.entity))
        self.assertIsNone(runtime.siege_aim.hydraulic_point(candidate, old_point))
        # The copied hull-forward resting source is allowed; the old enemy
        # hydraulic source and all its firing authority are not.
        self.assertNotEqual('player_siege_hydraulic',
            runtime.state['_diagnostic_aim_intent']['owner'])
        self.assertEqual(before, tuple(gun.ammo))
        self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
