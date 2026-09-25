# World-impact damage evidence, 2026-09-24

## Report and observed result

The `051910` report identifies build
`colorfulmeans-v094-gameplay-fixes-36037035573-1`, commit
`107084faa92cfec7df9d6a3986103b5ff5d4511a`, on Chinese HD
`0.9.22.0.1 #1513`. The player is the KV-5 on `37_caucasus`.

The server accepted environment damage of 359 HP at 05:13:45 and 295 HP at
05:15:50. The visible client subsequently reports positions near y=-14.3
and y=-14.4. It also accepted player-to-Bot ramming damage of 642 HP at
05:16:34 and 767 HP at 05:18:57, with reciprocal player damage of 126 and
247 HP. These observations establish that falling and some live-vehicle
collisions already reach authoritative HP. They do not establish that every
contact is accepted, nor that nonfatal impacts damage devices or crew.

The report contains no device-HP or per-track impact observation at either
landing. Its final all-crew knockout follows the fatal ramming event, not
either earlier landing.

## Local implementation and history

At the reported `107084fa` baseline, player `_apply_fall_damage` queued only
an impact speed. The server validated
the sequenced `landing_observation`, computes `vehicle_physics.fall_damage`,
then `_commit_player_environment_damage` committed HP. There was no device or
crew damage proposal in that chain. `_apply_bot_fall_damage` likewise changed
HP and applied the terminal all-device/crew state only if the vehicle died.

The same HP-only behavior is present in `v0.9.0`, `v0.9.2`, and the initial
public implementation `1bb3070d`. The later Bot rollback did not remove a
nonfatal landing critical-damage producer from those functions. The retained
linear `fall_damage` rule is a project reconstruction, not an extracted retail
server formula.

One independent transport defect is fixed by this change: `_critical_payload`
previously normalized `world_collision` critical events to `shot` because its
cause allowlist omitted world collision. The presentation consumer already
distinguishes the official world-collision device and crew notifications.
The cause tests preserve that distinction through validation and exercise
the stock notification dispatch. The cause repair alone does not create
nonfatal landing damage; the reconstruction below adds track and crew producers.

## Exact #1513 client evidence

The supplied `scripts.pkg` was inspected as CPython 2.7 bytecode, not treated
as a source distribution for the retail server:

- `scripts/client/Vehicle.pyc`, `Vehicle.onStaticCollision`, takes `energy`,
  `point`, `normal`, `miscFlags`, `damageHull`, `damageLeftTrack`,
  `damageRightTrack`, and `destrEffectIdx`. It selects the larger left/right
  track damage when the track flag is set, otherwise hull damage, and scales
  that value by 100 for collision effects. It does not calculate device HP,
  crew injuries, or authoritative hull HP.
- `scripts/client/Avatar.pyc`, `PlayerAvatar.showVehicleDamageInfo`, consumes
  the supplied damage-code and extra indices. It shows the notification and
  sound; it is not the damage producer.
- `scripts/common/constants.pyc` defines
  `DEVICE_CRITICAL_AT_WORLD_COLLISION`,
  `DEVICE_DESTROYED_AT_WORLD_COLLISION`,
  `TANKMAN_HIT_AT_WORLD_COLLISION`, `DEATH_FROM_WORLD_COLLISION`, and
  `DEATH_FROM_INACTIVE_CREW_AT_WORLD_COLLISION`.
- `scripts/common/physics_shared.pyc` configures physical bodies and
  suspension. It does not supply a collision-to-device/crew damage formula.
- `scripts/item_defs/vehicles/common/optional_devices.xml` gives enhanced
  suspension equipment `vehicleByChassisDamageFactor=0.5`.
  `items.artefacts.EnhancedSuspension._readConfig` reads it and
  `updateVehicleDescrAttrs` multiplies the vehicle's corresponding misc
  attribute. `items.vehicles.VehicleDescriptor.__updateAttributes`
  initializes the attribute. No damage consumer for that attribute is
  included in the available client Python package.

The collision-effect velocity thresholds in `vehicle.xml` are effect
selection data. They do not establish damage thresholds or coefficients.

## Historical official sources and limits

- [8.4 public test](https://worldoftanks.com/en/news/general-news/84-public-test/)
  records a fix for a missing voice notification when a fall damages a track.
- [8.4 update notes](https://worldoftanks.com/en/news/general-news/84-update-notes/)
  record a fix for falling damage incorrectly reaching a nonexistent turret
  on tank destroyers and SPGs.
- [8.8 public test](https://worldoftanks.com/en/news/general-news/88-public-test/)
  records enhanced-torsion protection for the chassis and the vehicle damage
  transmitted through it during ramming and falling.
- [2015 physics experiment](https://worldoftanks.com/en/news/general-news/physics-experiment-pt/)
  describes improved suspension survival with even weight distribution and
  moving tracks during landing. It describes a test, not the exact #1513
  released damage implementation.
- [8.0 public test notes](https://worldoftanks.com/en/news/general-news/80-public-test-notes/)
  record changes to ramming/falling damage and removal of ignition caused by
  falling onto another vehicle.

These sources support contact-dependent suspension damage and distinct world
collision feedback. They do not specify how to divide impulse between
tracks, convert it into module HP, select internal modules or crew, or apply
injury probabilities. The existence of a notification code is not proof that
every fall should injure crew. The approximation below does not borrow
projectile/HE saving throws or randomly destroy internal devices. A complete
retail-equivalent producer still needs server-side evidence or measured #1513
impact observations.

## Bounded reconstruction implemented after the audit

The new `impact_damage` model deliberately reuses the existing vehicle-HP
fall-damage budget. It does not add a new kinetic-energy conversion constant:
`budget = fall_damage(vehicle.maxHealth, normal_impact_speed)`. Each contacted
track independently loses `min(fitted_track_max_hp, budget * track_share)`.
The original hull HP loss is committed once and is unchanged by this module
calculation. Track maximum HP comes from the existing descriptor/profile,
including its already applied chassis-health modifiers.

The suspension records positive spring force times substep duration and
positive hard-contact velocity impulses, in consistent impulse units. These
are measurements of the existing solver, not new forces. They accumulate
through the landing step and are partitioned into left track, right track,
and hull/belly. The track shares use the sum of all three channels, so hull
load is never redistributed to tracks. A newly touched final-step contact
which has not yet applied a force gets an explicitly approximate impulse
from its effective mass and closing velocity. The Jacobian is the current
solver's vertical constraint, not a complete rigid-body surface-normal
solution. Zero-duration settling reports no damaging load.

Only the existing airborne-to-supported landing gate submits these shares.
Ordinary supported suspension compression cannot invoke the damage path.
An absent contact observation or unproved legacy contact keeps the existing
HP-only behavior. A measured hull-only landing has zero track shares; it
does not assume both tracks took the load, but can injure crew under the
severity rule below. This scope covers the active ten-spring solver, not
the hydraulic suspension path excluded from that trial.

The player sends speed and contact shares through the existing sequenced
landing observation. The server computes both HP and track loss and merges
it against its current frozen device profile and canonical critical state.
It opens a new critical revision, so a pre-impact automatic repair checkpoint
cannot erase the damage. Replaying an accepted landing returns its receipt
without applying HP or module loss again. Bots use the same budget and track
HP law before publishing their existing canonical critical state. A new hit
on a destroyed track resets incomplete repair progress under the same
`device_damage.damaged_hp` law as server-admitted projectile damage.

## Crew completion, 2026-09-25

The `110942` follow-up requests nonfatal falling crew injuries explicitly.
The preceding track-only producer could never generate those injuries: its
only crew change was the complete terminal knockout when hull HP reached
zero. The new shared `impact_damage.crew_casualties` fills that missing path
with an explicit deterministic project reconstruction:

`casualty_budget = floor(fall_damage * actual_crew_count / vehicle_max_health)`.

The denominator is full vehicle HP, not remaining HP. This reuses the existing
fall severity without adding a new impact constant or crew HP pool. Rounding
down gives no crew damage to small falls; subthreshold landings do not build
up hidden injury points. The actual admitted roster supplies individual seat
names, including numbered loaders and gunners and seats covering several
roles. No generic five-person fallback is used. Starting at the accepted
impact ordinal, roster order selects at most that many still-active members;
already injured members do not spend the budget and are never revived.
Rotation is a reproducible tie-break, not a claim about the impacted
compartment. Role impairment and medkit recovery use existing critical-state
mechanisms.

For example, a 359 HP fall on a full-HP scale of 1780 with six crew produces
one casualty; the same severity with two crew produces none. This is a
conservative discrete severity model, not evidence of those retail results.
The model does not reproduce retail collision injury probability, compartment
geometry, or equipment protection. Those remain calibration limits, rather
than a reason to leave the requested nonfatal injury path empty.

The human server computes casualties only after validating the sequenced
physical observation and merges them over canonical crew and repair state.
Unknown contact (`None`) and measured hull contact (`[0, 0]`) retain distinct
receipt identities. Replay cannot injure twice, including after a medkit
restores the casualty. The Bot worker uses the same shared law and preserves
the admitted roster. All-crew knockout disables either actor through the
world-collision death path while retaining remaining hull HP, as for existing
crew-knockout deaths; it does not fabricate additional hull damage.

Focused tests cover full-HP severity, no-contact and safe-speed exclusions,
numbered seats, already injured crew, combined roles, human/Bot parity,
canonical revision barriers, receipt identity, medkit use and replay, and
positive-HP all-crew deaths. Native Windows landing behavior and the exact
world-collision crew notification remain acceptance boundaries.

This change adds no internal-device selection, fire, or ammo-rack detonation.
The enhanced-suspension `vehicleByChassisDamageFactor` still has no
collision-damage consumer here; this change does not claim full retail
equipment protection.
