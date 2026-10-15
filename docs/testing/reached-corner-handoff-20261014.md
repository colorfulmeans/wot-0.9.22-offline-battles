# Reached path corner handoff (034127)

The 034127 Windows245 report shows Tortoise bot25 circling the (78, -34)
corner for roughly 27 seconds, and KV-3 bot4 repeatedly switching between
nearby vertices around (-142, -70). Safe completed local legs do not admit the
unsafe-only local-refusal watchdog. Reacquiring the cached incoming path leg
can therefore renew the local target without advancing the route.

The follower now records arrival at an exact cached vertex when its outgoing
edge cannot be issued and a local fallback is selected. When that same path
and request are resumed outside the arrival radius, it checks the outgoing
connector from the realised hull pose. A proved connector advances the index;
a geometric refusal requests a private replan from the actual pose. Deferred
native proof holds without a collision penalty or a replan. A fresh path can
legitimately revisit the same setup. Tactical holds, arrival, changed requests
and private replans retire the receipt.

The search receipt adds reached_path_corner and reached_corner_replans.
No terrain penalties, collision relaxation, slope thresholds, aim gates,
vehicle profiles, authored routes or graphics settings change.

Validation: navigation unit suites cover recorded-coordinate arrival/detour,
old-logic reproduction, proved forward continuation, both proof deferrals,
new-path ownership and receipt retirement. Geometry callbacks in these fixtures
are explicit replies; they do not replay the native map BSP. Exact-client
Windows acceptance must still confirm that the observed vehicles escape and
that mandatory climb setup points remain respected.

Local verification: 372 tests across 26 navigation, driver, authored-route,
rear-aim and snapshot suites passed. CPython 2.7.18 compiled all 180 client
sources. The finite dead-end test includes the six vehicle/FPS subcases.
Windows packaging and in-client acceptance are pending.
