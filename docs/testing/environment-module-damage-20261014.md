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
A bounded inward shock segment nominates native external materials and the
adopted interior/crew layout. Unknown geometry nominates no fictional module.
Each module is damaged once per event using the nearest reached contact.

Trial shock depth is clamp((impact_speed - 10) * 0.2, 0.25, 3.0) metres.
Module HP loss is max(0, impact_speed - 10) * 20 / (1 + contact_distance).
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
