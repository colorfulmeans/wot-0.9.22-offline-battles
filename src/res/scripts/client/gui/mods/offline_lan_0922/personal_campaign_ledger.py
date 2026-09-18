"""Reclaim only resettable campaign orders and their recorded crew rewards.

Ordinary mission payouts are permanent. The caller owns the completion/reward
markers and wraps a whole reset in GarageState._transaction(). These helpers
validate all of one inverse operation before changing the live snapshot.
"""
from gui.mods.offline_lan_0922.account_rpc.garage import GarageError

TANKWOMAN_DOSSIER_KEY = 'achievements:tankwomenProgress'


def _count(value):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise GarageError('INVALID_PERSONAL_MISSION_REWARD_JOURNAL')
    if result < 0:
        raise GarageError('INVALID_PERSONAL_MISSION_REWARD_JOURNAL')
    return result


def revoke_orders(state, count):
    """Remove earned orders without consuming orders pledged to other tasks."""
    count = _count(count)
    if not count:
        return 0
    snapshot = state.snapshot()
    available = _count(snapshot.get('personalMissionOrders', 0))
    if available < count:
        raise GarageError('PERSONAL_MISSION_RESET_ORDERS_SPENT')
    snapshot['personalMissionOrders'] = available - count
    state.revision += 1
    return count


def revoke_tankwoman(state, effect):
    """Remove the exact crew source recorded by the mission reward journal.

    Save restoration validates a saved source locator and remaps this ID.
    Training and assignment may change the descriptor without changing its
    source. No descriptor-based search is allowed when the source is missing.
    The accompanying berth is an ordinary permanent reward and is retained.
    """
    if not isinstance(effect, dict):
        raise GarageError('INVALID_PERSONAL_MISSION_REWARD_JOURNAL')
    tankman_id = _count(effect.get('tankman', 0))
    if not tankman_id:
        raise GarageError('PERSONAL_MISSION_RESET_CREW_SOURCE_UNAVAILABLE')
    dossier_delta = _count(effect.get('dossier_count', 1))
    snapshot = state.snapshot()
    found = []
    for key in ('barracksTankmen', 'recycleBinTankmen'):
        rows = snapshot.get(key) or {}
        if tankman_id in rows:
            found.append((key, rows, None))
    for record in state._records():
        rows = record.get('tankmen') or {}
        if tankman_id in rows:
            found.append(('vehicle', rows, record))
    if len(found) != 1:
        raise GarageError('PERSONAL_MISSION_RESET_CREW_SOURCE_UNAVAILABLE')
    dossier = snapshot.get('personalMissionDossier') or {}
    dossier_count = _count(dossier.get(TANKWOMAN_DOSSIER_KEY, 0))
    if dossier_count < dossier_delta:
        raise GarageError('PERSONAL_MISSION_RESET_CREW_DOSSIER_CHANGED')

    kind, rows, record = found[0]
    del rows[tankman_id]
    if kind == 'vehicle':
        record['crew'] = [None if value == tankman_id else value
                          for value in (record.get('crew') or ())]
        state._touched.add(int(record['id']))
    elif kind == 'recycleBinTankmen':
        state._touched_recycled.add(tankman_id)
    if dossier_delta:
        snapshot['personalMissionDossier'][TANKWOMAN_DOSSIER_KEY] = (
            dossier_count - dossier_delta)
    state._touched_tankmen.add(tankman_id)
    for record in state._records():
        previous = record.get('lastCrew')
        if isinstance(previous, (list, tuple)) and tankman_id in previous:
            record['lastCrew'] = [None if value == tankman_id else value
                                  for value in previous]
            state._touched.add(int(record['id']))
    state.revision += 1
    return tankman_id
