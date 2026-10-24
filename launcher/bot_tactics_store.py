"""Launcher profile storage and original minimap loading. No game-file writes."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

try:
    from . import core
except ImportError:
    import core

# Source checkout and packaged source tree share the same pure-data contract.
_source = Path(__file__).resolve().parents[1] / 'src/res/scripts/client'
_bundled = Path(getattr(sys, '_MEIPASS', '')) / 'servers/0.9.22/src/res/scripts/client'
for path in (_source, _bundled):
    if path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
from gui.mods.offline_lan_0922 import bot_tactics as contract
from gui.mods.offline_lan_0922 import bot_tactics_runtime as runtime

try:
    from . import bot_tactics_labels as labels
except ImportError:
    import bot_tactics_labels as labels

# Backward-compatible Chinese display lookup; runtime keys stay unchanged.
MAP_LABELS = {key: labels.map_label(key, 'zh') for key in contract.MAPS}



def root_path():
    return Path(core.settings_path()).parent / 'bot_tactics'


def default_spg_positions(name, graph, profile=None):
    """Show sourced parking regions, never the regular combat-route nodes."""
    from gui.mods.offline_lan_0922 import spg_positions
    entry = spg_positions.CATALOG['maps'].get(name)
    if not graph:return []
    deleted = set(contract.map_settings(profile, name).get('deleted_positions', ()))
    baseline = contract.default_map(name).get('positions')
    if baseline is not None:
        return [p for p in baseline if p['id'] not in deleted]
    if entry is None:
        for path in (_source.parents[3]/'server',_bundled.parents[3]/'server'):
            if path.is_dir() and str(path) not in sys.path:sys.path.insert(0,str(path))
        from server_bot_ai import BotPlanner
        planner=BotPlanner()
        routes,_=runtime.default_routes(profile or contract.empty(),name,graph)
        result=[]
        for team in (1,2):
            own,enemy=graph['bases'][team-1],graph['bases'][2-team]
            axis=tuple(dict(x=p[0],y=0,z=p[1]) for p in (own,enemy))
            for index,route in enumerate(routes.get(str(team),())):
                if route.get('_editor_class'):continue
                weights=route.get('class_weights') or {}
                if weights.get('SPG',0)<=0 and route.get('role_weights',{}).get('artillery',0)<=0:continue
                wire=dict(route,waypoints=[dict(x=p[0],y=0,z=p[1]) for p in route['waypoints']])
                point=planner._artillery_anchor(dict(id=index,route=wire),axis)['point']
                heading=math.degrees(math.atan2(enemy[0]-point['x'],enemy[1]-point['z']))
                result.append(dict(id='spg_%d_%s'%(team,route['id']),team=team,
                    label=labels.route_label(route['id'],'en'),point=[point['x'],point['z']],
                    radius=16.,heading=heading,priority=5))
        return [p for p in result if p['id'] not in deleted]
    grid = spg_positions._Graph(graph, entry['bounds'])
    result = []
    for team in (1, 2):
        side = entry['spawn_sides'][str(team)]
        by_zone = {}
        for zone, cell, index, point in grid.candidates(entry, side, 6.0):
            by_zone.setdefault(zone['id'], (zone, cell, point))
        enemy = graph['bases'][2-team]
        for identity, (zone, cell, point) in sorted(by_zone.items()):
            heading = math.degrees(math.atan2(enemy[0]-point[0], enemy[1]-point[2]))
            result.append(dict(id='spg_%d_%s'%(team,identity), team=team,
                               label='%s / %s'%(identity,cell), point=[point[0],point[2]],
                               radius=16.0, heading=heading, priority=5))
    return [p for p in result if p['id'] not in deleted]


def _atomic(path, document):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data = (contract.dumps(document) + '\n').encode('ascii')
    if len(data) > contract.MAX_BYTES:
        raise contract.TacticsError('Document is too large')
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if path.exists():
            shutil.copy2(str(path), str(path) + '.bak')
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _commit_files(changes):
    """Stage all writes before mutation and restore originals on an I/O failure."""
    changes=dict(changes)
    for path,data in list(changes.items()):
        backup=Path(str(path)+'.bak')
        if data is not None and path.exists() and path.suffix!='.bak' and backup not in changes:
            changes[backup]=path.read_bytes()
    originals={path:path.read_bytes() if path.exists() else None for path in changes}
    staged={}
    def stage(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=str(path.parent))
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
        except BaseException:
            os.unlink(name);raise
        return name
    done=[]
    try:
        for path,data in changes.items():
            if data is not None:staged[path]=stage(path,data)
        try:
            for path,data in changes.items():
                if data is None:path.unlink(missing_ok=True)
                else:os.replace(staged[path],path)
                done.append(path)
        except BaseException:
            for path in reversed(done):
                data=originals[path]
                if data is None:path.unlink(missing_ok=True)
                else:
                    temp=stage(path,data)
                    try:os.replace(temp,path)
                    finally:
                        if os.path.exists(temp):os.unlink(temp)
            raise
    finally:
        for name in staged.values():
            if os.path.exists(name):os.unlink(name)


def _encoded(document):
    data=(contract.dumps(document)+'\n').encode('ascii')
    if len(data)>contract.MAX_BYTES:raise contract.TacticsError('Document is too large')
    return data


_UNSPECIFIED=object()


class Store:
    def __init__(self, directory=None):
        self.root = Path(directory) if directory else root_path()
        self.profiles = self.root / 'profiles'
        self.active_path = self.root / 'active.json'

    def _load_owned(self, path):
        # Immutable defaults may contain a route retired by this build. Refresh
        # their identity before strict route validation; never reset user plans.
        data=path.read_bytes()
        if len(data)<=contract.MAX_BYTES:
            try:
                raw=json.loads(data.decode('utf-8-sig'))
            except (ValueError,UnicodeError):
                raw=None
            if (isinstance(raw,dict) and isinstance(raw.get('name'),str)
                    and raw['name'].casefold()=='default'
                    and raw.get('client')==contract.CLIENT
                    and raw.get('schema')==contract.SCHEMA):
                current=contract.default_profile()
                if raw!=current:_atomic(path,current)
                return contract.canonical(current)
        return contract.load(str(path))

    def ensure_active(self):
        if not self.active_path.exists():
            _atomic(self.active_path, contract.default_profile())
        document = self._load_owned(self.active_path)
        if document['name'].casefold() == 'default' and document != contract.default_profile():
            _atomic(self.active_path, contract.default_profile())
        # Keep the runtime materialization synchronized with its named owner.
        if document['name'].casefold() != 'default':
            path=self.profile_path(document['name'])
            if path.exists():
                latest=contract.load(str(path))
                if latest!=document:_atomic(self.active_path,latest)
            else:
                # Migrate an older applied snapshot into a named profile once.
                _atomic(path,document)
        return str(self.active_path.resolve())

    def active(self):
        return contract.load(self.ensure_active())

    def names(self):
        result = []
        if self.profiles.exists():
            for path in sorted(self.profiles.glob('*.json')):
                try:
                    document=self._load_owned(path)
                    if document['name'].casefold()=='default' and document!=contract.default_profile():
                        _atomic(path,contract.default_profile())
                    result.append(document['name'])
                except contract.TacticsError:
                    continue  # not deleted; importing it still reports the error
        return ['Default'] + sorted(set(n for n in result if n.casefold() != 'default'))

    def unique_name(self, name):
        name = contract._text(name, 48)
        occupied = {n.casefold() for n in self.names()}
        if name.casefold() not in occupied:
            return name
        index = 1
        while True:
            suffix = str(index)
            candidate = name[:48-len(suffix)] + suffix
            if candidate.casefold() not in occupied:
                return candidate
            index += 1

    def profile_path(self, name):
        # Labels need not be safe path components; never use a label as a path.
        name = contract._text(name, 48)
        return self.profiles / (hashlib.sha256(name.encode('utf8')).hexdigest() + '.json')

    def read(self, name):
        if name.casefold() == 'default':
            return contract.default_profile()
        return contract.load(str(self.profile_path(name)))

    def check_name(self,name,previous_name=None):
        name=contract._text(name,48)
        if name.casefold()=='default':raise contract.TacticsError('Name already exists: Default')
        for existing in self.names():
            if existing.casefold()==name.casefold() and existing!=previous_name:
                raise contract.TacticsError('Name already exists: '+existing)
        return name

    def save(self, document, apply=False, previous_name=_UNSPECIFIED):
        document = contract.canonical(document)
        import bot_tactics_geometry
        bot_tactics_geometry.validate(document, contract, graph_data)
        from gui.mods.offline_lan_0922.bot_fittings import validate_profile
        validate_profile(document)
        name=document['name']
        if name.casefold()=='default':
            if previous_name is not _UNSPECIFIED:
                raise contract.TacticsError('Name already exists: Default')
            default=contract.canonical(contract.default_profile())
            if document!=default:raise contract.TacticsError('Default is read only; create a custom profile first')
            if apply:_commit_files({self.active_path:_encoded(default)})
            return copy.deepcopy(default)
        if previous_name is _UNSPECIFIED:previous_name=name
        self.check_name(name,previous_name)
        if previous_name is not None and previous_name.casefold()=='default':
            raise contract.TacticsError('Default is read only')
        active=self.active()
        changes={self.profile_path(name):_encoded(document)}
        if previous_name is not None and previous_name!=name:
            for path in (self.profile_path(previous_name),Path(str(self.profile_path(previous_name))+'.bak')):
                changes[path]=None
        if apply or active['name']==previous_name:changes[self.active_path]=_encoded(document)
        _commit_files(changes)
        return copy.deepcopy(document)

    def delete(self,name):
        if name.casefold()=='default':raise contract.TacticsError('Default is read only')
        path=self.profile_path(name)
        if not path.exists():raise contract.TacticsError('Profile does not exist: '+name)
        changes={path:None,Path(str(path)+'.bak'):None}
        if self.active()['name']==name:changes[self.active_path]=_encoded(contract.default_profile())
        _commit_files(changes)

    def export(self, document, filename):
        document = contract.canonical(document)
        import bot_tactics_geometry
        bot_tactics_geometry.validate(document, contract, graph_data)
        _atomic(filename, document)

    @staticmethod
    def import_file(filename):
        document=contract.load(str(filename))
        import bot_tactics_geometry
        bot_tactics_geometry.validate(document, contract, graph_data)
        from gui.mods.offline_lan_0922.bot_fittings import validate_profile
        validate_profile(document)
        return document


def ammunition_preview(game_root, vehicle, values, ratios=None):
    """Resolve the actual selected research gun from pinned source resources."""
    try:
        from . import vehicle_overlays as overlays
    except ImportError:
        import vehicle_overlays as overlays
    from gui.mods.offline_lan_0922 import bot_fittings, ammo_policy
    def plain(value):
        if isinstance(value, overlays.packed_xml.PackedValue):return plain(value.value)
        if isinstance(value, overlays.packed_xml.PackedElement):return dict((k.decode(),plain(v)) for k,v in value.children)
        return value.decode('utf8',errors='replace') if isinstance(value,bytes) else value
    package=Path(game_root)/'res/packages/scripts.pkg'
    nation,name=vehicle.split(':')
    def read(path):return plain(overlays._read_source_member(str(package),'scripts/item_defs/vehicles/'+path)[1])
    selected=bot_fittings.plan(vehicle,values.get('skill','regular'),dict((k,values[k]) for k in ('development',) if k in values))
    modules=selected['modules'];definition=read(nation+'/'+name+'.xml')
    local=definition['turrets0'][modules['turret']]['guns'][modules['gun']] or {}
    gun=read(nation+'/components/guns.xml')['shared'][modules['gun']]
    gun.update(local)
    shell_data=read(nation+'/components/shells.xml')
    translations=overlays._vehicle_translations(game_root,nation)
    def caption(name):
        text=shell_data[name].get('userString',name)
        key=text.split(':',1)[-1] if text.startswith('#') else text
        return translations.gettext(key) if translations else name
    shells=[dict(index=i,name=n,label=caption(n),kind=shell_data[n]['kind']) for i,n in enumerate(gun['shots'])]
    profile=dict(vehicle_name=vehicle,gun_name=modules['gun'],shells=shells,class_tag=bot_fittings.CLASSES[vehicle],
                 clip_size=int(float((gun.get('clip') or {}).get('count',1))),ammo_ratios=[1]*len(shells))
    ordered=ammo_policy.ordered(profile)
    if ratios is None:profile.pop('ammo_ratios')
    else:profile['ammo_ratios']=list(ratios)
    counts=ammo_policy.allocation(profile,int(float(gun['maxAmmo'])),len(shells))
    listed=read(nation+'/list.xml')[name]
    return dict(vehicle=vehicle,gun=modules['gun'],shells=ordered,counts=counts,clip_size=profile['clip_size'],fixed=isinstance(listed.get('price'),dict) and 'gold' in listed['price'])


def graph_data(name):
    if name not in contract.MAPS:
        raise contract.TacticsError('Unknown map')
    filename = name + '.json'
    source = Path(__file__).resolve().parents[1] / 'navgraphs' / filename
    if source.is_file() and not getattr(sys, 'frozen', False):
        data = source.read_bytes()
    else:
        archive = core.client_archive('0.9.22')
        with zipfile.ZipFile(archive) as pack:
            member = 'mods/configs/offline_lan_0922/navgraphs/' + filename
            info = pack.getinfo(member)
            if info.file_size > 40 * 1024 * 1024:
                raise contract.TacticsError('Navigation member too large')
            data = pack.read(member)
    if hashlib.sha256(data).hexdigest() != contract.MAPS[name]['resource_sha256']:
        raise contract.TacticsError('Navigation resource hash mismatch')
    return json.loads(data)


def minimap_image(game_root, name):
    """Read original DDS on demand; never distribute Wargaming map artwork."""
    from PIL import Image
    package = Path(game_root) / 'res/packages' / (name + '.pkg')
    with zipfile.ZipFile(package) as pack:
        names = [n for n in pack.namelist() if n.replace('\\', '/').lower().endswith('/mmap.dds')]
        if len(names) != 1 or pack.getinfo(names[0]).file_size > 32 * 1024 * 1024:
            raise contract.TacticsError('Original minimap missing or too large')
        raw = pack.read(names[0])
    with Image.open(io.BytesIO(raw)) as image:
        if image.width > 4096 or image.height > 4096:
            raise contract.TacticsError('Minimap dimensions too large')
        return image.convert('RGB')


def navigation_image(graph):
    """Explicitly labelled fallback, a navigation raster, not original map art."""
    from PIL import Image
    w, h = int(graph['width']), int(graph['height'])
    data = bytearray(w * h * 3)
    for index, height in enumerate(graph['heights_mm']):
        row, col = divmod(index, w)
        color = ((62, 77, 64) if height is not None and not int(graph['hazards'][index]) & 15 else (32, 37, 41))
        target = ((h - 1 - row) * w + col) * 3
        data[target:target + 3] = bytes(color)
    image = Image.frombytes('RGB', (w, h), bytes(data))
    # Raster sample origins may extend outside the exact playable rectangle.
    b = contract.MAPS[graph['map']]['bounds']; ox, oz = graph['origin']; cell = graph['cell_size']
    box = ((b[0]-ox)/cell+0.5, h-0.5-(b[3]-oz)/cell,
           (b[2]-ox)/cell+0.5, h-0.5-(b[1]-oz)/cell)
    return image.crop(tuple(int(round(v)) for v in box))


class ViewTransform:
    """North-up world/pixel transform, including non-centred arenas."""
    def __init__(self, bounds, width=700, height=600):
        self.bounds = bounds; self.width = width; self.height = height
        self.zoom = 1.0; self.pan_x = 0.0; self.pan_y = 0.0

    def frame(self):
        b = self.bounds
        scale = min((self.width-48)/(b[2]-b[0]), (self.height-48)/(b[3]-b[1])) * self.zoom
        return ((self.width-(b[2]-b[0])*scale)/2+self.pan_x,
                (self.height-(b[3]-b[1])*scale)/2+self.pan_y, scale)

    def screen(self, point):
        left, top, scale = self.frame(); b = self.bounds
        return left + (point[0]-b[0])*scale, top + (b[3]-point[1])*scale

    def world(self, x, y):
        left, top, scale = self.frame(); b = self.bounds
        return (max(b[0], min(b[2], b[0]+(x-left)/scale)),
                max(b[1], min(b[3], b[3]-(y-top)/scale)))
