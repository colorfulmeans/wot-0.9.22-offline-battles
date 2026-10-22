# Base-circle arrival and capture handoff - 2026-10-22

The 144811 report shows Object 261 driving from inside its own 50 m circle
(about 49 m from the center) to the center before retiring macro travel.
The attack audit reproduces both a route endpoint and a capture order still
requesting travel while already inside the enemy circle, 30 m from the goal.
The previous terminal fix retired travel only within the 13 m point radius.

## Behavior

- Preserve travel priority outside the defended circle. Inside, stop macro
  translation and hand an existing target to stationary engagement, retaining
  the defense assignment. SPGs can request the existing ballistic proof just
  as in ordinary engagement; native arc, pitch, ammunition, obstruction,
  alignment and friendly-clearance checks remain mandatory.
- Preserve authoritative circle radii in both capture and defense contexts.
  An arrived defender cannot expire as a stalled traveler while in the circle.
  Leaving the circle resumes travel with the existing no-progress grace.
- On the final route leg, an endpoint inside the enemy circle completes at
  circle entry. Do not consume intermediate gates just because a tank enters
  the circle early. An endpoint outside the circle must finish first, before
  capture travel takes over. Remember that completion so subsequent snapshots
  do not send the vehicle back to the completed endpoint.
- Keep a stable capture squad with a three-vehicle budget including human
  contributors. Retain actual bot contributors first, including an immobilized
  contributor. Prefer ordinary vehicles for new assignments; use SPGs when
  ordinary candidates are unavailable. Other vehicles retain existing screen
  and combat behavior. Rank replacements by estimated travel to the circle
  boundary rather than its center.
- Prevent authored parking overlays from replacing a base mission. Preserve
  defense protection from non-navigation radio orders after engagement handoff.
- Record capture allocation, human and bot contributor counts, selected IDs,
  approach distance, contact count, pre-refresh stall age, shot sequence and
  reload state. Keep the existing contact-based progress refresh and retry /
  retirement durations; observations alone do not prove a stalled vehicle.

No navigation graph, continuity test, physical collision/obstruction rule,
local retry strategy or support threshold changed. One-point non-base goals
keep their precise arrival rule. Explicit team commands and authored waits
retain their original priority outside base mission ownership.

## Validation boundary

Added circle-boundary, displacement, intermediate-gate, outside-endpoint
completion, custom-radius, authoritative contributor-budget, immobilized
occupant, no-route capture, SPG defense timing, reload/lane and parking ownership
tests. Updated old assertions that intentionally expected penultimate-point
capture handoff or center/endpoint-based arrival. Retain tests of actual route
progress, screening capacity and defense membership using the mission ID.

Local reference tests prove the order/state transitions, not native #1513
physics, rendering, timing, or that a particular SPG can depress its gun enough
to hit a close target. The next Windows package is an unpublished PR candidate
for the user's exact-client test. Do not tag, merge or publish 0.10.2.
