from __future__ import print_function
"""Pinned language-only build. Shared client/server code must remain identical."""
import json
import os
import sys
import full_bot080_build as common
import bot_editor_build as original

BASE = 'c584fa591ccff2429c3850d92bafb1d4d6afbd1a'
ROOT = common.ROOT
PACKAGE = 'wot-0.9.22-offline-battles-0.9.4-bot-editor-i18n-20260924-Windows-x64.zip'
EXPECTED = {'docs/testing/094-editor-localization.md': 'e83babc94a079f1a1f6fc8f686a39d4a215c73410aef4a50607474e2195b3628',
 'docs/testing/bot-editor-names-0922.md': 'b88e3b630bd217600dce82ca03a7bad8262cc2aca84f000a0110ba66eddf1e67',
 'launcher/bot_tactics_labels.py': 'c7032bb5a0277fd20059a3718a31ba0241337bd4aa849373c15fa2f33d25c615',
 'launcher/bot_tactics_smoke.py': '919b4e2eb11932cc9736e97f49ac43c14f88b6b32e6718e4d7a6d78474709a45',
 'launcher/bot_tactics_store.py': 'd3dc0bdca96c61eb2a4260339ce4c9b0f112ddb4b45bc90a76cc8273bda49845',
 'launcher/bot_tactics_ui.py': 'aa0dd624b4454f487b34ba6b471a063c6258581f0cbde39034fbf8733f8b5456',
 'launcher/tests/test_bot_tactics_localization.py': 'f90e84c6d0ae31184ef83c3541922f8e05e3c6178d67c7e153b38d489bfb508c',
 'launcher/wot_launcher.py': 'd9e55b2585a31c6c0bc715a219c801bbbdafccf7f29ab2df34efd967f13ee497'}


def verify():
    base = os.environ.get('EDITOR_I18N_LOCAL_BASE', BASE)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        assert base == BASE
    changed = set(common.git('diff','--name-only',base,'--').decode().splitlines())
    allowed = set(EXPECTED) | {'tools/editor_i18n_build.py',
        '.github/workflows/build-094-editor-i18n.yml'} | set(
        'tools/editor_i18n.patch.%d.b64' % i for i in range(4))
    assert changed <= allowed, sorted(changed - allowed)
    for path, expected in EXPECTED.items():
        assert common.sha(common.read(os.path.join(ROOT,path)).replace(b'\r\n',b'\n')) == expected, path
    old = json.loads(common.git('show',base+':docs/testing/bot077-proof.json'))
    proof = dict(old)
    proof['runtime_sha256_lf'] = common.runtime_hashes()
    proof['repair_baseline'] = BASE
    proof['launcher_localization_hashes'] = EXPECTED
    proof['native_gameplay_tested'] = False
    proof['exact_historical_sha256'] = dict((p,h) for p,h in old['exact_historical_sha256'].items()
        if common.sha(common.git('show',base+':'+p).replace(b'\r\n',b'\n')) == h)
    # All runtime modules, not just selected markers, must be identical.
    for path, digest in proof['runtime_sha256_lf'].items():
        assert digest == common.sha(common.git('show',base+':'+path).replace(b'\r\n',b'\n')), path
    for folder in ('server','navgraphs','foliage','destructibles','spg_positions'):
        for path in common.git('ls-tree','-r','--name-only',base,folder).decode().splitlines():
            assert common.read(os.path.join(ROOT,path)) == common.git('show',base+':'+path), path
    common.save(os.path.join(ROOT,'build-evidence/editor-i18n-source-proof.json'),proof)
    print('PASS exact localization sources; all runtime, server and 41 map bytes unchanged.')
    return proof


def package(app_name):
    import shutil
    import zipfile
    from pathlib import Path
    verify()
    app=Path(app_name); evidence=Path(ROOT)/'build-evidence'
    ready=json.loads((evidence/'server-readiness.json').read_bytes())
    ui=json.loads((evidence/'packaged-editor-smoke.json').read_bytes())
    assert ready['ready'] and ui['ok'] and ui['locale_preserved_active_bytes']
    assert ui['localized_maps']==41 and ui['locale_roundtrip']==['en','zh','en']
    source=common.git('rev-parse','HEAD').decode().strip()
    assert source==os.environ['FULL_BOT080_SOURCE_SHA']
    receipt=json.loads((app/'FULL_BOT080_BUILD_EVIDENCE.json').read_bytes())
    assert receipt['fake_install_passed'] and receipt['source_commit']==source
    allowed={'wot-0.9.22-offline-battles.exe','_internal','README.txt','LICENSE','THIRD_PARTY_NOTICES.md','licenses'}
    for path in list(app.iterdir()):
        if path.name not in allowed:
            assert path.is_file(),str(path)
            shutil.move(str(path),str(evidence/path.name))
    assert set(p.name for p in app.iterdir())==allowed
    with zipfile.ZipFile(str(app/'_internal/client/0.9.22.zip')) as pack:
        assert pack.testzip() is None
        identity=json.loads(pack.read('mods/configs/offline_lan_0922/build_identity.json'))
        assert identity['semanticVersion']=='0.9.4'
        assert identity['buildIdentity']==os.environ['WOT_OFFLINE_BUILD_IDENTITY']
    with (app/'README.txt').open('a',encoding='utf8') as f:
        f.write('\nBot editor language follow-up: 41 maps and 96 route labels. Main language setting applies live.\nSource: '+source+'\nBuild: '+identity['buildIdentity']+'\n')
    archive=Path(ROOT)/PACKAGE
    with zipfile.ZipFile(str(archive),'w',zipfile.ZIP_DEFLATED,compresslevel=6) as pack:
        for path in sorted(app.rglob('*')):
            if path.is_file():pack.write(str(path),path.relative_to(app).as_posix())
    with zipfile.ZipFile(str(archive)) as pack:
        assert pack.testzip() is None
        assert set(p.split('/')[0] for p in pack.namelist())==allowed
    digest=common.sha(archive.read_bytes())
    (Path(ROOT)/(PACKAGE+'.sha256')).write_text(digest+'  '+PACKAGE+'\n')
    shutil.copyfile(str(Path(ROOT)/'dist/full-bot080-bytecode.json'),str(evidence/'bytecode.json'))
    common.save(str(evidence/'package-manifest.json'),dict(source=source,baseline=BASE,package=PACKAGE,
        sha256=digest,bytes=archive.stat().st_size,identity=identity,server_readiness=ready,
        packaged_editor_test=ui,fake_install_passed=True,native_gameplay_tested=False,
        runtime_changes=False,localized_maps=41,localized_routes=96))
    print('PACKAGE',PACKAGE,digest,archive.stat().st_size)


if __name__=='__main__':
    common.audit=verify
    action=sys.argv[1]
    if action=='verify':verify()
    elif action=='bytecode':common.bytecode()
    elif action=='distribution':original.distribution(sys.argv[2])
    elif action=='package':package(sys.argv[2])
    else:raise SystemExit('Unknown action')
