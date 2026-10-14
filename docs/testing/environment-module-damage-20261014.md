# Environmental module damage trial

The user requested position-based fall damage to external/internal modules and
crew, without an ammo-rack exemption; fire damages internal modules only.
Existing projectile saving throws and ignition rules are unchanged. These
new environmental parameters are a reconstruction, not recovered #1513 server
rules. Existing vehicle fire HP rate (5% per second) and 10 second duration
remain unchanged pending the user's research.

## Rules and trial values

Fire subtracts 10 module HP per completed second from engine, fuel tank,
ammo rack, radio and turret ring. Tracks, gun/optics and crew are excluded.
The rate is absolute HP, so additional installed module durability is useful.
Batch fire catch-up stops at the first fatal tick; an ammo rack reaching zero
can detonate. The existing module-test bench still suppresses lethal results.

Landing uses only physical world-contact witnesses or confirmed ground
samples. Severe legacy landings probe the chassis footprint at that event,
not every driving frame. Suspension landings use their deepest sampled points.
A bounded inward five-segment shock fan nominates native external materials and the
adopted interior/crew layout. Unknown geometry nominates no fictional module.
Each module is damaged once per event using the nearest reached contact.

Trial shock depth is clamp((impact_speed - 10) * 0.6, 0.25, 6.0) metres.
The central contact-normal ray and four rays at 25 degrees spread inward.
Module HP loss is max(0, impact_speed - 10) * 25 / (1 + 0.25 * contact_distance).
A reached crew member is injured when this trial shock amount reaches 100.
There is no projectile saving throw, Deadeye bonus, ammo-rack immunity or
forced global track destruction. Fuel/engine impact loss does not add a new
ignition rule. Ammo depletion or complete crew loss can end the vehicle.

## Ownership and diagnostics

Player observations donate only bounded, deduplicated geometry contacts. The
server uses its installed pools and current critical state to apply losses,
commits a fresh damage lineage and sends critical data with the health event.
The reliable landing identity includes contacts: retries cannot apply damage
again, and a conflicting retry is rejected. Client queues retain each event's
contacts. Bot damage commits only after the final turret/world pose is accepted;
a rejected landing loses its witnesses before it can cause module damage.
Both actors share the pure loss implementation and fire tick law.

ENV MODULE CONTACT records physical witnesses, normals, trial shock reach,
geometry sources, reached names/weights and query errors. ENV MODULE DAMAGE
records actor kind/id, source, before/after HP and terminal consequences.
Native external tests plus adopted internal geometry are not a claim that the
PC client ships exact official internal collision shapes. Windows acceptance
must verify geometry, damage panel, death effects, repair and gameplay feel.

## Verification

Focused cases cover internal-only burning, position-dependent external,
internal and crew injury, no ammunition exemption, once-per-module contacts,
missing geometry, slow-frame fatal cutoff, actor parity, legacy Bot landing,
rejected turret poses, reliable queue preservation and duplicate/conflicting
server observations. Full runtime and CPython 2.7 compilation checks are run
against the final source tree before delivery. Rates require gameplay
calibration and must not be described as official figures.

Final engine-free reference validation: 2,022 tests across 12 suites passed;
181 client source files compiled under CPython 2.7. Runtime acceptance still
requires the supported Windows game client.

## Bridge-impact calibration (report 20261014-145051)

The T-34-2 landing at 14:49:40 had 16.7488301725 m/s impact speed and
263 canonical vehicle HP loss. Only the driver was nominated at 0.833336 m;
the previous 1.349766 m single segment and 1/(1+d) attenuation produced 73.62,
below the 100 crew threshold. No device contacts were recorded.

The revised bounded fan reaches 4.049298 m at that speed. The same driver
contact receives approximately 111.70 shock; additional devices are damaged
only if their actual native/adopted shapes intersect a fan segment. All
contacts are deduplicated to their strongest witness before one HP debit.
External query failures no longer suppress interior queries. Missing layout
and per-ray direction/distance are logged. Fire coefficients are unchanged.
This is a gameplay trial, not a reconstruction of official physics constants.

## Ammunition death-label repair

The pinned PostmortemPanel.__onShowVehicleMessageByCode reads
extra.deviceUserString. The own-death adapter previously sent None even
for negative-health ammunition detonation, leaving the module-name field
empty. Pass the native victim descriptor ammoBayHealth extra for both shot
and fire detonation. Ordinary deaths retain no module extra; no translated
text or font replacement is invented. The exact bytecode consumer was read,
and shot/fire/ordinary cause fixtures verify object identity at the call.

## Coefficient calibration (report 20261014-151604)

The five-ray propagation now reaches real track, turret ring, ammunition and
fuel contacts, but recorded module HP remained above the 50% yellow threshold.
At the user's request the impact coefficient increases from 20 to 40 HP per
excess m/s. Reach, attenuation, contact nomination, deduplication, body HP and
fire are unchanged. Recorded contact weights/pools exercise the yellow-state
transition without forcing a state or adding an ammo exemption. Earlier
bridge replay shock amounts above describe the previous coefficient.

## Requested coefficient 30 trial (report 20261014-153046)

At the user's request reduce the impact coefficient from 40 to 30. Contact
reach, attenuation, module/crew nomination and terminal ownership remain
unchanged. The two recorded heavy impacts compute approximately 215.81 and
202.58 ammo HP loss against a full 203 HP pool; the first still detonates,
and the second narrowly survives if the rack is full. This is calibration,
not ammunition immunity. The 151604 replay now yields yellow left track and
turret ring with hidden damage to the other reached devices. Fire is unchanged.

## Requested coefficient 25 trial

The user selected 25 for the next gameplay test. Contact fan, distance
attenuation, crew threshold, authority and fire remain unchanged. The heavy
153046 impacts would leave a full 203 HP ammunition rack at about 23.15 and
34.19 HP; stronger impacts or pre-existing damage can still detonate it.
The lower-speed 151604 contacts remain hidden damage at this coefficient.
