"""Foreground decisions over the local player's actual mounted equipment.

These priorities belong to the player controller. Bot difficulty, equipment
presets and policy changes cannot change a local player's kit selection.
Activation, cooldowns and damage remain the shared native equipment laws.
"""

REPAIR_PRIORITY = (
    ('gunHealth', 'destroyed'), ('engineHealth', 'destroyed'),
    ('turretRotatorHealth', 'destroyed'), ('ammoBayHealth', 'critical'),
    ('gunHealth', 'critical'), ('engineHealth', 'critical'),
    ('turretRotatorHealth', 'critical'), ('surveyingDeviceHealth', 'destroyed'),
    ('surveyingDeviceHealth', 'critical'), ('fuelTankHealth', 'critical'),
    ('radioHealth', 'destroyed'), ('radioHealth', 'critical'),
    ('leftTrackHealth', 'destroyed'), ('rightTrackHealth', 'destroyed'))
CREW_PRIORITY = ('loader1', 'loader2', 'gunner1', 'gunner2',
                 'driver', 'commander', 'radioman1', 'radioman2')


def select_targets(critical):
    """Return local damage, a repair target and a crew target without mutation."""
    critical = critical if isinstance(critical, dict) else {}
    states = dict((row['name'], row['state'])
                  for row in critical.get('devices', ())
                  if isinstance(row, dict) and 'name' in row and 'state' in row)
    states.update((name, 'destroyed') for name in critical.get('destroyed', ()))
    repair = next((name for name, severity in REPAIR_PRIORITY
                   if states.get(name) == severity), None)
    crew = next((name for name in CREW_PRIORITY
                 if name in critical.get('crew_ko', ())), None)
    return states, repair, crew
