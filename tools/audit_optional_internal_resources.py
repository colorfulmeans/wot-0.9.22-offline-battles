"""Read-only inventory of possible interior geometry in another PC client.

This does not make another client a supported runtime, infer internal zones
from an exterior mesh, or accept an alias from a similar vehicle name.
"""
import argparse
import json
from pathlib import Path
import re
import zipfile

VEHICLES = ('G136_Tiger_131', 'A104_M4A3E8A', 'A106_M48A2_120',
            'A86_T23E3', 'R121_KV4_KTT', 'R126_Object_730_5')
MARKERS = ('ammoBay', 'fuelTank', 'transmission', 'surveyingDevice',
           'turretRotator', 'crew_00', 'gunner_1', 'loader_1')
GEOMETRY_SUFFIXES = ('.havok', '.hkx', '.primitives', '.primitives_processed',
                     '.visual', '.visual_processed', '.model')


def vehicle_for_member(member):
    parts = member.replace('\\', '/').lower().split('/')
    return next((v for v in VEHICLES if v.lower() in parts or
                 parts[-1] == v.lower()+'.xml'), None)


def scan(root):
    root = Path(root)
    rows = {v:dict(members=0, geometry_files=0, collision_files=[],
                  named_interior_candidates=[], modern_tagfiles=0,
                  read_errors=[]) for v in VEHICLES}
    packages = sorted((root/'res/packages').glob('*.pkg'))
    packages = [p for p in packages if p.name == 'scripts.pkg' or
                p.name.startswith('vehicles_')]
    for package in packages:
        with zipfile.ZipFile(package) as archive:
            for member in archive.infolist():
                vehicle = vehicle_for_member(member.filename)
                if vehicle is None or member.is_dir():
                    continue
                row = rows[vehicle]
                row['members'] += 1
                if not member.filename.endswith(GEOMETRY_SUFFIXES):
                    continue
                row['geometry_files'] += 1
                if '/collision_client/' in member.filename:
                    row['collision_files'].append(package.name+':'+member.filename)
                try:
                    blob = archive.read(member)
                except (RuntimeError, OSError, zipfile.BadZipFile) as error:
                    row['read_errors'].append(dict(member=member.filename, error=str(error)))
                    continue
                # A marker is only a lead. It is not proof of an indexed mesh,
                # a frame transform, or identity with PC #1513.
                markers = [m for m in MARKERS if re.search(
                    rb'(?<![A-Za-z0-9_])'+m.encode('ascii')+rb'(?![A-Za-z0-9_])', blob)]
                if blob[4:8] == b'TAG0':
                    row['modern_tagfiles'] += 1
                if markers:
                    row['named_interior_candidates'].append(dict(
                        package=package.name, member=member.filename, markers=markers))
    for row in rows.values():
        interior = any(set(c['markers'])-{'surveyingDevice'} for c in row['named_interior_candidates'])
        row['conclusion'] = ('needs_mesh_and_0922_registration_review' if interior else
            'only_observation_device_named_no_complete_interior' if row['named_interior_candidates'] else
            'no_named_interior_source_found')
    return dict(version_xml=(root/'version.xml').read_text(encoding='utf-8'),
                packages_scanned=len(packages), vehicles=rows,
                scope='named geometry source inventory only; no runtime acceptance or inferred interiors')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client_root')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(scan(args.client_root), indent=2), encoding='utf-8')
