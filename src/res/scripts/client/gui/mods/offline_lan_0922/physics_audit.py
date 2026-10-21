"""Observational native-water and support evidence; never an authority source."""
from __future__ import division

import math


def motion_episode(previous, position, now, command, driver):
    """Join bounded stall receipts across combat/local-action owner changes.

    Eight metres is a diagnostic pocket, not a driver arrival or retry rule.
    Count only observed receipts; do not claim unobserved travel between them.
    """
    row = dict(previous or {})
    departed = None
    if row and math.hypot(position[0]-row['origin'][0], position[2]-row['origin'][2]) > 8.:
        departed = dict(origin=row['origin'], started=row['started'],
                        observed_until=row['observed_at'], samples=row['samples'],
                        terminal='left_diagnostic_pocket')
        row = {}
    if not row:
        row = dict(scope='diagnostic_only', origin=tuple(position), started=now,
                   samples=0, transitions=[], dropped=0)
    row['transitions'] = list(row['transitions'])
    progress = driver.get('objective_progress') or {}
    observation = dict(at=now, position=tuple(position),
        mode=command.get('combat_mode'), local_target=command.get('move_position'),
        recovery_count=driver.get('recovery_count'),
        credit_reason=progress.get('credit_reason'),
        credit_age=progress.get('credit_age_seconds'),
        progress_reset=progress.get('reset_receipt'),
        fire_allowed=command.get('fire_allowed'))
    row['transitions'].append(observation)
    if len(row['transitions']) > 32:
        row['transitions'].pop(0)
        row['dropped'] += 1
    row.update(observed_at=now, age=now-row['started'], samples=row['samples']+1,
        displacement=math.hypot(position[0]-row['origin'][0], position[2]-row['origin'][2]))
    if departed is not None:
        row['previous_terminal'] = departed
    return row


def water_context(bigworld, avatar, point, vector, missed=False, entity_id=None):
    """Compare native query environments at the already admitted log cadence.

    Extra rays run only after a miss. Their results are diagnostic values,
    never replacement water heights or drowning verdicts.
    """
    row = dict(scope='diagnostic_only', errors=[])
    for name, owner, field in (
            ('avatar_space', avatar, 'spaceID'),):
        try:
            row[name] = int(getattr(owner, field))
        except Exception as error:
            row['errors'].append(name + ':' + type(error).__name__)
    try:
        player = bigworld.player()
        row['engine_player'] = dict(id=int(player.id), space=int(player.spaceID),
            position=tuple(float(player.position[i]) for i in range(3)))
    except Exception as error:
        row['errors'].append('engine_player:' + type(error).__name__)
    if entity_id is not None:
        try:
            entity = bigworld.entity(int(entity_id))
            row['sample_entity'] = dict(id=int(entity_id), space=int(entity.spaceID),
                position=tuple(float(entity.position[i]) for i in range(3)))
        except Exception as error:
            row['errors'].append('sample_entity:' + type(error).__name__)
    try:
        camera = bigworld.camera()
        row['camera_position'] = tuple(float(camera.position[i]) for i in range(3))
    except Exception as error:
        row['errors'].append('camera:' + type(error).__name__)
    try:
        row['graphics'] = dict((str(item[0]), int(item[1]))
            for item in bigworld.graphicsSettings()
            if item[0] in ('WATER_QUALITY', 'RENDER_PIPELINE', 'FAR_PLANE',
                           'TERRAIN_QUALITY', 'GRAPHICS_API'))
    except Exception as error:
        row['errors'].append('graphics:' + type(error).__name__)
    if missed:
        x, y, z = map(float, point)
        row['probes'] = []
        for name, start, end in (
                ('same_segment_reversed', (x, y-5., z), (x, y+20., z)),
                ('extended_downward', (x, y+200., z), (x, y-200., z))):
            probe = dict(name=name, start=start, end=end, flag=False)
            try:
                probe['raw_distance'] = bigworld.wg_collideWater(vector(start), vector(end), False)
                probe['status'] = 'returned'
            except Exception as error:
                probe.update(status='exception', error=type(error).__name__ + ':' + str(error)[:160])
            row['probes'].append(probe)
    return row
