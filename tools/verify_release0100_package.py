"""Inspect and execute the final frozen launcher and embedded replay runtime."""
from pathlib import Path
import importlib.util
import io
import json
import marshal
import subprocess
import sys
import tempfile
import types
import zipfile
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
from verify_native_payload import verify_bytes
app = Path(sys.argv[1]).resolve()
archive = CArchiveReader(str(app / 'wot-0.9.22-offline-battles.exe'))
pyz = archive.open_embedded_archive('PYZ.pyz')


def normalize(code):
    return code.replace(co_filename='<source>', co_consts=tuple(
        normalize(item) if isinstance(item, types.CodeType) else item
        for item in code.co_consts))


verified = []
for source in sorted((ROOT / 'launcher').glob('*.py')):
    if source.stem == 'wot_launcher':
        actual = marshal.loads(archive.extract(source.stem))
    elif source.stem in pyz.toc:
        actual = pyz.extract(source.stem)
    else:
        continue
    assert normalize(actual) == normalize(compile(source.read_bytes(), '<source>', 'exec')), source
    verified.append(source.name)
assert 'replay_launch.py' in verified
assert 'wot_launcher.py' in verified
assert 'core.py' in verified
assert 'bot_tactics_ui.py' in verified
assert 'bot_tactics_connections.py' in verified
assert 'bot_tactics_artillery.py' in verified
assert 'bot_tactics_inventory.py' in verified
assert 'bot_tactics_check_ui.py' in verified
assert 'bot_tactics_preview.py' in verified
assert 'bot_tactics_labels.py' in verified
assert 'crew_ui.py' in verified
assert 'crew_store.py' in verified
assert not (app / 'route-review-draft-20261025.json').exists()

sys.path.insert(0, str(ROOT / 'launcher'))
import stage_payload
server_sources = []
for relative in stage_payload.PAYLOAD_FILES['0.9.22']:
    server_sources.append(relative)
for directory in stage_payload.PAYLOAD_TREES['0.9.22']:
    server_sources.extend(path.relative_to(ROOT).as_posix()
                          for path in (ROOT / directory).rglob('*.py'))
assert 'server/server_route_recovery.py' in server_sources
assert 'server/server_route_tasks.py' in server_sources
for relative in server_sources:
    bundled = app / '_internal/servers/0.9.22' / relative
    assert bundled.read_bytes().replace(b'\r\n', b'\n') == (ROOT / relative).read_bytes().replace(b'\r\n', b'\n'), relative

with zipfile.ZipFile(app / '_internal/client/0.9.22.zip') as client:
    verify_bytes(str(ROOT), client.read('mods/0.9.22.0.1/offline_math_batch_native.pyd'))
    assert client.read('offline_worker_starter.exe') == (ROOT / 'native/offline_worker_starter.exe').read_bytes()
    mod_name = next(n for n in client.namelist() if n.endswith('.wotmod'))
    assert mod_name.endswith('_0.10.2.wotmod')
    with tempfile.TemporaryDirectory(prefix='release0100-') as temp:
        path = Path(temp) / mod_name
        path.parent.mkdir(parents=True)
        path.write_bytes(client.read(mod_name))
        source = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922/replay_process.py'
        spec = importlib.util.spec_from_file_location('replay_process_check', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        command = module.prepare_runtime(temp)
        # Execute the official runtime that the installed 0.10.2 mod supplied.
        result = subprocess.check_output(command[:3] + ['-c', 'import sys;print(sys.version_info[:3])'], creationflags=0x08000000)
        assert b'(3, 11, 9)' in result, result
        with zipfile.ZipFile(path) as mod:
            assert all(i.compress_type == zipfile.ZIP_STORED for i in mod.infolist())
            assert mod.read('res/offline_replay/replay_reader_process.py') == (ROOT / 'tools/replay/replay_reader_process.py').read_bytes()
# Source equality alone cannot reveal windowed stdio/lifecycle failures.
# Exercise the downloaded executable's real editor in its own temporary store.
with tempfile.TemporaryDirectory(prefix='release-editor-') as temp:
    receipt = Path(temp) / 'editor.json'
    process = subprocess.run(
        [str(app / 'wot-0.9.22-offline-battles.exe'),
         '--verify-bot-editor', str(receipt)],
        cwd=str(app), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=120, creationflags=0x08000000)
    editor = json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
    assert process.returncode == 0 and editor.get('ok'), editor or process.stderr
    assert editor.get('default_readonly') and editor.get('independent_presets_and_empty_ammo'), editor
    assert editor.get('isolated_profile') and editor.get('map_count') == 41, editor
    assert editor.get('crew_controls_and_outfit_override'), editor
    assert editor.get('seat_aware_recruits'), editor
    assert editor.get('nation_order_and_barracks_capacity'), editor
    assert 'nation_choices.py' in verified
    assert editor.get('vehicle_editor_language_preserved'), editor
    assert editor.get('scoped_effective_preview') and editor.get('save_initialization_and_backup') and editor.get('save_actions_two_by_four'), editor
    assert editor.get('authored_connections_and_route_tiers'),editor
    assert editor.get('separate_artillery_editor'),editor
    assert editor.get('automatic_parking_navigation'),editor
    assert editor.get('shared_defense_transactions'),editor
    assert editor.get('common_route_reset'),editor
    assert editor.get('map_endpoint_policy_and_team_connections'),editor
    assert editor.get('total_view_route_tier_controls'),editor
    assert editor.get('route_tree_class_colors'),editor
    assert editor.get('route_toolbar_and_restore_menu'),editor
    assert editor.get('native_gameplay_tested') is False, editor

print(json.dumps({'frozen_source_modules_verified': len(verified),
                  'bundled_server_sources_verified': len(server_sources),
                  'native_math_matches_current_sources': True,
                  'replay_entry_bundled': True, 'recorder_runtime_executed': True, 'packaged_editor_smoke': True,
                  'native_starter_matches_source_tree': True}))
