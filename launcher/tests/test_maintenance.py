"""Exercise destructive maintenance exclusively in isolated temporary roots."""
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

import core
import save_slots
import vehicle_overlays


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / 'game'
        self.game.mkdir()
        (self.game / core.GAME_EXECUTABLE).write_bytes(b'fake')
        (self.game / 'version.xml').write_text('<version>v.0.9.22.0.1 #1513</version>')
        self.environment = mock.patch.dict(os.environ, {
            'APPDATA': str(self.root / 'roaming'),
            'LOCALAPPDATA': str(self.root / 'local'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.game = str(self.game)
        self.state = Path(self.game) / 'mods/configs/offline_lan_0922'
        self.external = Path(save_slots.saves_root(self.game)).parent
        self.app = Path(core.settings_path()).parent

    def put(self, path, value='old'):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_clear_saves_removes_all_slots_legacy_inboxes_and_backups_only(self):
        deleted = [self.put(root / name) for root in (self.state, self.external)
                   for name in ('saves/default/save.json', 'saves/custom/garage_state.json',
                                'saves/custom/pre-initialize-123/save-backup.zip',
                                'garage_state.backup1.json', 'account_state.json',
                                'postbattle_state.json', 'launcher_inbox.json',
                                'launcher_crew_inbox.json.tmp')]
        kept = [self.put(self.state / 'config.json', '{"save_slot":"custom","name":"Tester"}'),
                self.put(self.external / 'vehicle_profiles.json'),
                self.put(self.app / 'bot_tactics/custom.json'),
                self.put(self.app / 'client_profiles/0.9.22/preferences.xml')]
        core.clear_offline_saves(self.game, is_running=lambda: False)
        for path in deleted:
            if path.name != 'save.json':
                self.assertFalse(path.exists(), str(path))
        self.assertTrue(all(path.exists() for path in kept))
        self.assertEqual({'save_slot': 'default', 'name': 'Tester'}, core._read_json(str(kept[0])))
        record = save_slots.read_slot('default', self.game)
        self.assertEqual('default', record['name'])
        self.assertEqual('unlocked', record['mode'])
        self.assertFalse(record['has_state'])
        metadata = core._read_json(str(Path(record['path']) / 'save.json'))
        self.assertTrue(metadata['skip_legacy_import'])
        self.assertFalse(list(self.root.rglob('.wot-maintenance-*')))

    def test_clear_saves_without_appdata_uses_game_fallback(self):
        with mock.patch.dict(os.environ, {'APPDATA': ''}):
            self.put(Path(save_slots.saves_root(self.game)) / 'custom/save.json')
            core.clear_offline_saves(self.game, is_running=lambda: False)
            self.assertEqual(['default'], [r['id'] for r in save_slots.list_slots(self.game)])

    def test_preferences_reset_keeps_saves_and_normal_client_preferences(self):
        prefs = self.put(core._isolated_0_9_22_preferences_path(), '<preferences>all accounts</preferences>')
        kept = [self.put(self.external / 'saves/custom/save.json'),
                self.put(core._normal_client_preferences_path())]
        core.reset_offline_preferences(self.game, is_running=lambda: False)
        self.assertFalse(prefs.exists())
        self.assertTrue(all(p.exists() for p in kept))

    def test_running_game_blocks_every_destructive_operation(self):
        path = self.put(self.external / 'saves/custom/save.json')
        for action in (core.clear_offline_saves, core.reset_offline_preferences, core.factory_reset_offline):
            with self.assertRaisesRegex(core.LauncherError, 'Close World of Tanks'):
                action(self.game, is_running=lambda: True)
        self.assertEqual('old', path.read_text())

    def test_old_launcher_and_external_server_cannot_resurrect_shared_settings(self):
        launcher = 'wot-0.9.22-offline-battles.exe'
        with mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, 'executable', 'C:/package/' + launcher):
            self.assertFalse(core.other_launcher_is_running(lambda: [launcher]))
            self.assertTrue(core.other_launcher_is_running(lambda: [launcher, launcher]))
            self.assertTrue(core.other_launcher_is_running(lambda: [launcher, 'WoT-0.9.22-LAN-Server.exe']))
            with self.assertRaisesRegex(core.LauncherError, 'Could not check'):
                core.other_launcher_is_running(mock.Mock(side_effect=OSError('denied')))

    def test_failed_save_rebuild_restores_all_old_data(self):
        old = self.put(self.external / 'saves/custom/save.json')
        config = self.put(self.state / 'config.json', '{"save_slot":"custom"}')
        with mock.patch.object(core, '_fresh_default_save', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(core.LauncherError, 'disk full'):
                core.clear_offline_saves(self.game, is_running=lambda: False)
        self.assertEqual('old', old.read_text())
        self.assertEqual({'save_slot': 'custom'}, core._read_json(str(config)))

    def test_factory_removes_shared_data_replays_reports_and_rebuilds_defaults(self):
        deleted = [self.put(p) for p in (
            self.state / 'config.json', self.external / 'vehicle_profiles.json',
            self.external / 'saves/custom/save.json', self.app / 'launcher.json',
            self.app / 'reports/report.zip', self.app / 'bot_tactics/custom.json',
            self.app / 'client_profiles/0.9.22/preferences.xml',
            Path(self.game) / 'replays/offline/last.wotlanreplay',
            Path(self.game) / 'offline-worker-python.log',
            Path(self.game) / '.wot-offline-reset-interrupted/save-backup.zip')]
        kept = [self.put(Path(self.game) / 'res/packages/scripts.pkg'),
                self.put(Path(self.game) / 'mods/0.9.22.0.1/other.wotmod'),
                self.put(self.root / 'desktop/report.zip'),
                self.put(core._normal_client_preferences_path())]
        def install(*args, **kwargs):
            self.put(self.state / 'config.json', '{"enabled":true}')
            return ['installed']
        import bot_tactics_store
        with mock.patch.object(core, 'server_log_path', return_value=str(self.root / 'server.log')), \
                mock.patch.object(vehicle_overlays, 'default_restore_targets', return_value=[]) as restore, \
                mock.patch.object(core, 'install_client_mod', side_effect=install) as installed, \
                mock.patch.object(core, 'ensure_0_9_22_preferences_isolation', return_value='isolated'), \
                mock.patch.object(bot_tactics_store.Store, 'ensure_active', return_value='default') as tactics:
            core.factory_reset_offline(self.game, base_dir='payload', is_running=lambda: False)
        installed.assert_called_once_with(self.game, core.PORT_0_9_22, 'payload', force=True)
        restore.assert_called_once()
        tactics.assert_called_once()
        self.assertEqual({'enabled': True}, core._read_json(str(self.state / 'config.json')))
        for p in deleted[1:]:
            self.assertFalse(p.exists(), str(p))
        self.assertTrue(all(p.exists() for p in kept))
        self.assertEqual(['default'], [r['id'] for r in save_slots.list_slots(self.game)])
        self.assertFalse(list(self.root.rglob('.wot-maintenance-*')))

    def test_failed_factory_reinstall_restores_old_profiles_and_saves(self):
        old = [self.put(self.app / 'launcher.json'), self.put(self.external / 'saves/custom/save.json')]
        overlay = self.put(Path(self.game) / 'res_mods/0.9.22.0.1/scripts/item_defs/vehicles/test.xml')
        with mock.patch.object(core, 'server_log_path', return_value=str(self.root / 'server.log')), \
                mock.patch.object(vehicle_overlays, 'default_restore_targets', return_value=[(str(overlay), 'test.xml')]), \
                mock.patch.object(core, 'ensure_0_9_22_preferences_isolation', return_value='isolated'), \
                mock.patch.object(core, 'install_client_mod', side_effect=core.LauncherError('bad payload')):
            with self.assertRaisesRegex(core.LauncherError, 'bad payload'):
                core.factory_reset_offline(self.game, is_running=lambda: False)
        self.assertTrue(all(p.read_text() == 'old' for p in old))
        self.assertEqual('old', overlay.read_text())

    def test_cleanup_failure_is_not_reported_as_success(self):
        old = self.put(self.app / 'client_profiles/0.9.22/preferences.xml')
        with mock.patch('shutil.rmtree', side_effect=PermissionError('locked')):
            with self.assertRaisesRegex(core.LauncherError, 'cleanup failed'):
                core.reset_offline_preferences(self.game, is_running=lambda: False)
        self.assertFalse(old.exists())
        self.assertTrue(list(self.root.rglob('.wot-maintenance-*')))

    def test_foreign_engine_overlay_blocks_factory_before_deleting_user_data(self):
        old = self.put(self.app / 'launcher.json')
        with mock.patch.object(core, 'server_log_path', return_value=str(self.root / 'server.log')), \
                mock.patch.object(core, 'ensure_0_9_22_preferences_isolation', side_effect=core.LauncherError('another tool overlay')), \
                mock.patch.object(vehicle_overlays, 'default_restore_targets') as restore:
            with self.assertRaisesRegex(core.LauncherError, 'another tool overlay'):
                core.factory_reset_offline(self.game, is_running=lambda: False)
        self.assertEqual('old', old.read_text())
        restore.assert_not_called()

    def test_redirected_target_is_rejected_before_touching_data(self):
        with mock.patch.object(os, 'lstat', wraps=os.lstat) as stat:
            real = os.lstat(self.game)
            class Redirect:
                st_mode = real.st_mode
                st_file_attributes = 0x400
            stat.side_effect = lambda p: Redirect() if os.path.abspath(p) == os.path.abspath(self.game) else real
            with self.assertRaisesRegex(core.LauncherError, 'redirected path'):
                core.clear_offline_saves(self.game, is_running=lambda: False)


if __name__ == '__main__':
    unittest.main()
