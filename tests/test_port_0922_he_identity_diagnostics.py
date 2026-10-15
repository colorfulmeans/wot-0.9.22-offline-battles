"""Unresolved actual surfaces must retain the reason and exact slot evidence."""
import types
import unittest
from unittest import mock
import test_port_0922_destructibles as h

sensor, V = h.destructibles_sensor, h._Vector


class HEIdentityDiagnosticsTests(unittest.TestCase):
    def recover(self, isolated, status):
        point = V(0., 0., 5.)
        key = (111, 0, 5, 32383)
        original = h._mat_info_1513(True, point, V(), 111, '', 5, 32383)
        bw = types.SimpleNamespace(wg_collideSegment=lambda space, start, end, flags, keep:
            (point, V()) if keep(*key) else None)
        rows = []
        with mock.patch.object(sensor, '_destructible_isolated_1513', return_value=isolated), \
                mock.patch.object(sensor, '_destructible_catalog', None), \
                mock.patch.dict(sensor.__dict__, {'g_offh_destr_instances': {}}), \
                mock.patch.object(sensor, 'resolve_native_item_name_1513', return_value=status) as resolve, \
                mock.patch.object(sensor, '_native_contact_slot_evidence_1513', return_value={'quarantined': isolated}) as slot:
            result = sensor._recover_shot_material_1513(lambda label, function, *args: function(*args),
                bw, 1, V(), V(0., 0., 10.), (point, V()), original, lambda *unused: True, rows)
        return result, original, rows, resolve, slot

    def test_isolated_actual_stone_surface_reports_skip_without_requery(self):
        result, original, rows, resolve, slot = self.recover(True, ('exact', 'fake'))
        self.assertIs(original, result)
        resolve.assert_not_called()
        slot.assert_called_once_with(1, (111, 0, 5, 32383))
        self.assertEqual('isolated', rows[0]['status'])
        self.assertTrue(rows[0]['slot']['quarantined'])

    def test_exact_unnamed_slot_does_not_admit_an_empty_descriptor(self):
        result, original, rows, unused, slot = self.recover(False, ('exact', None))
        self.assertIs(original, result)
        self.assertEqual('exact', rows[0]['status'])
        self.assertEqual('', rows[0]['filename'])
        slot.assert_called_once()

    def test_pending_resource_retains_its_actual_reason(self):
        result, original, rows, unused, slot = self.recover(False, ('pending', None))
        self.assertIs(original, result)
        self.assertEqual('pending', rows[0]['status'])
        slot.assert_called_once()
