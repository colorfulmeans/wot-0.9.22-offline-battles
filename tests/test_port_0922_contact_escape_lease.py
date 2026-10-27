"""Longitudinal escape owns one bounded physical exit across control updates."""
import json
import math
from pathlib import Path
import unittest
from unittest import mock
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class ContactEscapeLeaseTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('100_thepit', 1)
        self.peer = dict(id=25, team=2, alive=False, position=(3., 0., 0.), yaw=0.,
                         shape=(1.5, 3.5, -.8, 2.), half_width=1.5, half_length=3.5)
        self.state = dict(id=23, slot=7, team=2, position=(0., 0., 0.), yaw=0.,
            speed=2., dt=.1, half_width=1.5, half_length=3.5,
            collision_shape=(1.5, 3.5, -.8, 2.), neighbours=[self.peer])
        self.contact = dict(peer_id=25, peer_alive=False, peer_team=2,
                            peer_position=self.peer['position'], normal=(0., -1.))
        self.guard = mock.patch.object(self.adapter.driver, '_reverse_blocked_by_vehicle', return_value=None)
        self.blocker = self.guard.start()
        self.addCleanup(self.guard.stop)

    def plan(self, contact=None, clear=lambda *unused: True):
        return self.adapter._contact_escape_plan(self.state, self.state['position'], clear,
            self.contact if contact is None else contact)

    def test_normal_changes_do_not_reverse_the_admitted_exit(self):
        target, command = self.plan()
        self.assertEqual(-1., command['throttle'])
        for frame in range(25):
            contact = dict(self.contact, normal=(0., 1. if frame % 2 else -1.))
            self.state['position'] = (0., 0., .08 if frame % 2 else -.08)
            next_target, command = self.plan(contact)
            self.assertEqual(target, next_target)
            self.assertEqual(-1., command['throttle'])
        self.assertLess(self.adapter._contact_escapes[23]['best_progress'], .25)

    def test_contact_gap_and_tactical_changes_keep_the_original_target(self):
        target, unused = self.plan()
        order = dict(combat_mode='base_defense', move_position=(20., 0., 0.),
                     aim_position=(20., 0., 0.), face_position=(20., 0., 0.),
                     target_id=1, fire_allowed=True)
        with mock.patch.object(self.adapter, '_hull_contact', return_value=None), \
                mock.patch.object(self.adapter, '_wreck_push_plan', side_effect=AssertionError('escape interrupted')), \
                mock.patch.object(self.adapter.driver, 'drive', side_effect=AssertionError('driver interrupted')):
            for frame in range(20):
                self.state['position'] = (0., 0., -.01*frame)
                order['combat_mode'] = 'route' if frame % 2 else 'engage'
                order['move_position'] = (20.+frame, 0., 0.)
                command = self.adapter._drive_order_controls(23, self.state, self.state['position'], order, lambda *unused: True)
                self.assertEqual(target, command['move_position'])
                self.assertEqual(-1., command['throttle'])
                self.assertEqual('contact_escape', command['recovery_mode'])
                self.assertIn(command['contact_escape']['phase'], ('active', 'started'))

    def test_tiny_oscillation_exhausts_each_direction_without_restarting(self):
        signs = []
        for frame in range(110):
            self.state['position'] = (0., 0., .08 if frame % 2 else -.08)
            result = self.plan()
            if result is not None:
                signs.append(result[1]['throttle'])
        changes = sum(a != b for a, b in zip(signs, signs[1:]))
        self.assertEqual(1, changes)
        self.assertEqual({-1., 1.}, self.adapter._contact_attempts[23]['failed'])
        self.assertNotIn(23, self.adapter._contact_escapes)
        self.assertIsNone(self.plan())
        # A mere gap cannot erase the failed-direction receipt.
        with mock.patch.object(self.adapter, '_contact_peers', {}):
            self.adapter._hull_contact(23, dict(self.state, neighbours=[]), self.state['position'])
        self.assertEqual({-1., 1.}, self.adapter._contact_attempts[23]['failed'])

    def test_fresh_terrain_or_vehicle_refusal_releases_the_escape(self):
        for reason in ('terrain', 'vehicle'):
            self.adapter._contact_escapes.clear()
            self.adapter._contact_attempts.clear()
            self.blocker.return_value = None
            self.plan()
            if reason == 'vehicle': self.blocker.return_value = 99
            result = self.plan(clear=lambda *unused: reason != 'terrain')
            self.assertIsNone(result)
            self.assertNotIn(23, self.adapter._contact_escapes)
            self.assertEqual({'terrain': 'terrain_withdrawn', 'vehicle': 'vehicle_withdrawn'}[reason],
                             self.state['_contact_escape_evidence']['phase'])
            self.assertEqual({-1.}, self.adapter._contact_attempts[23]['failed'])

    def test_signed_net_progress_completes_the_fixed_exit(self):
        target, unused = self.plan()
        self.state['position'] = target
        self.assertIsNone(self.adapter._retained_contact_escape(self.state, target, lambda *unused: True))
        self.assertNotIn(23, self.adapter._contact_escapes)
        self.assertEqual('completed', self.state['_contact_escape_evidence']['phase'])
        self.assertEqual(set(), self.adapter._contact_attempts[23]['failed'])

    def test_peer_retirement_and_parking_release_ownership(self):
        self.plan()
        self.state['neighbours'] = []
        self.assertIsNone(self.adapter._retained_contact_escape(self.state, self.state['position'], lambda *unused: True))
        self.assertEqual('peer_changed', self.state['_contact_escape_evidence']['phase'])
        self.state['neighbours'] = [self.peer]
        self.plan()
        order = dict(combat_mode='hold', parking_phase='waiting',
                     move_position=self.state['position'], throttle_override=0.)
        command = self.adapter._drive_order_controls(23, self.state, self.state['position'], order, lambda *unused: True)
        self.assertEqual(0., command['throttle'])
        self.assertNotIn(23, self.adapter._contact_escapes)
        self.assertEqual('parking_cancelled', command['contact_escape']['phase'])
        self.adapter.forget(23)
        self.assertNotIn(23, self.adapter._contact_attempts)
        self.assertNotIn(23, self.adapter._contact_escapes)

    def test_reported_wz_geometry_keeps_backing_until_real_exit(self):
        from gui.mods.offline_lan_0922 import vehicle_physics
        row = json.loads((Path(__file__).parent/'fixtures/wz120_133359_escape.json').read_text())
        self.state.update(position=tuple(row['position']), yaw=row['yaw'], speed=row['speed'],
            collision_shape=tuple(row['shape']), half_width=row['shape'][0], half_length=row['shape'][1],
            neighbours=row['neighbours'])
        self.blocker.return_value = None
        contact = self.adapter._hull_contact(23, self.state, self.state['position'])
        self.assertEqual(25, contact['peer_id'])
        # Reproduce the admitted reverse boundary, not an invented scene ray.
        # The actual Windows callback still decides which corridor is usable.
        clear = lambda bearing, *unused: math.cos(bearing-row['yaw']) < 0.
        target, command = self.adapter._contact_escape_plan(self.state, self.state['position'], clear, contact)
        self.assertEqual(row['recorded_throttle'], command['throttle'])
        for actual, expected in zip(target, row['recorded_exit']):
            self.assertAlmostEqual(expected, actual)
        self.assertGreater(self.state['speed'], 0.)
        for frame in range(200):
            result = self.adapter._retained_contact_escape(self.state, self.state['position'], clear)
            if result is None:
                self.assertEqual('completed', self.state['_contact_escape_evidence']['phase'])
                break
            self.assertEqual(target, result[0])
            self.assertEqual(-1., result[1]['throttle'])
            self.state['speed'] = vehicle_physics.longitudinal_step(vehicle_physics._DEFAULTS,
                self.state['speed'], -1., False, 0., self.state['dt'])
            x, y, z = self.state['position']
            self.state['position'] = (x+math.sin(row['yaw'])*self.state['speed']*self.state['dt'],
                                      y, z+math.cos(row['yaw'])*self.state['speed']*self.state['dt'])
        else:
            self.fail('the recorded reverse escape never completed')
        self.assertLess(self.state['speed'], 0.)
        self.assertGreater(self.state['_contact_escape_evidence']['progress'], 7.)

    def test_current_hull_orientation_owns_the_repeated_safety_query(self):
        self.plan()
        self.state['yaw'] = .2
        queries = []
        def clear(bearing, distance):
            queries.append((bearing, distance))
            return True
        self.assertIsNotNone(self.adapter._retained_contact_escape(self.state, self.state['position'], clear))
        self.assertAlmostEqual(.2+math.pi, queries[-1][0])
        self.assertAlmostEqual(.2+2.*math.pi, self.blocker.call_args.args[1])

    def test_pivot_and_return_cannot_clear_failed_world_direction(self):
        self.plan()
        self.plan(clear=lambda *unused: False)
        self.state['yaw'] = 1.
        self.adapter._contact_escape_memory(23, self.state['position'], self.contact, 3.5, 1.)
        self.state['yaw'] = 0.
        unused, command = self.plan()
        self.assertEqual(1., command['throttle'])
        self.assertIn(-1., self.adapter._contact_attempts[23]['failed'])
