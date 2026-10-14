"""Shared #1513 critical-result bits and environmental transition checkpoints."""

CRIT_DEVICE_INDICES = {
    "engineHealth": 0, "ammoBayHealth": 1, "fuelTankHealth": 2,
    "radioHealth": 3, "leftTrackHealth": 4, "rightTrackHealth": 4,
    "gunHealth": 5, "turretRotatorHealth": 6, "surveyingDeviceHealth": 7,
}
CRIT_TANKMAN_INDICES = {
    "commander": 0, "driver": 1, "radioman1": 2, "radioman2": 2,
    "gunner1": 3, "gunner2": 3, "loader1": 4, "loader2": 4,
}

def transition_mask(previous, current, crew_only=False):
    """Return the #1513 ``crits`` bits this transition newly set.

    ``scripts/client/gui/shared/crits_mask_parser.py`` of build #1513 reads
    bits 0-7 as critically damaged devices, bits 12-23 as destroyed devices
    and bits 24-31 as destroyed crew, indexed by ``VEHICLE_DEVICE_TYPE_NAMES``
    and ``VEHICLE_TANKMAN_TYPE_NAMES`` from ``battle_results_shared``.
    """
    if not isinstance(current, dict):
        return 0
    previous = previous if isinstance(previous, dict) else {}
    mask = 0

    def device_states(value):
        return dict(
            (str(record.get("name", "")), str(record.get("state", "")))
            for record in value.get("devices") or ()
            if isinstance(record, dict))

    old_devices = device_states(previous)
    old_destroyed = set(str(name) for name in previous.get("destroyed") or ())
    for name, state in device_states(current).items():
        index = CRIT_DEVICE_INDICES.get(name)
        if index is None:
            continue
        if state == "critical" and old_devices.get(name) != "critical":
            mask |= 1 << index
    for name in (set(str(name) for name in current.get("destroyed") or ()) -
                 old_destroyed):
        index = CRIT_DEVICE_INDICES.get(name)
        if index is not None:
            mask |= 1 << (12 + index)
    for name in (set(str(name) for name in current.get("crew_ko") or ()) -
                 set(str(name) for name in previous.get("crew_ko") or ())):
        index = CRIT_TANKMAN_INDICES.get(name)
        if index is not None:
            mask |= 1 << (24 + index)
    return mask & 0xff000000 if crew_only else mask



def accumulate(totals, actor, cause, previous, current, crew_only=False):
    mask = transition_mask(previous, current, crew_only)
    for index in range(32):
        bit = 1 << index
        if mask & bit:
            key = (int(actor), str(cause), bit)
            totals[key] = totals.get(key, 0) + 1
    return mask
