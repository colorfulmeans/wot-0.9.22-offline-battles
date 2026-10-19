# Combat manoeuvre and wall-egress handoff

## Scope and recovery point

This change follows Windows401, source `bed68a2e897d4b5e985321660763ed25de72ac42`
on `fix/terminal-route-capture-handoff` (PR #95). The new branch is
`fix/combat-manoeuvre-and-wall-egress`. Keep that parent as the rollback point;
do not substitute the release tag or another 0.10.1 launcher revision.

Runtime evidence: `wot-error-report-20261019-172753-0e3742a48adc.zip`, one
round on `86_himmelsdorf_winter`, 17:20:47â€“17:27:37, team 1 capture victory.
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
- `planner_blocked_last_replan`: a separately timestamped terminal event with
  original/target pose, refusal expiry, replan count and wall witness. It survives
  subsequent nonblocked decisions so the three-second stall record cannot miss
  the short transition. The navigation snapshot also carries the live blocked
  counter, contact episode and point-refusal provenance/expiry.
- `friendly_reposition`: the active marker, including origin, destination,
  blocker identity and position, shot identity, side, start and deadline.
- `friendly_reposition_event`: timestamped start, arrival, timeout,
  target disappearance/change or priority handoff. The timestamp separates the
  most recent terminal event from the currently active marker.
- `friendly_reposition_last_terminal` and `friendly_reposition_retry`: terminal
  cause and retry state are retained separately. A quiet retry-window observation
  cannot overwrite the timeout that caused it, nor can a new action erase the
  previous terminal witness before the bounded motion record samples it.
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

## Follow-up: report 183514, effective wreck pushing and route evidence

The Object 257 (Bot 3) continued to advance and move Tiger II wreck 16, but
the macro gate timer skipped progress checks whenever `route_wreck_blocked`
was true. At 18:31:39 it skipped gate 7; at 18:31:59 it switched from rail
to hill despite continuing local motor progress. The macro timer now renews
after a new half metre of realised progress toward the same gate objective.
Its best-distance mark survives reversing, contact flicker and local target
changes. A stopped push still expires after the original twenty seconds and
uses the unchanged skip/retry/route-switch path. Ordinary non-contact progress
thresholds remain unchanged. Moving a wreck without moving the Bot does not
renew this clock. This is a progress-accounting fix, not a collision bypass.

Pressure transfers for WZ-120G, T49, AMX 13 90 and E75 changed under changing
contact weights and contributor counts. No new route lock, slope preference,
lease duration or donor policy is introduced without a demonstrated invariant
failure. Actual assignment receipts now retain contact identities/health/radio
leases and contributor identity/position inputs. These inputs are not duplicated
into every Bot's balance summary. Route entry receipts retain the initial
nearest point, realised speed/yaw, every close/rear-point skip and final entry;
their original sample time survives subsequent progress observations. This
exposes why an expiry return selected a distant endpoint instead of merely
recording that an expiry happened.

Local wreck motor receipts preserve the first terminal reason, time and pose
after subsequent `exhausted` observations, separating motor timeouts from native
turn refusals. Successful macro renewals are emitted in the server attempt log,
and the report reader now parses that plain-server record as well as skips and
switches. Regression coverage includes continuing slow pushes, stops, reversal
orbits, contact flicker, changed local goals, unchanged ordinary thresholds,
pressure input provenance, entry evidence and terminal-reason lifetime.

Native Windows gameplay remains the next acceptance boundary. Support opening
at one missing point and closing with all five restored, target selection,
native body/LOS checks, authored routes and original retry switching are intact.


## Follow-up: report 191856, blocked firing holds and angle execution

A lost local firing lane no longer renews an ordinary stationary engage/support
lease. Tracking and target priority survive; movement resumes the existing
map-authored leg with launch disabled. A timed four-second route release cannot
re-establish a stationary engage hold while launch permission is absent. Moving
flanks, cover and low-health owners keep their existing laws.

Mechanical-angle recovery retains its native eight-metre candidate check,
initial two-second facing phase and finite failed-pair retry. Once selected,
its destination survives the old absolute six-second expiry. A new best 0.25 m
translation or five-degree alignment improvement renews a six-second no-progress
clock. The first executed local driver steering goal is frozen once, so a local
turn does not consume all translation time, and changing local points cannot
keep resetting alignment credit. Arrival, no progress, unavailable candidates,
priority handoff and cleared mechanical refusal have timestamped terminal
receipts. Both forward and reverse mechanical actions publish the existing local
manoeuvre flag through their terminal, preventing the server idle-fire timer
from interrupting a still-active relocation. Friendly-action cleanup cannot
erase a concurrent mechanical owner. The native gun solver and every actual
body sweep remain authoritative.

Static-only support solves reuse exact complete column results, including layer
witnesses, inside their synchronous query scope. Changed column/band, destructible
revision or solve invalidates reuse. Potential vehicle-roof contacts do not take
this additional shortcut: their live carrier/contact side effects still run.
Reuse counters and elapsed time join the existing support profile. This proves
query equivalence and reduced duplicate calls, not a measured Windows FPS gain.

Navigation diagnostics distinguish request wait from actual per-Bot job age and
the global oldest job age. A pending asynchronous job's expansion count is unknown,
not zero: that counter is delivered only on completion. Named worker state is
explicitly the global last poll. Native job submission, completion, cancellation
and close records retain endpoints, job identity, simulation-clock basis and
query received/answered/deferred counters. Per-job query service remains visible
in sampled motion receipts. No T-54 path-scoring or retry-policy change is made
without proof of a routing defect. The report's zero counter did not prove an
unserviced background search.

Focused tests cover lost-lane reload and reacquisition, multi-second driver
turns, real movement, no-progress exit, native job/query lifecycle and exact
support reuse/invalidation/roof exclusions. CPython 2.7 compilation, relevant
regressions and independently inspected launcher payloads are delivery evidence;
next-report exact-client behavior and frame pacing remain the acceptance boundary.
Support still opens with one failed point and closes with all five restored.
