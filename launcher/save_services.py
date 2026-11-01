"""Offline edits to stock reserve quantities and garage capacity."""
try:
    from . import save_ledger, save_slots, crew_store
except ImportError:
    import save_ledger, save_slots, crew_store
from gui.mods.offline_lan_0922 import offline_services as policy
from gui.mods.offline_lan_0922.account_rpc import economy


def _read(slot, game_root=None, root=None):
    path = save_ledger.ledger_path(slot, game_root, root=root)
    state = save_ledger._read_state(path)
    if state is not None:
        if not isinstance(state.get('ledger'), dict):
            raise save_ledger.SaveLedgerError('The save is not in the expected format.')
        return path, state, state['ledger'], True
    path = save_slots.metadata_path(slot, game_root, root=root)
    state = save_ledger._read_state(path) or {}
    return path, state, state, False


def read_reserves(slot, game_root=None, root=None):
    unused, state, owner, garage = _read(slot, game_root, root)
    return policy.reserve_state(owner.get('offlineServices', {}) if garage else
                                owner.get('initial_services', {}))['counts']


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= save_ledger.MAX_BALANCE:
        raise save_ledger.SaveLedgerError('Quantity must be a non-negative whole number.')
    return value


def write_reserves(slot, counts, game_root=None, root=None, is_running=None):
    counts = {key: _count(value) for key, value in counts.items()}
    if any(key not in policy.RESERVE_BY_ID for key in counts):
        raise save_ledger.SaveLedgerError('Unknown personal reserve.')
    with crew_store._edit(slot, game_root, root, is_running):
        path, state, owner, garage = _read(slot, game_root, root)
        services = owner.setdefault('offlineServices' if garage else 'initial_services', {})
        reserves = policy.reserve_state(services)
        changes = []
        for phase, sign in (('granted', 1), ('revoked', -1)):
            rewards = []
            for key, value in counts.items():
                delta = (value - reserves['counts'][key]) * sign
                if delta > 0:
                    rewards.append({'kind': 'reserve', 'id': policy.RESERVE_IDS[key], 'count': delta})
            if rewards:
                changes.append({'phase': phase, 'rewards': rewards})
        reserves['counts'].update(counts)
        services['personalReserves'] = reserves
        save_ledger.queue_account_changes(owner, changes, garage)
        save_ledger._write_state(path, state)
        return reserves['counts']


def add_slots(slot, quantity, game_root=None, root=None, is_running=None):
    quantity = _count(quantity)
    if quantity == 0:
        raise save_ledger.SaveLedgerError('Quantity must be positive.')
    with crew_store._edit(slot, game_root, root, is_running):
        path, state, owner, garage = _read(slot, game_root, root)
        record = save_slots.read_slot(slot, game_root, root=root)
        default = (economy.CAREER_GARAGE_SLOTS if record['mode'] == save_slots.MODE_NEW_ACCOUNT
                   else economy.SANDBOX_GARAGE_SLOTS)
        key = 'slots' if garage else 'initial_slots'
        total = _count(owner.get(key, default)) + quantity
        _count(total)
        owner[key] = total
        save_ledger.queue_account_changes(owner, [{'phase': 'granted',
            'rewards': [{'kind': 'slots', 'count': quantity}]}], garage)
        save_ledger._write_state(path, state)
        return total
