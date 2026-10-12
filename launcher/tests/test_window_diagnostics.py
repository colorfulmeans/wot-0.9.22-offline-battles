import threading
import unittest
from unittest import mock
import window_diagnostics


class FocusEvidenceTests(unittest.TestCase):
    def test_changes_record_dialog_and_focus_without_controlling_windows(self):
        stop = threading.Event()
        before = {'foreground': {'pid': 1}, 'game_windows': [{'minimized': False}], 'dialogs': []}
        after = {'foreground': {'pid': 2, 'image': 'error.exe'},
                 'game_windows': [{'minimized': True}],
                 'dialogs': [{'title': 'Error', 'text': ['diagnostic text']}]}
        rows = iter((before, before, after))
        def read():
            value = next(rows)
            if value is after:
                stop.set()
            return value
        write = mock.Mock()
        window_diagnostics.monitor_focus(stop, 'game.exe', write, reader=read, interval=0.)
        self.assertEqual(2, write.call_count)
        self.assertIn('diagnostic text', write.call_args.args[0])

    def test_reader_failure_is_logged_and_cannot_terminate_game(self):
        write = mock.Mock()
        window_diagnostics.monitor_focus(threading.Event(), 'game.exe', write,
            reader=mock.Mock(side_effect=OSError('access denied')))
        self.assertIn('unavailable: OSError', write.call_args.args[0])

    def test_change_budget_bounds_automatic_capture(self):
        write = mock.Mock()
        window_diagnostics.monitor_focus(threading.Event(), 'game.exe', write,
            reader=mock.Mock(side_effect=({'pid': 1}, {'pid': 2})), interval=0., limit=2)
        self.assertEqual(3, write.call_count)
        self.assertIn('limit reached', write.call_args.args[0])
