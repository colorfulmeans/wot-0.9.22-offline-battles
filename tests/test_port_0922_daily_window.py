"""Daily-window model publication and delayed callback ownership."""
import sys
import types
import unittest
from unittest import mock
import test_port_0922_garage as fixture


class DailyWindowTests(unittest.TestCase):
    def setUp(self):
        self.daily = fixture._load_port_module('daily_window')
        self.queue, self.cancelled = [], []
        def callback(delay, function):
            self.queue.append(function)
            return len(self.queue)
        self.world = types.SimpleNamespace(callback=callback, cancelCallback=self.cancelled.append)
        self.panel = self.daily.DailyWindow(types.SimpleNamespace(_open=True))
        self.panel.token = 1
        self.panel.view = self.view()
        self.patches = [mock.patch.dict(sys.modules, {'BigWorld': self.world}),
            mock.patch.dict(self.daily._rooms, {1: self.panel}, clear=True),
            mock.patch.object(self.panel, 'model', return_value={'daily': True})]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def view(self):
        return types.SimpleNamespace(_isDAAPIInited=lambda: True,
            flashObject=types.SimpleNamespace(as_update=mock.Mock()), destroy=mock.Mock())

    def test_publish_one_timer_and_cancel_on_close(self):
        view = self.panel.view
        self.panel.refresh(); self.panel.refresh()
        view.flashObject.as_update.assert_called_with({'daily': True})
        self.assertEqual(1, len(self.queue))
        self.panel.close(); self.panel.close()
        self.assertEqual([1], self.cancelled)
        self.queue[0]()
        self.assertEqual(1, len(self.queue))
        self.assertIsNone(self.panel.view)
        view.destroy.assert_called_once_with()

    def test_cancelled_callback_cannot_clear_or_duplicate_reopened_timer(self):
        self.panel.refresh()
        self.panel.close()
        self.panel.token = 2
        self.daily._rooms[2] = self.panel
        self.panel.view = self.view()
        self.panel.refresh()
        self.assertEqual(2, self.panel._tick)
        self.queue[0]()
        self.panel.refresh()
        self.assertEqual(2, self.panel._tick)
        self.assertEqual(2, len(self.queue))
        self.panel.close()
        self.assertEqual([1, 2], self.cancelled)

    def test_waits_for_initialized_view_and_stops_on_external_disposal(self):
        self.panel.view._isDAAPIInited = lambda: False
        self.panel.refresh()
        self.assertFalse(self.queue)
        self.panel.view = self.view()
        self.panel.refresh()
        self.panel.view = None
        self.panel.view_disposed()
        self.queue[0]()
        self.assertEqual([1], self.cancelled)
        self.assertEqual(1, len(self.queue))

    def test_native_cancel_failure_still_destroys_view_and_fences_callback(self):
        view = self.panel.view
        self.panel.refresh()
        self.world.cancelCallback = mock.Mock(side_effect=ValueError('retired timer'))
        self.panel.close()
        self.queue[0]()
        view.destroy.assert_called_once_with()
        self.assertIsNone(self.panel.view)
        self.assertEqual(1, len(self.queue))

    def test_latest_daily_progress_is_built_for_each_model(self):
        self.patches[-1].stop()
        ui = fixture._load_port_module('offline_services_ui')
        daily = dict(missions=['win', 'kill', 'damage'], claimed=[])
        # Use actual policy mission IDs and counters, rather than a fixed label snapshot.
        with mock.patch.object(ui, 'snapshot', return_value={}), \
             mock.patch.object(ui.policy, 'daily_state') as state:
            ids = list(ui.policy.MISSION_BY_ID)[:3]
            daily = dict(missions=ids, claimed=[], **dict((key, 0) for key in ids))
            state.return_value = daily
            first = self.panel.model()
            daily[ids[0]] = 1
            second = self.panel.model()
        self.assertTrue(first['daily'])
        self.assertNotEqual(first['labels']['row0'], second['labels']['row0'])
        self.assertEqual({'reserves', 'close'}, set(first['controls']))


if __name__ == '__main__':
    unittest.main()
