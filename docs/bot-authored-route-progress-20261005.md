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
