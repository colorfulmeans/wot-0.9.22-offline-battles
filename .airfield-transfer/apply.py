"""Fix only the standalone verifier: WoT normally supplies gui and gui.mods."""
from pathlib import Path
import subprocess
p = Path('tools/verify_airfield_test_build.py')
text = p.read_text()
old = "        sys.path.insert(0, os.path.join(unpacked, 'res', 'scripts', 'client'))\n        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid"
new = """        sys.path.insert(0, os.path.join(unpacked, 'res', 'scripts', 'client'))
        # WoT owns these parent packages. Supply only their search paths in
        # this isolated CPython 2.7 test; do not alter the distributed mod.
        for package_name, relative in (('gui', 'gui'), ('gui.mods', 'gui/mods')):
            package_stub = types.ModuleType(package_name)
            package_stub.__path__ = [os.path.join(unpacked, 'res', 'scripts', 'client', *relative.split('/'))]
            sys.modules[package_name] = package_stub
        sys.modules['gui'].mods = sys.modules['gui.mods']
        from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid"""
assert text.count(old) == 1, 'Verifier changed; refusing an unreviewed edit'
p.write_text(text.replace(old, new))
subprocess.check_call(['git', 'add', '--', str(p)])
subprocess.check_call(['git', 'rm', '--', '.airfield-transfer/apply.py'])
print('Standalone package namespace fixed; no runtime source or asset changed.')
