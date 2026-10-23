"""Bake exact #1513 crew seats and native active skill sets (read-only)."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'launcher'))
import vehicle_overlays as overlays


def build(game,python27):
    package=Path(game)/'res/packages/scripts.pkg'
    member='scripts/common/items/components/skills_constants.pyc'
    code="import zipfile,marshal,json;z=zipfile.ZipFile(%r);s={};exec marshal.loads(z.read(%r)[8:]) in s;print(json.dumps(dict(common=sorted(s['COMMON_SKILLS']),roles={k:sorted(v) for k,v in s['SKILLS_BY_ROLES'].items()},active=sorted(s['ACTIVE_SKILLS']))))"%(str(package),member)
    skills=json.loads(subprocess.check_output([python27,'-B','-c',code]))
    seats={}
    with zipfile.ZipFile(package) as archive:
        source_hash=hashlib.sha256(archive.read(member)).hexdigest()
        for vehicle in overlays.list_vehicle_choices(game):
            root=overlays.packed_xml.read_packed_xml(archive.read(vehicle['member']))
            crew=next(v.value for k,v in root.children if k==b'crew')
            rows=[]
            for key,value in crew.children:
                text=base64.b64encode(value.value).decode('ascii') if value.value_type==5 else value.value.decode('ascii')
                rows.append(tuple([key.decode('ascii')]+text.split()))
            seats[vehicle['nation']+':'+vehicle['vehicle']]=tuple(rows)
    lines=['"""Generated #1513 crew seats; regenerate with tools/bake_crew_seats.py."""',
           'SKILLS_SOURCE_SHA256 = '+repr(source_hash),
           'COMMON = '+repr(tuple(skills['common'])),
           'ACTIVE = '+repr(tuple(skills['active'])),
           'ROLE_SKILLS = {']
    lines.extend('    %r: %r,'%(k,tuple(v)) for k,v in sorted(skills['roles'].items()))
    lines.extend(['}','SEATS = {'])
    lines.extend('    %r: %r,'%(k,v) for k,v in sorted(seats.items()))
    lines.extend(['}',''])
    return '\n'.join(lines),seats


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('client');p.add_argument('--python27',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();text,seats=build(a.client,a.python27)
    Path(a.output).write_bytes(text.encode('ascii'))
    print('%d vehicles, %d seats'%(len(seats),sum(map(len,seats.values()))))
