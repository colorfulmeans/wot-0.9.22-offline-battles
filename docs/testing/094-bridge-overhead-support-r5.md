# Bridge-side support correction, physics-r5

Report: `wot-error-report-20260925-130449-b4e95f5db4b0.zip`.
Reported source: `d9ac97a3630783a01a134e0ee48dcb251f0ac803` (physics-r4).

## Observed cause

The captured suspension state disproves the idea that every remaining bridge
failure is a horizontal collision rejection. In `visible-client.log` line
1475 (13:02:19.636), a 0.009003-second update raises the actual centre of mass
from 2.538981 m to 3.640376 m while world motion is clear. Rigid contact 22 is
at y=-0.213 m before the solve, but its sampled support is the bridge surface
at y=1.109 m, more than 1.3 m above that corner.

The third attempt shows the same defect at line 2043 (13:04:11.358). Its
centre of mass rises 0.663936 m in 0.011047 seconds. Contact 13 is at
y=0.155 m but receives support at y=0.846 m. The tank subsequently settles
into the reported stuck pose. Neither frame reports invalid-pose rollback,
raised-support rejection, or a horizontal collision block.

These are centre-of-mass measurements, not the expected rise of the model
origin as a tank rotates upside down. The hard-contact solver is given an
invalid constraint: a corner already below the bridge must remain above it.
Its penetration correction then lifts and rotates the body. This produces
the appearance of forced righting without an explicit upright target.

## Change

Remove the rigid-contact sampling ceiling derived from the model origin and
the previous support plane, including the now-unused reference-plane data.
Use each rigid corner's actual current world height for its upper bound.
Retain the downward angular and gravitational sweep so high-speed landings
can acquire ground before the corner passes through it. A rigid corner's
previous and current world positions also define a short native collision
segment. Only an actual inward hit on an upward face may extend the final
column to that surface; the endpoint must independently confirm the surface.
This preserves a roof sliding into a slope without borrowing an unrelated
bridge layer. The shared rule is used by player, Bot and shoved-wreck samplers.

This changes contact acquisition, not gravity, suspension force constants,
angular targets, Bot steering, or the physical collision response. The
world-collision and mass-contact fixes from earlier revisions remain.

## Regression boundary

The compact fixture contains the two captured poses, velocities, contact
layouts, mass centres and support heights. Tests feed those observed columns
through both player and Bot samplers, reject the witnessed overhead contacts,
and then verify that the unchanged solver no longer produces the large
upward jump. Unrecorded spring coefficients use the existing test descriptor;
this is not a replay of the entire native map or exact vehicle descriptor.

Additional coverage retains 45 m/s upside-down landings at 120, 30 and 10 Hz,
including ground penetration checks, and horizontal roof contact on a slope.
Existing bridge departure, wall,
rollover and suspension tests remain part of the dedicated build gate.

Crew damage also no longer starts every battle's first landing at roster
index zero. The authoritative producer samples actual healthy seats once,
and replay uses the committed result. The earlier reconstructed severity
budget is unchanged. See `094-world-impact-damage-audit.md` for its limits:
internal-module falling damage remains unimplemented; the current device
producer covers the two tracks only.

The ordinary gameplay-followup gate already has seven failures and two
errors at the unmodified r4 commit, in the reverted Bot aiming/targeting
behavior. They are separate from this physics change and are not hidden by
lowering assertions. Native Windows 0.9.22 gameplay remains the final
acceptance check; this build is a test package, not a release.
