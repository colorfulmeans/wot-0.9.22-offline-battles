# Unknown-water and local progress follow-up

## Confirmed causes

Report `20261019-015957-93b692b13d2b`, installed build
`colorfulmeans-39150603913-1`, contains winter Himmelsdorf refusals labelled
`unplanned_water_shortcut` even though the shipped base graph and all nine
local meshes have no shallow-water cells. The corridor's missing routing
height returned an unknown hazard summary, which the water-only query treated
as positive water evidence. This is independent of the physical segment gate.

Both Python and C++ now inspect actual entered-cell water bits for that
water-only unknown case. The occupied start cell remains excluded, allowing
departure from an existing ford. Real water before or after missing support
still blocks the shortcut. Bounds, unknown fatal hazards, support and real
collision checks retain their existing contracts. Unknown is not a clear proof.

The driver retained a connector's best distance, but measured later distances
against a moving steering point within the existing two-metre identity radius.
Distances now use the retained fixed connector point. Real translation also
retains the alignment record instead of granting the same turn fresh credit.
New orders, actual destination arrival, command holds, the bounded connector
ledger, retry timing and route switching retain their existing behavior.

## Diagnostics and performance scope

Progress receipts include measured versus steering distance and the position,
old order, old connector, old credit age and new order at a reset. These expose
unconfirmed upper-order churn without changing order selection.

Bounded caches reuse immutable short-segment edge geometry (at most eight
edges per entry) and actual water flags. Mixed-mesh water keys retain exact
sub-cell endpoints. Dynamic failed-edge expiry and wreck penalties are read
fresh; no real collision, current support sample or physics time is skipped.
Counters distinguish geometry reuse, actual shallow queries and cache hits.

## Validation

- Reference suite: 97 files / 2,521 cases were exercised. The new mixed-mesh
  fixture initially lacked its mesh-index attribute; the completed fixture
  and the affected tests pass on the final sources.
- A retry-motion fixture incorrectly equated a captured replan origin with the
  position when the deferred search starts one physics tick later. It now
  checks the exact live position at request time and exact captured origin at
  search time. Whole-hull collision, departure from the finite dead end and
  arrival checks remain. A separate deferred-origin test documents this
  pre-existing production contract; no navigation behavior changed for it.
- One existing Airfield 24 FPS spawn-departure test remains failing: actors
  18 and 27 move 5.877 m and 11.344 m in the synthetic 60-second scene. These
  values match the unchanged baseline. Its assertion is retained.
- Final focused reference run: 35 cases pass, including unknown/real water,
  physical refusal, mixed-mesh keys, live penalty expiry, retained alignment,
  fixed distance reference and real dead-end retries.
- The five new root-cause checks fail against the previous production sources
  and pass with the fixes. Directed edge geometry matches the baseline over
  10,000 sampled segments; all 190 client modules compile under pinned Python
  2.7. This does not establish native-game escape success or an FPS gain.

Native shipping compilation, strict Python/C++ parity and final downloaded
package inspection are required before delivery. The one-missing-point enable /
all-five-restored disable support rule and navigation policy are unchanged.
