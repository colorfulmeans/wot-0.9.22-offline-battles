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

## Report 20261003-155309 / build 59 follow-up

All six Airfield global edits were admitted. There are no class-scoped edits,
manual parking zones or explicit node waits in the report. Airfield is outside
the two-map sourced SPG catalog: all six guns use the host's rear-route parking
fallback. Showing the complete regular lane for SPGs therefore misrepresented
their actual deployment. The editor now previews parking anchors and supports
optional parking itineraries with red parking and pink movement markers.

The user confirms that Object 704 acquired and fought the nearby player in this
round. Its remaining observation concerns spawn egress alongside AT 15, not
target acquisition. Native traces show short avoidance goals traversed with
full forward drive (704 at 15:46:02), and navigation waits that still turn toward
a distant strategic heading (CDC at 15:47:35/38, with native rotation denied).
Short avoidance goals now align before translation; a pending navigation wait
keeps its steering stationary. The existing bounded checked escape still runs
after the wait timeout. Slow uphill progress credits the driver's local stuck
clock while a separate best-distance clock continues to bound oscillation.
No drive power, terrain resistance, ground data or physical collision laws are
changed. The edited routes in this report remain user-owned.

Worker live windows 3/4 average 267.407/291.035 ms in Python, with Bot update
263.376/285.894 ms. Prewarm is only 0.299/0.330 ms; synchronization and presentation
are also small. Detailed capture 1 has 840.665 ms of destructible intersection
self time across 26 detailed frames, plus motion world, support and native
physics work. Capture 2 additionally has 677.977 ms of search-batch self work
across 25 detailed frames. The bottleneck is battle simulation, not evidence of
Internet latency or a profile initialization pause. Later live window 10 is
78.670 ms in Python / 75.635 ms in Bot update; window 11 has already returned to
prebattle and is 16.880 ms in Python. The final low ping cannot be extrapolated
to a healthy full opening lineup. No native performance improvement is claimed.

Before packaging, 722 dedicated Bot regression cases pass (one optional skip),
and 35 actual Windows Tk / localization / itinerary integration cases pass.
The expanded executable editor smoke checks Airfield parking previews and the
relocated symmetry control. Package inspection and the clean Windows CI result
are recorded in the PR handoff. Local full-launcher account-mutating tests are
blocked by the user's running WoT process, which is not interrupted for tests.
The unrelated historical SPG target-lease assertion remains a known baseline
failure in full Tests; the dedicated gameplay gate stays separate.


## October 5, 20:36 parked TD acquisition

Report 20261005-203602 uses launcher build 98. Tortoise waits with no selected
target for roughly 50 seconds while reported enemies are 355-424 m away. Its
450 m firing envelope was restored, but its short preferred fighting distance
still leaves ordinary acquisition at 340 m. Later target acquisition produces
checked hull turning and six shots during the same wait; this is not evidence
of a physical parking yaw lock. The early logs do not establish continuous
native lane proof for every enemy, so distance alone is not a complete proof
of the whole observed delay.

The final user-directed policy unifies all TDs with the existing light-armour
sniper profile, rather than changing target-acquisition rules only at authored
parking places. The interim parking-specific acquisition extension is removed.
The same unchanged acquisition formula now uses 255 m preferred distance for
every TD, during travel, parking approach, waiting and queueing. The end-to-end
regression acquires a proved 400 m target with the production armoured TD
profile, keeps translation at zero, and drives limited-traverse hull laying.
Loss of lane proof disables fire. These deterministic checks do not replace
native gameplay acceptance; packaging is paused at the user's request.

TD armour no longer changes brawler/sniper preferences or preferred distance.
Every TD retains base brawler 0.32, sniper 0.92, preferred distance 255 m and
firing range 450 m. Descriptor speed still adjusts mobility preferences, and
actual armour remains in the profile for physical/target data. Both TD armour
categories use the same installed-gun aiming/collision rules. Other classes
retain their existing 120 mm armour preference adjustment (+0.18 brawler,
-0.08 sniper). Other profile preferred/fire ranges are HT 72/260, MT 135/340,
LT 175/320 m. Ordinary
visible acquisition is max(340, min(560, preferred*2 + mobility*300)); remembered
contact acquisition is max(240, min(420, preferred*1.5 + mobility*210)), where
mobility is max(scout, flanker). These are AI policy distances, not spotting
or projectile physics limits.

## October 3, 17:10 report and editor simplification

Report 20261003-171033 uses build 61 and contains one current Airfield worker
round, despite the user observing two matches. It cannot independently identify
the other match. Live windows 3/4 have 261.025/269.456 ms frame gaps and
245.187/252.514 ms Bot updates; prewarm is only 0.323/0.356 ms. The 30-second
capture contains 9,605 Bot physics resolver calls, 37,854 native motion rays,
28,878 native motion ground queries and 21,660 navigation rays. Of 4,296 motion
world fallback checks, 3,378 are classified as turning. Cumulative physics
resolver self time is 11,176.956 ms, followed by slice and planner/driver work.
This identifies repeated simulation and collision work during the crowded
opening; it is not a network fault diagnosis or evidence that deleting route
profiles fixes ping. Later live windows 6/7 still take 95.498/90.820 ms in Bot
updates. No native performance improvement is claimed by this UI change.

The editor now starts at All classes with symmetry enabled. SPG editing retains
parking regions only: movement points, waits and scripted SPG routes are removed
from the editor, assignment and position schema. The user's experimental local
active/draft profiles and their backups were explicitly authorized for deletion;
account, garage and save data are outside that cleanup scope. No configuration
migration or silent itinerary-ignoring compatibility path is introduced.

## Follow-up: report 20261005-212211, active slope bend ownership

Build 100's Pz.58 repeatedly changed its local index from 1 to 0 at the
El Halluf south slope lip. The route and strategic goal did not change.
Projection onto a bend's outgoing edge incorrectly treated a hull slightly
beside its setup as having passed the active target. The next segment was
unproved, so reacquiring the same cached join reset progress to an earlier
vertex. Keep the selected target until the ordinary arrival test advances it;
retain projection-based forward joins when reacquiring a different path.

Replay the reported poses and local path against the real El Halluf bake with
unavailable ground failing closed. Thirty alternating poses retain index 1,
reaching its setup advances to index 2, and the warmed replay adds no ground
queries. New walls, edge penalties and unplanned shallow water still reject
that target. The U-wall lifecycle replay has the same physical trajectory and
511-step arrival as the parent, without its redundant later join job. Correct
the old test's misleading "any job pending at the exit" assertion: that job
was not the original plan. Pending phase, physical exit, collision-free steps,
completion and arrival are now checked independently.

Slope support, hull pose, vehicle physics, graph resources and authored routes
are unchanged. These tests prove target ownership and bounded query behaviour;
the exact Windows client must confirm the observed circling is resolved.
