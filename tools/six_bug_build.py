"""Verify the rebuilt client, server and localized Windows launcher together."""
from __future__ import print_function

import glob
import hashlib
import io
import json
import marshal
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'a5401f87359ac916f6fcedc31aa09d25bf226dd8'
PACKAGE = 'wot-0.9.22-offline-battles-0.9.4-physics-r5-20260925-Windows-x64.zip'


def read(path):
    with open(path, 'rb') as stream:
        return stream.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git'] + list(args), cwd=ROOT)


def record(name, value):
    folder = os.path.join(ROOT, 'build-evidence')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(os.path.join(folder, name), 'wb') as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf8'))


def source():
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=ROOT)
    assert not git('diff', 'HEAD', '--'), 'Tracked source changed during build'
    commit = git('rev-parse', 'HEAD').decode().strip()
    expected = os.environ.get('GITHUB_SHA', commit)
    assert commit == expected, (commit, expected)
    record('source.json', {'source_commit': commit, 'baseline': BASE,
                          'native_gameplay_tested': False})
    return commit


def normalized(value):
    if isinstance(value, types.CodeType):
        fields = ('co_argcount', 'co_nlocals', 'co_stacksize', 'co_flags',
                  'co_code', 'co_names', 'co_varnames', 'co_freevars',
                  'co_cellvars', 'co_filename', 'co_firstlineno', 'co_lnotab')
        return (tuple(getattr(value, field) for field in fields) +
                (tuple(normalized(item) for item in value.co_consts),))
    if isinstance(value, tuple):
        return tuple(normalized(item) for item in value)
    return value


def bytecode():
    assert sys.version_info[:2] == (2, 7), sys.version
    commit = source()
    packages = glob.glob(os.path.join(ROOT, 'dist', '*.wotmod'))
    assert len(packages) == 1, packages
    modules = {}
    with zipfile.ZipFile(packages[0]) as archive:
        assert archive.testzip() is None
        assert not any(name.endswith('.py') for name in archive.namelist())
        for folder, unused_dirs, files in os.walk(os.path.join(ROOT, 'src')):
            for filename in sorted(files):
                if not filename.endswith('.py'):
                    continue
                path = os.path.join(folder, filename)
                member = os.path.relpath(path, os.path.join(ROOT, 'src')).replace(os.sep, '/') + 'c'
                pyc = archive.read(member)
                assert pyc[:4] == b'\x03\xf3\r\n', member
                actual = marshal.loads(pyc[8:])
                expected = compile(read(path), actual.co_filename, 'exec', 0, True)
                assert normalized(actual) == normalized(expected), member
                modules[member] = sha(pyc)
        actual_members = set(name for name in archive.namelist() if name.endswith('.pyc'))
        assert actual_members == set(modules), 'Unexpected or omitted compiled client module'
    proof = {'source_commit': commit, 'python': sys.version,
             'wotmod_sha256': sha(read(packages[0])), 'modules': modules,
             'native_gameplay_tested': False}
    record('bytecode.json', proof)
    # Keep the receipt outside dist: only deliverable payload is staged there.
    print('PASS %d client modules match the exact source commit' % len(modules))


def require_x64(data):
    assert data[:2] == b'MZ', 'Missing Windows PE header'
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[offset:offset + 4] == b'PE\0\0', 'Invalid PE signature'
    assert struct.unpack_from('<H', data, offset + 4)[0] == 0x8664, 'Expected x64 executable'


def distribution(app):
    commit = source()
    app = os.path.abspath(app)
    payload = os.path.join(app, '_internal')
    require_x64(read(os.path.join(app, 'wot-0.9.22-offline-battles.exe')))
    require_x64(read(os.path.join(ROOT, 'dist', 'server', 'WoT-0.9.22-LAN-Server.exe')))
    proof = json.loads(read(os.path.join(ROOT, 'build-evidence', 'bytecode.json')))
    assert proof['source_commit'] == commit
    config = 'mods/configs/offline_lan_0922/'
    with zipfile.ZipFile(os.path.join(payload, 'client', '0.9.22.zip')) as client:
        assert client.testzip() is None
        identity = json.loads(client.read(config + 'build_identity.json'))
        assert identity['semanticVersion'] == '0.9.4'
        assert identity['buildIdentity'] == os.environ['WOT_OFFLINE_BUILD_IDENTITY']
        mods = [name for name in client.namelist() if name.endswith('.wotmod')]
        assert len(mods) == 1
        data = client.read(mods[0])
        assert sha(data) == proof['wotmod_sha256'], 'Launcher contains another client build'
        with zipfile.ZipFile(io.BytesIO(data)) as mod:
            assert mod.testzip() is None
            for member, digest in proof['modules'].items():
                assert sha(mod.read(member)) == digest, member
        for catalog in ('navgraphs', 'foliage', 'destructibles'):
            folder = os.path.join(ROOT, catalog)
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    assert client.read(config + catalog + '/' + name) == read(path), path
    sys.path.insert(0, os.path.join(ROOT, 'launcher'))
    import core
    import stage_payload
    server_files = list(stage_payload.PAYLOAD_FILES['0.9.22'])
    for relative in stage_payload.PAYLOAD_TREES['0.9.22']:
        for folder, unused_dirs, files in os.walk(os.path.join(ROOT, relative)):
            server_files.extend(os.path.relpath(os.path.join(folder, name), ROOT)
                                for name in files if name.endswith('.py'))
    for relative in server_files:
        installed = os.path.join(payload, 'servers', '0.9.22', relative)
        assert read(installed) == read(os.path.join(ROOT, relative)), relative
    fake = tempfile.mkdtemp(prefix='six-bug-install-')
    try:
        with open(os.path.join(fake, 'WorldOfTanks.exe'), 'wb') as stream:
            stream.write(b'')
        with open(os.path.join(fake, 'version.xml'), 'wb') as stream:
            stream.write(b'<version> v.0.9.22.0.1 #1513 </version>')
        assert core.inspect_game_root(fake)['client'] == core.PORT_0_9_22
        core.install_client_mod(fake, core.PORT_0_9_22, base_dir=payload)
        assert core._installation_complete(fake, core.PORT_0_9_22,
                                           core._CLIENT_INSTALL[core.PORT_0_9_22])
    finally:
        shutil.rmtree(fake)
    result = {'source_commit': commit, 'identity': identity,
              'verified_client_modules': len(proof['modules']),
              'verified_server_source_files': len(server_files),
              'fake_install_passed': True, 'native_gameplay_tested': False}
    record('distribution.json', result)
    print('PASS current client bytecode, server sources, x64 executables and launcher install')
    return result


def package(app):
    app = os.path.abspath(app)
    receipt = distribution(app)
    evidence = os.path.join(ROOT, 'build-evidence')
    ui = json.loads(read(os.path.join(evidence, 'packaged-editor-smoke.json')))
    ready = json.loads(read(os.path.join(evidence, 'server-readiness.json')))
    assert ready['ready'] is True
    assert ui['ok'] and ui['localization_checked'] and ui['language_switch_preserves_active']
    assert ui['translated_map_count'] == 41 and ui['translated_route_count'] == 96
    for name in ('TESTING_20260916_GROUP1_ZH.md', 'server.log'):
        path = os.path.join(app, name)
        if os.path.isfile(path):
            shutil.move(path, os.path.join(evidence, name))
    allowed = {'wot-0.9.22-offline-battles.exe', '_internal', 'README.txt',
               'LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses'}
    assert set(os.listdir(app)) == allowed, os.listdir(app)
    with open(os.path.join(app, 'README.txt'), 'ab') as stream:
        stream.write(('\nPhysics follow-up r4 test build (2026-09-25).\nSource: ' +
                      receipt['source_commit'] + '\nBuild: ' +
                      receipt['identity']['buildIdentity'] + '\n'
                      'Fresh measured support under the mounted hull releases existing low bridge-top contacts.\n'
                      'Outward bridge-side contacts can release while real backing walls still block motion.\n'
                      'Bounded bridge-edge logs capture contact decisions and suspension movement.\n'
                      'No forced righting is added; Bot route selection and avoidance remain unchanged.\n'
                      'The preceding mass-based contact and grounded resistance fixes are retained.\n'
                      'Landing track damage uses a contact-weighted reconstruction.\n'
                      'Landing crew loss uses floor(hull fall damage * actual crew count / max hull HP).\n'
                      'This deterministic crew rule is an explicit project reconstruction.\n'
                      'Native Windows bridge departure and gameplay acceptance remain pending.\n').encode('utf8'))
    target = os.path.join(ROOT, PACKAGE)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder, dirs, files in os.walk(app):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(folder, name)
                archive.write(path, os.path.relpath(path, app).replace(os.sep, '/'))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(name.split('/')[0] for name in archive.namelist()) == allowed
    receipt.update({'package': PACKAGE, 'bytes': os.path.getsize(target),
                    'packaged_editor_smoke': ui, 'server_readiness': ready})
    record('package-manifest.json', receipt)
    print('PACKAGE %s (%d bytes)' % (PACKAGE, os.path.getsize(target)))


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'source':
        source()
    elif action == 'bytecode':
        bytecode()
    elif action == 'distribution':
        distribution(sys.argv[2])
    elif action == 'package':
        package(sys.argv[2])
    else:
        raise SystemExit('Unknown action: ' + action)
