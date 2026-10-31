"""Exact-client recruit choices and per-save native generation requests."""
import json
import base64
import os
import uuid
import zipfile
from contextlib import contextmanager
import threading

try:
    from . import core, save_ledger, save_slots, vehicle_overlays, bot_lineup_profiles, nation_choices
except ImportError:
    import core, save_ledger, save_slots, vehicle_overlays, bot_lineup_profiles, nation_choices

# Loading the tactics store installs the shared Python-2-compatible contract path.
try:
    from . import bot_tactics_store
except ImportError:
    import bot_tactics_store
from gui.mods.offline_lan_0922 import crew_recruits as contract, crew_skills


def catalogue(game_root):
    unused, package = vehicle_overlays._require_target(game_root)
    result = []
    with zipfile.ZipFile(package) as archive:
        for vehicle in vehicle_overlays.list_vehicle_choices(game_root):
            if not bot_lineup_profiles.vehicle_choice_is_standard(vehicle):continue
            root = vehicle_overlays.packed_xml.read_packed_xml(archive.read(vehicle['member']))
            crew = next((value.value for key, value in root.children if key == b'crew'), None)
            roles = tuple(key.decode('ascii') for key, unused in crew.children) if crew is not None else ()
            roles = tuple(role for role in roles if role in contract.ROLES)
            if roles:
                name=vehicle['nation']+':'+vehicle['vehicle']
                seats=crew_skills.seats(name)
                if len(seats)!=len(roles) or any(r[0]!=role for r,role in zip(seats,roles)):
                    raise ValueError('The crew table does not match the selected client.')
                result.append(dict(vehicle,name=name,roles=roles,seats=seats))
    return sorted(result, key=nation_choices.vehicle_key)


def inbox_path(slot, game_root=None, root=None):
    return os.path.join(save_slots.slot_dir(slot, game_root, root=root), contract.FILE_NAME)


def write_pending(path, rows):
    payload = {'schema': 1, 'crew': [contract.request(row) for row in rows]}
    if len(payload['crew']) > contract.MAX_PENDING:
        raise ValueError('Start the game to receive pending crew first.')
    temporary = path + '.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, 'w', encoding='utf8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    except Exception:
        if os.path.isfile(temporary):
            os.remove(temporary)
        raise



BERTH_BLOCK = 16
INITIAL_BERTHS = 'initial_berths'
_LOCK = threading.RLock()

class BerthsFullError(ValueError):
    pass

@contextmanager
def _edit(slot,game_root,root,is_running):
    """Serialize crew and berth edits, including multiple launcher processes."""
    with _LOCK:
        if (is_running or core.game_is_running)():
            raise save_ledger.SaveLedgerError('Close World of Tanks before changing crew or barracks berths.')
        directory=save_slots.slot_dir(slot,game_root,root=root)
        save_slots.read_slot(slot,game_root,root=root)
        os.makedirs(directory,exist_ok=True)
        with open(os.path.join(directory,'.crew-edit.lock'),'a+b') as lock:
            lock.seek(0,os.SEEK_END)
            if lock.tell()==0:lock.write(b'0');lock.flush()
            lock.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                raise save_ledger.SaveLedgerError('Another crew or barracks edit is in progress. Try again.')
            try:
                yield
            finally:
                lock.seek(0)
                if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def _number(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=save_ledger.MAX_BALANCE:
        raise save_ledger.SaveLedgerError('The barracks data could not be read.')
    return value


def _capacity(slot,game_root=None,root=None):
    from gui.mods.offline_lan_0922.account_rpc import economy
    path=save_ledger.ledger_path(slot,game_root,root=root)
    state=save_ledger._read_state(path)
    if state is None and os.path.lexists(path):
        raise save_ledger.SaveLedgerError('The barracks data could not be read.')
    if state is None:
        path=save_slots.metadata_path(slot,game_root,root=root)
        state=save_ledger._read_state(path)
        if state is None and os.path.lexists(path):
            raise save_ledger.SaveLedgerError('The barracks data could not be read.')
        state=state or {}
        record=save_slots.read_slot(slot,game_root,root=root)
        default=economy.CAREER_BARRACKS_BERTHS if record['mode']==save_slots.MODE_NEW_ACCOUNT else economy.SANDBOX_BARRACKS_BERTHS
        total=_number(state.get(INITIAL_BERTHS,default))
        return path,state,None,total,0,set()
    ledger=state.get('ledger')
    if not isinstance(ledger,dict) or 'berths' not in ledger or not isinstance(ledger.get('barracks'),list):
        raise save_ledger.SaveLedgerError('The barracks data could not be read.')
    total=_number(ledger['berths'])
    members=ledger['barracks']
    try:
        valid=all(isinstance(v,str) and v and base64.b64decode(v,validate=True) for v in members)
    except (ValueError,TypeError):
        valid=False
    # The ledger stores encoded passports, not inventory IDs. Identical
    # passports can belong to distinct recruits and each occupies a berth.
    if not valid or len(members)>total:
        raise save_ledger.SaveLedgerError('The barracks data could not be read.')
    receipts=contract.identities(ledger.get(contract.RECEIPTS,[]))
    return path,state,ledger,total,len(members),set(receipts)


def capacity(slot,game_root=None,root=None):
    unused,state,ledger,total,occupied,receipts=_capacity(slot,game_root,root)
    pending=sum(row['id'] not in receipts for row in contract.read(inbox_path(slot,game_root,root)))
    return dict(total=total,occupied=occupied,pending=pending,available=max(0,total-occupied-pending))


def expand_berths(slot,game_root=None,root=None,is_running=None):
    with _edit(slot,game_root,root,is_running):
        before=capacity(slot,game_root,root)
        path,state,ledger,total,occupied,receipts=_capacity(slot,game_root,root)
        if total>save_ledger.MAX_BALANCE-BERTH_BLOCK:
            raise save_ledger.SaveLedgerError('The barracks berth limit has been reached.')
        if ledger is None:state[INITIAL_BERTHS]=total+BERTH_BLOCK
        else:ledger['berths']=total+BERTH_BLOCK
        save_ledger.queue_account_changes(ledger if ledger is not None else state,
            [dict(phase='granted',rewards=[dict(kind='berths',count=BERTH_BLOCK)])],ledger is not None)
        save_ledger._write_state(path,state)
        before['total']+=BERTH_BLOCK
        before['available']=max(0,before['total']-before['occupied']-before['pending'])
        return before


def add(slot, game_root, vehicle, seat, female, skills, training=100, root=None, is_running=None):
    with _edit(slot,game_root,root,is_running):
        choices = {row['name']: row for row in catalogue(game_root)}
        selected = choices.get(vehicle)
        if selected is None or isinstance(seat,bool) or not isinstance(seat,int) or not 0<=seat<len(selected['seats']):
            raise ValueError('Select a trained vehicle with the requested crew role.')
        row = contract.request(dict(id=uuid.uuid4().hex, nation=selected['nation'], vehicle=vehicle,
                                    role=selected['seats'][seat][0], seat=seat, training=training, female=female, skills=skills))
        if capacity(slot,game_root,root)['available']<1:
            raise BerthsFullError('Not enough barracks berths. Click Add 16 barracks berths first.')
        path = inbox_path(slot, game_root, root)
        rows = contract.read(path)
        write_pending(path, rows + [row])
        return row
