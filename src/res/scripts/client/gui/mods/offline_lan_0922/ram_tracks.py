"""Track-only ram losses nominated by exact native contact materials."""
import copy
import math
TRACKS = frozenset(('leftTrackHealth','rightTrackHealth'))
SAFE_SPEED = 2.0
HP_PER_EXCESS_MS = 25.0  # Offline trial coefficient, not a retail constant.

class ContactArmors(tuple):
    def __new__(cls, values, tracks):
        result=tuple.__new__(cls, values)
        result.tracks=tuple(tuple(v) for v in tracks)
        return result
    def reversed(self):
        return ContactArmors(tuple(reversed(self)),tuple(reversed(self.tracks)))

def names(value):
    if not isinstance(value,(list,tuple)) or len(value)>2:
        raise ValueError('invalid ram track contacts')
    if any(name not in TRACKS for name in value):
        raise ValueError('ram contact is not a track')
    return sorted(set(value))

def damage(current, profile, contacts, speed):
    contacts=names(contacts)
    speed=float(speed)
    if math.isnan(speed) or math.isinf(speed) or not 0. <= speed <= 200.:
        raise ValueError('invalid ram impact speed')
    loss=max(0.,speed-SAFE_SPEED)*HP_PER_EXCESS_MS
    if not contacts or loss<=0.:return None
    maxima={row['name']:float(row['max_hp']) for row in (profile or {}).get('devices',())
        if row.get('name') in TRACKS and float(row.get('max_hp',0.))>0.}
    out=copy.deepcopy(current or {})
    devices={r['name']:dict(r) for r in out.get('devices',())}
    destroyed=set(out.get('destroyed',()));events=[];changed=False
    for name in contacts:
        maximum=maxima.get(name)
        if maximum is None:continue
        row=devices.get(name,dict(name=name,hp=maximum,max_hp=maximum,state='normal'))
        old=row.get('state','normal');before=float(row.get('hp',maximum))
        after=max(0.,before-loss)
        if after==before:continue
        state='destroyed' if after<=0. else ('critical' if old=='critical' or after<=maximum*.5 else 'normal')
        row.update(hp=after,max_hp=maximum,state=state);devices[name]=row;changed=True
        if state=='destroyed':destroyed.add(name)
        else:destroyed.discard(name)
        if state!=old:events.append(dict(kind='device',name=name,state=state,old_state=old,cause='ramming'))
    if not changed:return None
    out.update(devices=[devices[k] for k in sorted(devices)],destroyed=sorted(destroyed),events=events)
    return out
