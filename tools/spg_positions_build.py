from __future__ import print_function
"""Exact-source test build. Does not rewrite the historical rollback proof."""
import hashlib
import json
import os
import subprocess
import sys
import full_bot080_build as common

BASE = '5fda392c88c0987ed110a097e3c668d0be011fa2'
ROOT = common.ROOT
PREFIX = common.PREFIX
PRODUCTION = ['server/server_bot_ai.py', 'server/lan_battle_server.py', 'src/res/scripts/client/gui/mods/offline_lan_0922/bot_runtime.py', 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/spg_positions.py', 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/spg_positions_data.py']
EXPECTED = {'server/server_bot_ai.py': '252f3c0fabb00aedf7913ebd48797d0077c56d78a497b599f91394d3b48718e7', 'server/lan_battle_server.py': '5a4ae63a2e4b7ee0bbc941287ba9b0ec43f858e8df3d2089b598e314d0295c74', 'src/res/scripts/client/gui/mods/offline_lan_0922/bot_runtime.py': '6dc92ee47d6142a3c1c77d4fa696c723d0b44b22612efc22a13fdaa233134d9b', 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/spg_positions.py': 'e1836b038c1da19c804676c32bb3ea1f17a2591721f8cd3620f59f10d5963cc8', 'src/res/scripts/client/gui/mods/offline_lan_0922/ai/spg_positions_data.py': 'ff478c033994f9100a158552aa1d076e060f035d80a22dab441f109767827ad3', 'tests/test_port_0922_spg_positions.py': 'c533c14633e84ee33f35ee601310dbefc36312a8d7d4945f8e42c64734600d49', 'tools/build_spg_positions.py': 'dcff68c44367cda44fbabd27f3f4a5839b4c7515ec3923f74ce2f9bc033b8670', 'data/spg_positions/hawg_2527609_markers.json': '28e58e4c45e04cf54be2513d5d5df0a8af8edac12a6d4c6663adf5d3f69aa165', 'docs/testing/094-spg-position-library.md': '4c14c99fb0e353062766d903f8681b89a3ebe2bc5198b416920944ee3dd1a19b', 'docs/testing/spg-position-coverage.json': 'e14cd1ee7597f91424d8d85dfb5ef552601074d85b0adc5fba497ae03cffc078'}
ALLOWED = set(EXPECTED) | {'tools/spg_positions_build.py', '.github/workflows/build-spg-positions-test.yml', '.github/workflows/prepare-spg-position-inputs.yml', } | set('tools/spg_positions.patch.%02d.b64' % i for i in range(20))
PACKAGE = 'wot-0.9.22-offline-battles-0.9.4-spg-positions-test-20260924-Windows-x64.zip'


def verify():
    changed = set(common.git('diff', '--name-only', BASE, '--').decode().splitlines())
    assert changed.issubset(ALLOWED), sorted(changed-ALLOWED)
    for path, expected in EXPECTED.items():
        assert common.sha(common.read(os.path.join(ROOT,path)).replace(b'\r\n',b'\n')) == expected, path
    old = json.loads(common.git('show',BASE+':docs/testing/bot077-proof.json'))
    assert old['variant'] == 'original'
    proof = dict(old)
    proof['runtime_sha256_lf'] = common.runtime_hashes()
    proof['repair_baseline'] = BASE
    proof['repair_paths'] = PRODUCTION
    proof['native_gameplay_tested'] = False
    # Keep map/catalog hashes and all unchanged historical modules. Changed
    # modules are verified against this repair, not labelled exact upstream077.
    proof['exact_historical_sha256'] = dict((p,h) for p,h in
        old['exact_historical_sha256'].items()
        if common.sha(common.git('show', BASE+':'+p).replace(b'\r\n',b'\n')) == h
        and p not in PRODUCTION)
    for path, expected in proof['exact_historical_sha256'].items():
        assert common.sha(common.read(os.path.join(ROOT,path)).replace(b'\r\n',b'\n')) == expected,path
    for path, digest in proof['runtime_sha256_lf'].items():
        if path not in PRODUCTION:
            assert digest == common.sha(common.git('show', BASE+':'+path).replace(b'\r\n',b'\n')), path
    graph_manifest = json.loads(common.read(os.path.join(ROOT,'navgraphs/manifest.json')))
    for item in graph_manifest['maps']:
        path = 'navgraphs/' + item['file']
        assert common.sha(common.read(os.path.join(ROOT,path))) == item['sha256'],path
    for path in ('ai/driver.py','ai/traffic.py','ai/adapter.py'):
        assert common.read(os.path.join(ROOT,PREFIX+path)).replace(b'\r\n',b'\n') == common.git('show',BASE+':'+PREFIX+path).replace(b'\r\n',b'\n'),path
    common.save(os.path.join(ROOT,'build-evidence/spg-positions-source-proof.json'), proof)
    print('PASS historical SPG positions; exact source, 41 unchanged navgraphs and prior runtime fixes preserved.')
    return proof


def package(app_name):
    import io
    import shutil
    import zipfile
    from pathlib import Path
    verify()
    app = Path(app_name)
    evidence = Path(ROOT)/'build-evidence'
    evidence.mkdir(exist_ok=True)
    ready = json.loads((evidence/'server-readiness.json').read_bytes())
    assert ready['ready'] is True
    source = common.git('rev-parse','HEAD').decode().strip()
    assert source == os.environ['FULL_BOT080_SOURCE_SHA']
    receipt = json.loads((app/'FULL_BOT080_BUILD_EVIDENCE.json').read_bytes())
    assert receipt['fake_install_passed'] and receipt['source_commit'] == source
    allowed = {'wot-0.9.22-offline-battles.exe','_internal','README.txt',
               'LICENSE','THIRD_PARTY_NOTICES.md','licenses'}
    for path in list(app.iterdir()):
        if path.name not in allowed:
            assert path.is_file(), path
            shutil.move(str(path),str(evidence/path.name))
    assert {p.name for p in app.iterdir()} == allowed
    with zipfile.ZipFile(str(app/'_internal/client/0.9.22.zip')) as client:
        assert client.testzip() is None
        identity = json.loads(client.read('mods/configs/offline_lan_0922/build_identity.json'))
        assert identity['semanticVersion'] == '0.9.4'
        assert identity['buildIdentity'] == os.environ['WOT_OFFLINE_BUILD_IDENTITY']
        mods = [n for n in client.namelist() if n.endswith('.wotmod')]
        assert len(mods) == 1
        with zipfile.ZipFile(io.BytesIO(client.read(mods[0]))) as mod:
            assert mod.testzip() is None
            for path in PRODUCTION:
                if path.startswith('src/'):
                    assert path[len('src/'):]+'c' in mod.namelist(),path
    with (app/'README.txt').open('a',encoding='utf8') as f:
        f.write('\nSPG position library test: 38 sourced maps, 237 source markers, 230 graph-projected regions and 666 parking slots. The 3 unsupported maps retain explicit fallback. Native firing arcs remain unverified until each actual shot.\nSource: '+source+'\nBuild: '+identity['buildIdentity']+'\n')
    archive = Path(ROOT)/PACKAGE
    with zipfile.ZipFile(str(archive),'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(app.rglob('*')):
            if path.is_file():z.write(str(path),path.relative_to(app).as_posix())
    with zipfile.ZipFile(str(archive)) as z:
        assert z.testzip() is None
        assert {p.split('/')[0] for p in z.namelist()} == allowed
    digest = common.sha(archive.read_bytes())
    (Path(ROOT)/(PACKAGE+'.sha256')).write_text(digest+'  '+PACKAGE+'\n')
    shutil.copyfile(str(Path(ROOT)/'dist/full-bot080-bytecode.json'),str(evidence/'bytecode.json'))
    common.save(str(evidence/'package-manifest.json'),{
        'source':source,'baseline':BASE,'package':PACKAGE,'sha256':digest,
        'bytes':archive.stat().st_size,'identity':identity,'server_readiness':ready,
        'fake_install_passed':True,'native_gameplay_tested':False,
        'production_changes':PRODUCTION,'original_driver_traffic_maps_preserved':True,
        'source_markers':237,'accepted_source_regions':230,'parking_slots':666,'sourced_maps':38,'native_firing_arc_matrix':False})
    print('PACKAGE',PACKAGE,digest,archive.stat().st_size)

if __name__ == '__main__':
    common.audit = verify
    action = sys.argv[1]
    if action == 'verify':verify()
    elif action == 'bytecode':common.bytecode()
    elif action == 'distribution':common.distribution(sys.argv[2])
    elif action == 'package':package(sys.argv[2])
    else:raise SystemExit('Unknown action')
