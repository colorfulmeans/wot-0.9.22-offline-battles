"""Stage the reviewed generated Flash input without tracking client assets.

The input blob is a build cache, not a file in the source tree. Rebuilding the
transformer requires the exact locally owned client documented in
docs/depot-styles-build.md. Both transformer and generated asset are gated.
"""
import base64
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
proof = json.loads((root/'tools/release0100-style-input.json').read_text())
assert hashlib.sha256((root/'tools/build_depot_style_swf.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == proof['transformer_sha256']
url = 'https://api.github.com/repos/colorfulmeans/wot-0.9.22-offline-battles/git/blobs/' + proof['blob_sha']
with urlopen(Request(url, headers={'User-Agent': 'WoT-release-builder'}), timeout=60) as response:
    record = json.load(response)
assert record['sha'] == proof['blob_sha'] and record['encoding'] == 'base64'
raw = base64.b64decode(record['content'])
assert hashlib.sha256(raw).hexdigest() == proof['output_sha256']
assert raw[:3] in (b'CWS', b'FWS')
output = root/'build/depot/lobby.swf'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(raw)
Path(str(output)+'.json').write_text(json.dumps(proof), encoding='utf-8')
print('Verified generated warehouse/shop UI staged.')
