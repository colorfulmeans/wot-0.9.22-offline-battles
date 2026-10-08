# Incoming Bot/player RAM evidence, test141

Report `wot-error-report-20261008-204235-f7e851eca838.zip` identifies test140.
At 20:41:46 the visible client records STB-1 (Bot22, 37.4 t) contacting the
stationary 113 (45.4 t): physical peer velocity is approximately 15.8 m/s and
local contact response is (-1.7403,-6.9284) m/s. There is no corresponding RAM
proof or server RAM transaction. The log does not expose that frame's HP
velocity, so it cannot establish its exact early-exit branch.

A code-level reproduction confirms the asymmetry risk: the same physical
contact imparts about 7.14 m/s to the player but does not queue an HP proof when
Bot history has zero displacement velocity. A nonzero incoming velocity queues
the proof. Both directions already settle through the existing server ledger
when given valid immutable evidence; the server does not prohibit Bot damage.

## Change

The existing translation SAT sweep can return its contacted player IDs without
another collision query. Before reciprocal momentum response, the worker
retains the real incoming velocity, first-contact Bot/player poses and the
player's accepted motion for each enemy-player episode. Rows bind player ID,
sequence and sample time. A harmless small touch may be superseded by stronger
actual incoming motion before admission; consumed player receipts remain
idempotent. No predicted motor velocity is admitted for damage.

Ordinary periodic Bot rows carry a bounded optional fixed-point collection.
An empty collection costs one count integer; one contact adds 21 integers.
The accepted server pose archive freezes it and presentation selects evidence
only at or before its actual timestamp. The contact proof uses the original
pair's matrices rather than a later shoved pose, retains native paired armour
verification, and binds its sequence, both poses and velocities back to the
server's canonical archived episode. Unsupported native geometry retains the
existing two-attempt proof limit and does not re-query that unchanged witness
on every render frame. Separation, death and round lifecycle retire evidence.

Existing HP formulas, coefficient, friendly exclusion, wreck exclusion,
physical momentum, damage ownership and receipt deduplication remain. No
terrain samples, map scan or extra suspension solver is introduced. Bounded
contact logs expose the source sequence and incoming velocity for playtesting.

## Validation

Added regressions cover incoming capture after a swept stop, continuing contact,
separation/re-impact, death, friends and vertical separation, fixed-point
transport, immutable archive and future evidence exclusion, canonical peer/
sequence/pose/velocity binding, actual renderer projection, stationary Bot vs
moving player, Bot vs stationary player, original geometry after presentation
shove and duplicate server settlement. Python 2.7 compilation covers all 164
client modules. Existing native plate, codec, player-input and server ledger
checks remain in the test suite.

Fresh-interpreter discovery ran 7,219 cases across 267 files: 262 files passed;
the same five baseline files retain 13 failing subcases (Pilsen doorway,
Airfield/Cliff departures, Canada railway clearance and wreck pushing), with
zero errors. The 14 new incoming-motion regressions pass. These retained
failures are not represented as fixed or suppressed by this patch.

A 29-body pure-Python guard benchmark on this host measured median per-call
0.7033 -> 0.7256 ms without contact and 1.5465 -> 1.6245 ms with contact in the
initial witness implementation. Recording the complete geometry adds only
contact-side scalar copies; no native query is added. This measures that helper,
not native game frame time or ping. Native STB-1/113 impact, armour interaction
and frame pacing still require a test141 gameplay report.
