# Authored route execution follow-up, 2026-10-05

The native report `wot-error-report-20261005-024939-4e46ab23d1fe.zip`
used build `colorfulmeans-37224774166-1`. Its pinned El Halluf medium-tank
routes were loaded correctly. Team 2 Centurion Mk. 3 repeatedly alternated
between distant-contact advancement and the cached first vertex behind its
actual pose near (-129.44, -291.0). The logged terrain verdict was clear.

Shared route searches now start at the authored leg anchor, not the first
vehicle's offset pose. Their bounded A* prefers the authored leg corridor
instead of the old slope comfort cost. This is a soft preference: the existing
support, grade, water, collision and per-vehicle rejected-edge checks remain
mandatory. Local joins and combat searches also prefer proved manoeuvring room.
A passed cached vertex is consumed only with a checked forward segment;
otherwise navigation replans a private join from the actual hull pose.

Distant targets retain aiming and target leases while vehicles advance along
the assigned route. Both server and local planner use the existing `advance`
mode for this case, keeping the route navigation key stable. Close engagement,
withdrawal, cover and explicit authored wait orders retain their own handling.

Validation: 101 server Bot tests and 31 targeted route, join, clearance and
Sheridan ingress tests pass. All 161 client Python sources compile under
CPython 2.7. The reported Centurion pose selects a checked forward descent
in a replay of the exact shipped graph. A wall fixture still requires a legal
detour. The broader 217-test AI suite has the same eight legacy failures and
nine obsolete-test-double/API errors as the parent, after updating assertions
for the intentionally changed route advancement behavior.

These checks establish source behavior and resource contracts. Native turning,
route fidelity and performance still require testing on the exact Windows
client. Existing authored profiles and map graphs are not rewritten.

## Build 88 native follow-up: ineffective corridor cost

Report `wot-error-report-20261005-031716-0daf708dd80f.zip` confirms build
`colorfulmeans-37227013351-1` still turns repeatedly on the downhill route.
The corridor vector used generic `dx`/`dz` locals that the heuristic overwrote
after each successful relaxation. Consequently its next-edge deviation cost
used cell-relative heuristic offsets instead of the authored world vector.
The preceding single-forward-target test did not exercise completed planning.

The exact new authored leg from (-131.5, -294.697) to (29.276, -180.313)
exhausted 4096 expansions under the shipped code. Correcting the immutable
corridor vector completes the search in 323 expansions plus its result step
on the unchanged shipped graph. Native logs show the affected medium tanks
following short pending-search fallbacks rather than a completed leg.

Remove slope comfort surcharges at the common A* cost owner, for both baked
and live-ground edges. Eligible uphill/downhill steps pay distance and actual
obstacle, water, clearance and route-deviation costs; route joins, local combat,
withdrawal and continuation cannot restore the old surcharge. Grade, support,
collision and directed graph links remain eligibility checks. No graph, route,
physical coefficient or expansion-budget change is made.

Three regression cases fail on build 88 and pass after this correction: the
complete reported descent must finish within 512 expansion steps; an eligible
bump must not cause a flat bypass; live-ground planning must not zigzag across
a legal plane, uphill or downhill. These tests also cover ordinary and authored
corridor planning. The dedicated CI now runs the completed-plan regressions.
The six route regressions, 101 server tests and 28 other targeted join,
clearance and ingress checks pass locally; client navigation compiles under
Python 2.7. Native gameplay remains pending and the existing general artillery
target-lease failure is not claimed fixed.


## Residual downhill stair geometry and report 132255

Build 89 fixed the authored corridor cost but retained the legacy 0.38-grade
link eligibility. The reported M46 path alternated 4 m cardinal edges; the
23.86-degree diagonal was absent although native longitudinal grip remains
full through 27.5 degrees. The runtime now admits bounded (48 m maximum)
shortcut proofs across dry squares only when both reversible cardinal paths
already exist and every corner gradient remains within the existing native
full-grip threshold. Actual ground is sampled at at most 1 m intervals and the
native hull corridor must be clear. Missing ground, cardinal links, corners,
water, collision and discontinuities still veto. A* topology, map fingerprints
and authored profiles are unchanged. Proof caches retain the existing bounds.

The exact installed #1513 terrain and compiled static obstacle audit admitted
both the reported diagonal and its longer downhill chord. A fixture sampled
from that terrain verifies the complete smoothed output, not merely one
forward target. Native game driving remains the user acceptance boundary.

Report 132255 also proved that four-decimal edited default route coordinates
were rounded to three decimals in the manifest. The old 0.0001 matching tolerance
rejected the route identity and its 120-second waits. Matching now accepts only
the maximum three-decimal serialization error (0.000501 m); different fallback
lanes still reject. The regression exercises arrival, the complete 120-second
wait and release, for a scoped default TD route.

The late M41 Bulldog and LTTB were in low-health withdrawal terminals, with
zero throttle and no collision. Their distant known targets were beyond the
320 m light-tank firing envelope, so firing was withheld while target identity
kept the defensive hold alive. A completed withdrawal now resumes after the
existing 15-second defensive pause when there is no target within the existing
1.15 firing-range threat envelope and no recent hit. A nearby threat still
restarts withdrawal. Target identity alone no longer pins the terminal forever.

Validation: targeted navigation, authored waiting and server regressions pass;
Python 2.7 compilation passes for changed client modules. No physical tank
coefficients, navgraph resources or saved profiles were changed.
