"""Align existing graph objectives to exact #1513 standard control points."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.capture_circles import standard_circles_from_space
from gui.mods.offline_lan_0922.navigation_graph_schema import SUPPORTED_MAPS


def calibrate(client):
    records = {}
    graphs = {}
    for name in SUPPORTED_MAPS:
        path = ROOT / 'navgraphs' / (name + '.json')
        raw = path.read_bytes()
        graph = json.loads(raw)
        with zipfile.ZipFile(Path(client) / 'res/packages' / (name + '.pkg')) as archive:
            space = archive.read('spaces/' + name + '/space.bin')
        circles = standard_circles_from_space(space)
        records[name] = dict(space_sha256=hashlib.sha256(space).hexdigest(),
                             centres=[p[0] for p in circles], radii=[p[1] for p in circles])
        # Preserve authored profiles only for this exact verified metadata change.
        graph.setdefault('capture_coordinate_previous_sha256', hashlib.sha256(raw).hexdigest())
        graph['objective_bases'] = records[name]['centres']
        graph['objective_base_radii'] = records[name]['radii']
        graphs[path] = graph
    # Validate the entire client before writing any map.
    for path, graph in graphs.items():
        path.write_text(json.dumps(graph, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8', newline='\n')
    manifest_path = ROOT / 'navgraphs/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest['maps']:
        entry['sha256'] = hashlib.sha256((ROOT / 'navgraphs' / entry['file']).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (ROOT / 'tests/fixtures/standard_capture_circles_1513.json').write_text(
        json.dumps(records, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client')
    calibrate(parser.parse_args().client)
