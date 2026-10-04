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
