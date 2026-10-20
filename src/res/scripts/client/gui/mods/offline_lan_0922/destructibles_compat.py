# -*- coding: utf-8 -*-
"""Expose the 0.8.2 AreaDestructibles surface on pinned #1513.

The authority module retains the 0.8.2 law with explicit #1513 ABI fixes.
#1513 moved the encoders and damage-type constants to
``DestructiblesCache``; this adapter restores only those moved names.  It also
replaces one unsafe #1513 tree-descriptor lookup.

``wg_getDestructibleFilename`` (``WorldOfTanks.exe`` ``0x006b2580``) is not a
safe probe: for a resolved item whose native type owns no name handler it
reaches ``PyString_FromString(NULL)`` and faults natively.  The chunk list
``wg_getChunkDestrFilenames`` (``0x006b1a10``) guards both nulls and is the
safe boundary, but it may be compacted: it appends nothing for a skipped item,
while a handled item may append either a non-empty name or ``''``.  Positions
are native item indices only when the list length equals the exact item count.
The sensor rebuilds the exact ``item_index -> filename`` mapping from that list
and the null-safe effect-category call; this adapter consumes that mapping.
"""


_INSTALLED = False
_SAFE_DESC_SPACE = [None]
_SAFE_DESC_BY_WIRE = {}
_DESC_PENDING_CALLS = {}
_DESC_FAILURES = set()

try:
    _STRING_TYPES = (basestring,)
except NameError:
    _STRING_TYPES = (str,)


def reset_safe_descriptor_cache(space_id=None):
    """Forget descriptors from the previous battle space."""
    _SAFE_DESC_SPACE[0] = space_id
    _SAFE_DESC_BY_WIRE.clear()
    _retire_descriptor_calls()
    _DESC_FAILURES.clear()


def invalidate_safe_descriptor_chunk(chunk_id, retire_calls=False):
    """A reloaded chunk must prove the descriptor's native identity again."""
    for wire in list(_SAFE_DESC_BY_WIRE):
        if wire[0] == int(chunk_id):
            _SAFE_DESC_BY_WIRE.pop(wire, None)
    if retire_calls:
        _retire_descriptor_calls(int(chunk_id))


def _retire_descriptor_calls(chunk_id=None):
    for key, ticket in list(_DESC_PENDING_CALLS.items()):
        if chunk_id is not None and key[1] != chunk_id:
            continue
        _DESC_PENDING_CALLS.pop(key, None)
        callback = ticket.get('callback')
        if callback is not None:
            import BigWorld
            try:
                BigWorld.cancelCallback(callback)
            except Exception:
                pass  # Native teardown may already have retired this ID.


def inspect_destructible_desc(cache, space_id, chunk_id, item_index):
    """Inspect one streamed descriptor without the nullable scalar wrapper.

    The name is this exact native item's own resource, recovered from the
    possibly compacted chunk list through the sensor's alignment.  That is what
    the only two stock callers of ``getDestructibleDesc`` need: tree
    fracture/touchdown effects and the tree animator.  Non-tree identities keep
    their existing native paths and are deliberately not inferred here.
    ``pending`` covers the legal stream boundary and a bounded alignment still
    advancing across render ticks.  An item with no exact name, a terminally
    unaligned chunk and an unresolved descriptor are all definitively
    ``invalid`` rather than another item's resource.
    """
    from gui.mods.offline_lan_0922 import destructibles_sensor

    space_id = int(space_id)
    chunk_id = int(chunk_id)
    item_index = int(item_index)
    if _SAFE_DESC_SPACE[0] != space_id:
        reset_safe_descriptor_cache(space_id)
    key = (chunk_id, item_index)
    if destructibles_sensor.is_isolated_1513(chunk_id, item_index):
        _SAFE_DESC_BY_WIRE.pop(key, None)
        return 'invalid', None
    cached = _SAFE_DESC_BY_WIRE.get(key)
    if cached is not None:
        return 'resolved', cached
    status, filename = destructibles_sensor.resolve_native_item_name_1513(
        space_id, chunk_id, item_index)
    if status == 'pending':
        return 'pending', None
    if status != 'exact':
        return 'invalid', None
    if not isinstance(filename, _STRING_TYPES) or not filename:
        return 'invalid', None
    try:
        desc = cache.getDescByFilename(filename)
    except Exception as error:
        _SAFE_DESC_BY_WIRE.pop(key, None)
        destructibles_sensor.isolate_destructible_1513(
            'descriptor_cache', chunk_id, item_index, detail=error)
        return 'invalid', None
    if isinstance(desc, dict) and 'type' in desc:
        _SAFE_DESC_BY_WIRE[key] = desc
        return 'resolved', desc
    destructibles_sensor.isolate_destructible_1513(
        'tree_descriptor', chunk_id, item_index,
        detail='exact native filename has invalid descriptor payload=%s' %
            type(desc).__name__)
    return 'invalid', None


def resolve_destructible_desc(cache, space_id, chunk_id, item_index):
    """Return the safe descriptor, or ``None`` at pending/invalid boundaries."""
    return inspect_destructible_desc(
        cache, space_id, chunk_id, item_index)[1]


def _safe_get_destructible_desc(self, space_id, chunk_id, item_index):
    return resolve_destructible_desc(
        self, space_id, chunk_id, item_index)


def _safe_missing_descriptor_log(area_module, space_id, chunk_id, item_index):
    """Log a failed safe lookup without re-entering the crashing wrapper."""
    key = (int(space_id), int(chunk_id), int(item_index))
    if key in _DESC_FAILURES or len(_DESC_FAILURES) >= 32:
        return
    _DESC_FAILURES.add(key)
    from gui.mods.offline_lan_0922 import destructibles_sensor
    import json
    import sys
    status, desc = inspect_destructible_desc(
        area_module.g_cache, *key)
    manager = getattr(area_module, 'g_destructiblesManager', None)
    initial = getattr(manager, '_DestructiblesManager__destrInitialMatrices', {})
    loaded = getattr(manager, '_DestructiblesManager__loadedChunkIDs', {})
    tree = (destructibles_sensor._destructible_catalog or {}).get('tree_instances', {}).get(key[1:]) or {}
    row = dict(space=key[0], chunk=key[1], item=key[2], status=status,
        interface='ClientDestructiblesCache.getDestructibleDesc',
        native_count=loaded.get(key[1]) if isinstance(loaded, dict) else None,
        catalog_filename=tree.get('descriptor_filename'),
        isolated=destructibles_sensor.is_isolated_1513(key[1], key[2]),
        initial_matrix=isinstance(initial, dict) and (key[1], key[2]) in initial,
        descriptor_available=desc is not None)
    sys.stdout.write('[Offline LAN 0.9.22] TREE DESCRIPTOR ' + json.dumps(row) + '\n')
    logger = getattr(area_module, 'LOG_ERROR', None)
    if callable(logger):
        logger(
            'Destructible descriptor is not available, space: %s, '
            'chunk: %s, id: %s' %
            (space_id, chunk_id, item_index))


def _tree_descriptor_boundary(area, original, animation=False):
    """Retain a pending stock tree call until its exact descriptor is ready."""
    def call(owner, *args):
        manager = area.g_destructiblesManager
        space, chunk, item = (args[:3] if animation else
            (manager.getSpaceID(), args[0], args[1]))
        status, unused = inspect_destructible_desc(area.g_cache, space, chunk, item)
        if status != 'pending':
            return original(owner, *args)
        phase = 'animation' if animation else str(args[2])
        key = (int(space), int(chunk), int(item), id(owner), phase)
        if key in _DESC_PENDING_CALLS:
            return None
        if len(_DESC_PENDING_CALLS) >= 128:
            _safe_missing_descriptor_log(area, space, chunk, item)
            return None
        import BigWorld
        ticket = {'callback': None, 'attempts': 0}
        _DESC_PENDING_CALLS[key] = ticket
        def retry():
            if _DESC_PENDING_CALLS.get(key) is not ticket:
                return
            ticket['callback'] = None
            if (area.g_destructiblesManager is not manager or
                    manager.getSpaceID() != space or
                    getattr(BigWorld.player(), 'spaceID', None) != space):
                _DESC_PENDING_CALLS.pop(key, None)
                return
            status, unused = inspect_destructible_desc(area.g_cache, space, chunk, item)
            ticket['attempts'] += 1
            if status == 'pending' and ticket['attempts'] < 100:
                ticket['callback'] = BigWorld.callback(0.05, retry)
                return
            _DESC_PENDING_CALLS.pop(key, None)
            if status == 'resolved':
                original(owner, *args)
            else:
                _safe_missing_descriptor_log(area, space, chunk, item)
        ticket['callback'] = BigWorld.callback(0.05, retry)
        return None
    return call


def _chunk_identity_boundary(area_module, original):
    """Invalidate before onChunkLoad can synchronously replay queued damage."""
    def handle(manager, chunk_id, *args):
        if manager is getattr(area_module, 'g_destructiblesManager', None):
            from gui.mods.offline_lan_0922 import destructibles_sensor
            state = getattr(destructibles_sensor, 'g_offh_tree_state', None)
            if (isinstance(state, dict) and
                    state.get('spaceID') == manager.getSpaceID()):
                destructibles_sensor._drop_streamed_chunk_registry_1513(
                    state, chunk_id)
            else:
                destructibles_sensor._invalidate_chunk_native_names_1513(
                    chunk_id)
            destructibles_sensor.retire_chunk_identity_1513(chunk_id)
        return original(manager, chunk_id, *args)
    return handle


def _fragile_collision_boundary(area_module, original):
    """Observe the real native replacement, including delayed/replayed orders."""
    def handle(manager, space_id, chunk_id, item_index, *args, **kwargs):
        result = original(manager, space_id, chunk_id, item_index, *args, **kwargs)
        if (manager is getattr(area_module, 'g_destructiblesManager', None) and
                manager.getSpaceID() == space_id):
            from gui.mods.offline_lan_0922 import destructibles_sensor
            destructibles_sensor.note_native_fragile_replacement(
                space_id, chunk_id, item_index)
        return result
    return handle


def install(area_module=None, cache_module=None):
    global _INSTALLED
    if _INSTALLED:
        # ``BattleRuntime.start`` calls install once per round.  Space IDs are
        # engine-owned and need not be treated as a cross-round cache key.
        reset_safe_descriptor_cache()
        return True

    if area_module is None:
        import AreaDestructibles as area_module
    if cache_module is None:
        import DestructiblesCache as cache_module

    AreaDestructibles = area_module
    DestructiblesCache = cache_module

    moved_functions = {
        'chunkIDFromPosition': DestructiblesCache.chunkIDFromPosition,
        'encodeFallenTree': DestructiblesCache.encodeFallenTree,
        'encodeFallenColumn': DestructiblesCache.encodeFallenColumn,
        'encodeFragile': DestructiblesCache.encodeFragile,
        'encodeDestructibleModule':
            DestructiblesCache.encodeDestructibleModule,
    }
    moved_constants = {
        'DESTR_TYPE_TREE': DestructiblesCache.DESTR_TYPE_TREE,
        'DESTR_TYPE_FALLING_ATOM':
            DestructiblesCache.DESTR_TYPE_FALLING_ATOM,
        'DESTR_TYPE_FRAGILE': DestructiblesCache.DESTR_TYPE_FRAGILE,
        'DESTR_TYPE_STRUCTURE': DestructiblesCache.DESTR_TYPE_STRUCTURE,
        '_DAMAGE_TYPE_TREE': DestructiblesCache.DESTR_TYPE_TREE,
        '_DAMAGE_TYPE_COLUMN': DestructiblesCache.DESTR_TYPE_FALLING_ATOM,
        '_DAMAGE_TYPE_FRAGILE': DestructiblesCache.DESTR_TYPE_FRAGILE,
        '_DAMAGE_TYPE_MODULE': DestructiblesCache.DESTR_TYPE_STRUCTURE,
    }
    for name, value in moved_functions.items():
        if not hasattr(AreaDestructibles, name):
            setattr(AreaDestructibles, name, value)
    for name, value in moved_constants.items():
        if not hasattr(AreaDestructibles, name):
            setattr(AreaDestructibles, name, value)

    # Exact #1513 bytecode has only two consumers of this method, both in the
    # tree path.  Replacing the class method also covers the already-created
    # global cache instance.  Its stock error logger repeats the same unsafe
    # scalar lookup, so replace that exact companion boundary as well.
    cache_type = getattr(
        AreaDestructibles, 'ClientDestructiblesCache', None)
    if cache_type is not None:
        cache_type.getDestructibleDesc = _safe_get_destructible_desc
        if hasattr(AreaDestructibles, '_printErrDescNotAvailable'):
            AreaDestructibles._printErrDescNotAvailable = (
                lambda space_id, chunk_id, item_index:
                _safe_missing_descriptor_log(
                    AreaDestructibles, space_id, chunk_id, item_index))

    manager_type = getattr(AreaDestructibles, 'DestructiblesManager', None)
    if manager_type is not None:
        name = '_DestructiblesManager__launchTreeFallEffect'
        original = getattr(manager_type, name, None)
        if callable(original):
            setattr(manager_type, name, _tree_descriptor_boundary(AreaDestructibles, original))
        name = '_DestructiblesManager__setFragileDestroyed'
        original = getattr(manager_type, name, None)
        if callable(original):
            setattr(manager_type, name,
                    _fragile_collision_boundary(AreaDestructibles, original))
        for name in ('onChunkLoad', 'onChunkLoose'):
            original = getattr(manager_type, name, None)
            if callable(original):
                setattr(manager_type, name,
                        _chunk_identity_boundary(AreaDestructibles, original))

    animator_type = getattr(AreaDestructibles, 'DestructiblesAnimator', None)
    original = getattr(animator_type, 'showFallTree', None)
    if callable(original):
        animator_type.showFallTree = _tree_descriptor_boundary(AreaDestructibles, original, True)

    reset_safe_descriptor_cache()
    _INSTALLED = True
    return True
