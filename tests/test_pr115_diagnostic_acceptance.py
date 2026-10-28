"""Exercise diagnostic producers and native-window lifetime, not log strings."""
import types
import unittest
from unittest import mock
import test_port_0922_garage as fixture


class DiagnosticAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.d = fixture._load_port_module('native_input_diagnostics')

    def test_matrix_providers_are_materialized_and_missing_wreck_muzzle_is_local(self):
        provider = object()
        angles = types.SimpleNamespace(yaw=1.2, pitch=0.3, roll=0.1)
        materialize = mock.Mock(return_value=angles)
        def node(name):
            if name == 'HP_gunFire':
                raise TypeError('not in wreck compound')
            return provider
        appearance = types.SimpleNamespace(turretMatrix=provider, gunMatrix=provider)
        entity = types.SimpleNamespace(id=7, health=0, isCrewActive=False,
            appearance=appearance, model=types.SimpleNamespace(node=node), matrix=provider)
        with mock.patch.dict('sys.modules', {'Math': types.SimpleNamespace(Matrix=materialize)}), \
                mock.patch.object(self.d, 'detailed_enabled', return_value=True), \
                mock.patch.object(self.d, 'write_json_record') as write:
            self.d.turret_pose('after_model_refresh', entity)
        label, row = write.call_args.args
        self.assertEqual('TURRET DEATH POSE', label)
        self.assertEqual(1.2, row['model_matrices']['turretMatrix']['yaw'])
        self.assertTrue(row['world_nodes']['HP_turretJoint']['available'])
        self.assertFalse(row['world_nodes']['HP_gunFire']['available'])
        self.assertIn('not in wreck compound', row['world_nodes']['HP_gunFire']['message'])
        self.assertEqual(5, materialize.call_count)

    def test_followup_frames_reject_old_round_entity_and_model(self):
        for boundary in ('none', 'round', 'entity', 'model', 'appearance'):
            with self.subTest(boundary=boundary):
                queue = []
                appearance, model = object(), object()
                entity = types.SimpleNamespace(id=7, appearance=appearance, model=model)
                world = types.SimpleNamespace(callback=lambda delay, fn: queue.append(fn),
                    entity=lambda unused: entity)
                with mock.patch.object(self.d, 'detailed_enabled', return_value=True), \
                     mock.patch.object(self.d, 'turret_pose') as pose, \
                     mock.patch.object(self.d, 'validation_event') as event:
                    self.d.observe_refresh_frames(world, entity, appearance)
                    if boundary == 'round': self.d._detail_round = 44
                    if boundary == 'entity': world.entity = lambda unused: object()
                    if boundary == 'model': entity.model = object()
                    if boundary == 'appearance': entity.appearance = object()
                    while queue: queue.pop(0)()
                    self.assertEqual(3 if boundary == 'none' else 0, pose.call_count)
                    self.assertEqual(0 if boundary == 'none' else 1, event.call_count)
                self.d._detail_round = None

    def test_diagnostic_failure_is_reported_without_breaking_health_callback(self):
        class Broken(object):
            @property
            def id(self): raise ValueError('unreadable native entity')
        with mock.patch.object(self.d, 'detailed_enabled', return_value=True), \
             mock.patch.object(self.d, 'write_json_record') as write:
            self.d.turret_pose('before_death', Broken())
        self.assertEqual('turret_probe_failed', write.call_args.args[1]['stage'])

    def test_daily_refresh_cancels_timer_and_rejects_stale_open(self):
        daily = fixture._load_port_module('daily_window')
        queue, cancelled = [], []
        world = types.SimpleNamespace(callback=lambda delay, fn: queue.append(fn) or len(queue),
            cancelCallback=cancelled.append)
        room = types.SimpleNamespace(_open=True)
        panel = daily.DailyWindow(room)
        panel.token = 7
        panel.view = types.SimpleNamespace(_isDAAPIInited=lambda: True,
            flashObject=types.SimpleNamespace(as_update=mock.Mock()), destroy=mock.Mock())
        with mock.patch.dict('sys.modules', {'BigWorld': world}), \
             mock.patch.dict(daily._rooms, {7: panel}, clear=True), \
             mock.patch.object(panel, 'model', return_value={'daily': True}):
            panel.refresh(); panel.refresh()
            self.assertEqual(1, len(queue))
            panel.close(); panel.close()
            self.assertEqual([1], cancelled)
            queue[0]()
            self.assertIsNone(panel.view)
            self.assertEqual(1, len(queue))


if __name__ == '__main__': unittest.main()
