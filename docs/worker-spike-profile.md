# Worker spike timing test

Launch the extracted Windows test package with `START_SPIKE_PROFILE.bat`.
The inherited `WOT_OFFLINE_SPIKE_PROFILE=1` flag enables only the hidden
worker's detailed observer. Opening the executable normally keeps the ordinary
profiling policy. Close an existing launcher before selecting either mode.

The observer measures every control callback, including catch-up slices, for
up to 64 consecutive 30-second capture windows (32 minutes). Each capture
retains all tracked Bot actor summaries; slow-frame traces retain the six
most expensive actor slices and their eight most expensive stages. Global
stage totals, explicit actor phases, native calls/callbacks, and queue waits
reuse the existing bounded ledgers. Shared asynchronous navigation servicing
has its own `bot.navigation_service` scope outside the actor loops.

Driving preparation, commands, target refresh, weapon preparation, motion
planning, integration, aim/fire, and cover preparation have separate actor
phases. Nested timings are inclusive; use self time to avoid double counting.
The observer does not change Bot decisions, stepping, or work budgets.
Detailed timings and periodic JSON emission add overhead: use this package
to identify causes, not to establish an uninstrumented performance baseline.

After a representative battle, export the launcher's report ZIP. The hidden
worker log's `combat_trace`, `combat_summary`, and `combat_checkpoint` records
contain the per-frame and per-Bot timing evidence. A checkpoint overlaps its
capture summary and must not be added to it.

## Parking-distance spike correction

Report `20261009-183832` records 170--197 ms single-SPG command stalls.
Deployment/fire-position retries synchronously reuse whole-grid shortest
distance selection. `_Graph.distances` now calls `parking_distances` in the
matching native bridge. The Python reference remains available for conformance
and unsupported inputs. The native calculation retains directed link bits,
direction order, destination usability (missing height, hazard mask 15,
inclusive arena bounds), cell-scaled orthogonal/diagonal edge lengths, and
distance/index heap ordering. It does not adopt normal navigation's slope,
turn, smoothing, or asynchronous route laws. Candidate generation, occupancy,
ranking, selected points and actual movement/fire validation remain Python
owned and unchanged. No map/actor cache or stale reachability evidence is added.

CPython 2.7.18 host checks compare 30 irregular directed grids and all 10,628
reachable nodes from three positions on the report map. Complete catalog
allocation, single-actor retry selection and seeded selection match the
reference exactly. In the host check the Python flood takes 150--154 ms and
the complete native bridge plus Python result conversion takes 2.1--2.4 ms.
These are isolated host timings, not a measured in-game frame improvement.
The diagnostic entry also measures `parking.position_order`, retry operations,
catalog/manual assignment and `parking.distances`; the native ledger separates
input parsing, calculation and result packing. Exact-client acceptance should
confirm whether these scopes remove the observed command spikes.
