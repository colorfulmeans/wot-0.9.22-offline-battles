# Combat manoeuvre and wall-egress handoff

## Scope and recovery point

This change follows Windows401, source `bed68a2e897d4b5e985321660763ed25de72ac42`
on `fix/terminal-route-capture-handoff` (PR #95). The new branch is
`fix/combat-manoeuvre-and-wall-egress`. Keep that parent as the rollback point;
do not substitute the release tag or another 0.10.1 launcher revision.

Runtime evidence: `wot-error-report-20261019-172753-0e3742a48adc.zip`, one
round on `86_himmelsdorf_winter`, 17:20:47–17:27:37, team 1 capture victory.
The report's build identity is `colorfulmeans-39226708047-1`.

## Diagnosed failures and implemented ownership

### M41 90 GF, Bot 14

From approximately 17:25:46 until 17:27:33 the fixed flank destination was
`(-148.837, 1.1, 75.174)`. The vehicle alternated local arrival and travel while
tracking Bot 20. At 17:26:30, local throttle was zero but the positive strategic
override produced throttle one in an `arrived` command. Replaying that input
against the parent adapter reproduces the override.

Positive strategic throttle may now override only a driving command, never
arrival. A completed flank leg owns a firing hold while the order and target
remain unchanged. Track-pivot displacement cannot restart it. A new destination,
new target, displacement beyond the hull-length allowance, a contact manoeuvre,
another mode, or `forget()` releases this ownership. Route travel, collision
admission, target priority and firing permission still have their existing owners.
At the server, an already completed flank with no local firing lane no longer
renews its travel lease: it yields to the existing route-resumption branch,
retaining enemy tracking without granting permission to fire through a wall.

### Strv S1, Bot 8, and Object 268, Bot 10

Their wide hull turns repeatedly entered `friendly_lane_reposition`. The old
four-second total lease often expired during hull alignment, before translation.
Returning to enemy aim allowed the same blocked shot to recreate the same action.
Object 268 also repeatedly triggered `route_release_active`: eight seconds ready
without firing released four seconds of route movement.

The existing four-second translation allowance is retained for turreted tanks.
For limited-traverse guns, the action adds the current required turn angle divided
by the descriptor-derived hull turn rate, plus two seconds of alignment margin;
the complete action is capped at 16 seconds. This is a bounded lifetime, not an
unlimited progress renewal. An already active attempt cannot renew its deadline.

Timeout ends the owner, records the exact blocker/target/shot identity and imposes
an eight-second retry interval. The next retry uses the opposite existing lateral
side; later retries remain possible. A different blocker/target/shot or two metres
of source/blocker movement invalidates the old retry identity. Arrival, target
death/change, defensive priority or withdrawal also releases the action. The
friendly-fire, collision and support gates remain authoritative throughout.

`local_combat_manoeuvre` is a worker-owned boolean, encoded in an unused flag bit
without adding wire columns. Its beginning and end are publication edges. Both
normal and contained server state projections preserve it. While a friendly-lane
or gun-angle manoeuvre owns the hull, the server clears its idle-firing timer.
After the terminal publication, a fresh idle interval can begin; the original
eight-second/four-second release rule remains available. Death clears the bit.
Low-health retreat and base defense can preempt lane repositioning. Existing
limited-traverse rear aiming and attacker priority are unchanged.

### T-54, Bot 20

The tank remained near `(-256, 1.1, -19)` for more than three minutes. Its original
route and recovery goals did change; this was not a complete absence of replanning.
The report includes hard body-sweep refusals against vertical wall faces near
`z=-22.15` and `x=-253.23`. Generic direction samples alone did not carry those
pre-execution refusals into the existing blocked-step feedback path.

Current-decision authoritative body-sweep hard refusals now enter the existing
per-Bot blocked-action accumulator when LocalDriver returns `blocked` with real
movement intent and the refused action points toward that selected local target
(within 0.1 radians). Unknown/deferred/unproved results and refusals for the
opposite direction do not enter it. A rotation
refusal does not create a global map wall. Four verdicts over at least one second
retain the existing private edge penalty and replan.

The proved rejected short point also uses the existing finite point-refusal
lifetime (12 seconds). This covers short connectors inside a coarse cell, where
an edge alone cannot name the point. Replanning or changing a request cannot erase
that still-live physical refusal. Existing candidate enumeration, distance/cost/
turn scoring and retry policy remain intact; the candidate filter skips only the
temporarily refused point's 1.5-metre arrival disk, allowing another existing
candidate to compete. Expiry permits the original point to be tried again.

## Diagnostics

The existing bounded `BOT MOTION` record now carries:

- `planner_blocked_handoff`: decision time, target, hard body refusal count,
  global direction review result, private replan result and reason. Nonblocked
  decisions replace the prior reason instead of presenting it as current.
- `friendly_reposition`: the active marker, including origin, destination,
  blocker identity and position, shot identity, side, start and deadline.
- `friendly_reposition_event`: timestamped start, arrival, timeout, retry wait,
  target disappearance/change or priority handoff. The timestamp separates the
  most recent terminal event from the currently active marker.
- `local_combat_manoeuvre` and adapter `control_arbitration.flank_arrival`.

No additional collision/ground probes are spent to write these receipts.

## Validation and limits

`tests/test_port_0922_bot_combat_manoeuvre.py` covers the report-coordinate arrival
override; persistent flank completion and release; increased limited-traverse
lease; unchanged turreted allowance; fixed deadlines; timeout/retry; target death,
target change and priority cancellation; arrival cleanup; report-coordinate native
refusal escalation; private/finite penalties surviving a replan; unknown/stale
evidence exclusion; selection of a different existing candidate; compact wire
begin/end parity; and server idle-timer ownership and release.

The publication edge contract test is updated to include the new flag and proves
both begin and end transitions. Run the affected runtime/navigation/codec/server
tests, Python 2.7 source compilation, and the exact pushed commit's Actions checks.
Record results and package identity in the accompanying delivery manifest.

Engine-free tests establish command and lifecycle behavior, not successful native
egress from every map pocket. The first Windows acceptance still needs the next
report: inspect T-54-class wall exits, completed flank holds, and fixed-gun lane
repositioning. Do not claim a real-client playtest solely from these tests.

The parent already has independently recorded test failures for Airfield 24-FPS
spawn departure, a GC reachability fixture and a team-command fake missing
`_alive_bots`. Keep those visible; do not remove tests or change unrelated
navigation rules to turn them green. Distinguish any new failure from that parent.

## Preserved contracts and next audit

Support remains one failed basic point enables detailed support, all five restored
points disable it. No support/stacking/ram formula, map graph, route catalog,
slope policy, navigation scoring, target priority, ammunition rule, health retreat
threshold, or limited-traverse rear-aim law is changed here. Test-scene launchers
remain independent opt-in entries. This is a test package and source backup,
not a release/tag or an instruction to merge into `main`.

For the next report, reconstruct the command's cached decision timestamp before
comparing it to a physical commit. A native `hard` result must be distinguished
from missing terrain, a deferred budget, friendly traffic, stationary defensive
combat and a successful capture hold. Do not infer all stationary tanks are stuck.
