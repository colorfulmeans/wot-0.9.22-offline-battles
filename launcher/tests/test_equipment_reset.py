"""Only unlocked saves receive the approved one-time clean equipment reset."""
import json
from pathlib import Path
import tempfile
import unittest
import save_slots


class EquipmentResetTests(unittest.TestCase):
    def test_old_unlocked_resets_once_and_new_account_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            full = save_slots.create_slot('full', save_slots.MODE_UNLOCKED, root=directory)
            zero = save_slots.create_slot('zero', save_slots.MODE_NEW_ACCOUNT, root=directory)
            metadata = Path(full['path']) / 'save.json'
            data = json.loads(metadata.read_text(encoding='utf-8'))
            data.pop('equipment_revision')
            metadata.write_text(json.dumps(data), encoding='utf-8')
            old = Path(full['path']) / 'garage_state.json'
            untouched = Path(zero['path']) / 'garage_state.json'
            old.write_text('{"test":1}', encoding='utf-8')
            untouched.write_text('{"test":2}', encoding='utf-8')
            zero_before = (Path(zero['path']) / 'save.json').read_bytes()
            self.assertEqual(1, save_slots.reset_unlocked_equipment_defaults(root=directory))
            self.assertFalse(old.exists())
            self.assertEqual('{"test":2}', untouched.read_text(encoding='utf-8'))
            self.assertEqual(zero_before, (Path(zero['path']) / 'save.json').read_bytes())
            old.write_text('{"new":3}', encoding='utf-8')
            self.assertEqual(0, save_slots.reset_unlocked_equipment_defaults(root=directory))
            self.assertTrue(old.exists())

    def test_new_unlocked_is_already_on_current_equipment_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            full = save_slots.create_slot('full', save_slots.MODE_UNLOCKED, root=directory)
            data = json.loads((Path(full['path']) / 'save.json').read_text(encoding='utf-8'))
            self.assertEqual(save_slots.DEFAULT_REVISION, data['equipment_revision'])
            self.assertEqual(0, save_slots.reset_unlocked_equipment_defaults(root=directory))
