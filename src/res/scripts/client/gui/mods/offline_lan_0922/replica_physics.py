"""Read-only physical parameters for a published remote vehicle fitting.

This is not a controller and does not resolve Bot skill, tactics or routes.
The installed descriptor and its published crew/directive context are the
same facts used for native presentation; prediction owns no remote pose.
"""

from . import loadout, vehicle_fitting_context, vehicle_physics


def contact_params(state, descriptor):
    if descriptor is None:
        return None
    fitting = vehicle_fitting_context.context(descriptor)
    if fitting is not None:
        factors = vehicle_fitting_context.native_factors(descriptor)
    else:
        published = state.get('fitting') or {}
        level = published.get('crew_level')
        factors = loadout.attribute_factors(descriptor, crew=None, crew_level=level)
        if factors is None and level is not None:
            # Match the exact-client native default-crew compatibility path;
            # never manufacture force coefficients or query a Bot runtime.
            factors = loadout.attribute_factors(descriptor, crew=None)
        if factors is None:
            raise RuntimeError('remote vehicle native crew factors are unavailable')
    return vehicle_physics.derive_params(descriptor, factors=factors)
