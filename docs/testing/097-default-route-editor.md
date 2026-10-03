# Editable default routes and Airfield restoration

The Airfield lane rewrite in `0576e4dc` moved previously correct nodes and
introduced unwanted ridge crossings. Restore both teams' route objects exactly
from `31d8c001`; do not interpret the user's red drawing as another replacement
road design. Remove the broad Airfield corridor generator. Retain the reviewed
ground links, route-admission performance fix and destroyed-skin ownership fix.

The editor now edits built-in geometry directly, including moving, inserting
and deleting nodes. Each route still fits the existing 1..16-point protocol.
Per-map, per-team overrides remain separate from custom route allocation rules;
route IDs, capacities, risks and class/role affinities are retained. Original
graph resources and editor caches remain immutable. Saving and applying affects
the next round. Reset route and undo/redo restore earlier geometry.

The worker validates each override against the existing bounded navigation
graph before creating its director. Unusable or disconnected edits independently
fall back to their original routes with diagnostics. Assigned routes reach the
ordinary manifest, so the host's route catalog and subsequent lane switching
use the same coordinates. No terrain, collision or native firing veto is waived.

## Follow-up: report 20261003-141828

The installed package is build 58. Four of the six global Airfield edits were
rejected as waypoint_unusable; only T1 central and T2 north were admitted.
Manual radius-16 SPG zones admitted one vehicle per team, with the other two
falling back because no reachable unreserved parking footprint fit.

Worker PERF capture 3 reports 2.04 FPS, 490.28 ms per rendered callback and
472.705 ms in Python. The largest detailed capture-1 self costs include
destructible intersection SAT (1362.5 ms / 14 detailed callbacks), motion world
queries, destructible motion and ground support. This is simulation work;
the report does not establish an Internet latency fault. Inline SAT projections
remove generator/call overhead while retaining every sweep generator, axis,
projection order and tolerance. A differential check of 30,000 seeded pairs
(3/4 generators, zero/tiny/ordinary/large extents) matches the parent exactly;
the local Python 3 benchmark is 1.53x faster for this function only. It does not
prove a native Windows FPS or ping improvement.

Short clear route corners now align before forward drive when the target is
within two hull half-lengths (minimum 8 m) and the heading error exceeds 0.45
radians. Recovery and obstacle detours retain their checked escape behaviour.
Directly observed proximity threats get lane-queue priority even before target
acquisition; the same bounded probe budget and native/static/final-fire vetoes
remain. Object 704 was shot six times at close range without selecting a target;
the existing report does not distinguish absent direct contact from a negative
native lane receipt. New stall records include proximity contact visibility and
lane receipts. Native acceptance of this acquisition change remains pending.

Default edits are now scoped by class. The initial lane allocation still uses
the original lane catalog; the worker then replaces geometry for the matching
class, advertises a distinct class-route identity and excludes that class from
the corresponding global host-catalog entry. Invalid scoped edits do not remove
the original class affinity. Default waits are read only when the actual
manifest geometry matches the admitted edit. Restored class routes, shared
route reversal, independent unchecking, class isolation and arrival timers have
focused tests, including actual Windows Tk events.

The preceding verification below describes build 58's baseline, including its
known unrelated historical failures; it is not a claim about native acceptance
of the follow-up.

## Build 58 baseline verification

- All 41 map registries match the shipped default route IDs and admit their
  original geometry through the editing contract.
- Real Windows Tk events cover default-node drag, insertion, deletion,
  undo/redo, persistence, apply, reopen and route reset without cache mutation.
- The launcher suite passes 906 cases, with 14 platform/optional skips.
- The dedicated Bot CI commands pass 714 cases, with one optional skip.
- A broader historical Bot run executes 692 cases: 59 failures, 18 errors,
  one skip. The exact parent snapshot `0576e4dc` executes the same 686 older
  cases with identical 59 failures and 18 errors; all 77 failure identities
  match and no new failure is introduced. Many assertions still describe
  suspension and crew effects from before the requested Bot rollback.
- Package/build verification and native-game acceptance remain separate.
  Tk and plain-data checks do not prove driving through the edited roads in
  the exact Chinese HD #1513 Windows client.
