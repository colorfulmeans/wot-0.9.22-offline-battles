# Combat manoeuvre and wall-egress handoff

## Scope and recovery point

This change follows Windows401, source `bed68a2e897d4b5e985321660763ed25de72ac42`
on `fix/terminal-route-capture-handoff` (PR #95). The new branch is
`fix/combat-manoeuvre-and-wall-egress`. Keep that parent as the rollback point;
do not substitute the release tag or another 0.10.1 launcher revision.

Runtime evidence: `wot-error-report-20261019-172753-0e3742a48adc.zip`, one
round on `86_himmelsdorf_winter`, 17:20:47Ã¢â‚¬â€œ17:27:37, team 1 capture victory.
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

## Follow-up: report 202110, lane delivery and capture defence

The authority now keeps three separate facts: the team's existing spot-memory
lease, the recipient's radio lease, and that shooter's native firing-lane
receipt. A direct observer's 0.5-second freshness no longer silently erases
an otherwise valid local lane in the worker packer or server admission/relay.
This does not refresh visibility from a ray or expose unobserved positions.
Invisible contacts, expired radio/lanes, dead sources and mechanical refusals
still exclude launch; the independent native final-fire gate is unchanged.
Positive-publication counters run after all filters, rather than at the earlier
merge. Selected-pair receipts retain publication time, lane sample/time/age,
direct and radio freshness, remaining lease, mechanical result and terminal
inclusion/exclusion reason, including the absence of an observation row.

The gun solver's actual target identity, remaining angular error and alignment
are published through an optional atomic codec group and admitted on both normal
and contained state paths. Ordinary score changes do not interrupt a first aim
while it makes new one-degree improvements. A shot releases that commitment;
six seconds without new aim progress also releases it. Immediate close-threat
and existing learned recent-attacker overrides remain unchanged. A visible
tracking target briefly missing a lane can survive two seconds even if another
enemy has a lane, always movement-only; persistent blockage still releases it.
Death, knowledge/range loss and exhausted weapons keep their existing exits.

Capture priority already existed after ordinary selection. This change repairs
that owner rather than adding another one: it retains a current valid capturer,
does not zero/recreate its lease every tick, and records the final override in
the tactical diagnostic. Proved in-range capturers take precedence over ordinary
targets; the existing recent-attacker response remains an explicit exception.
A blocked capturer never grants fire. Defender retention recognises a firing
window outside the circle, and no-approach accounting credits actual new shots,
decreasing post-shot reload and new aim progress toward a proved capturer.
Possessing a target/positive ray alone cannot renew it forever. Stopped or
non-progressing defenders still use the original ten-second replacement rule.
The base incident receipt retains every combat-credit reason and input.

T28 Concept and Sturer Emil have completed search jobs and positive short-egress
proofs in this report; that does not prove their repeated local actions actually
escape. No navigation law is changed. Bounded eight-second execution windows
record every applied-command observation, accumulated travel versus net travel,
forward/reverse/turn/hold counts, modes, decision identity and sample time.
The previous window survives rollover beside the current motion/physics receipt.
The original driver retry clock and route-switch rules are retained.

The reported worker bottleneck remains world collision, ground sampling and
vertical integration, not solely the native ray itself. Complete-column reuse
had negligible hits in this scene. No wider world-answer cache or reduced
physics interval is introduced. Additional world bridge/engine-dispatch and
geometry-preparation timing separates callback/marshalling from the existing
world/ray stages; it measures an unresolved cost rather than asserting an FPS
gain. Support remains one failed point enables detailed / all five restore
disables it. Damage, stacking, authored routes, C, avoidance and retry policy
are unchanged. Focused tests cover positive/negative publication through relay,
slow/blocked/dead/urgent target lifetimes, codec/server admission, base target
override, combat progress and eventual idle replacement. Real Windows timing,
native LOS and gameplay acceptance still require the next user test report.

## Windows414 follow-up: idle gun and exact query reuse

Report `wot-error-report-20261019-211637-977f532af0b7.zip` confirms a no-contact
gun-rest defect: the gun retained a world bearing when its hull turned. Rest
yaw now follows the current hull, using the existing traverse rate and limits;
neutral pitch and all enemy/retained-target/ballistic aim laws remain intact.
Replace the old test which explicitly required the incorrect world bearing.
Route-connection records include previous executed aim identity/time alongside
the current hull and turret pose, without acquiring an additional native probe.

Reduce only exact unfiltered engine-ray repeats inside one synchronous native
world operation. Keys retain exact endpoints, ground mode and the destruction
revision. End/exception unwinds the scope; destructive recasts invalidate all
nested scopes. Filtered rays always execute their native callback: the shared
callable has a different thread-local candidate/exclusion context for each ray,
so its identity is not sufficient evidence for raw-result reuse. Errors are
never cached as misses. No collision receipt lifetime or planning deadline is
extended and no physics interval is discarded. New counters expose hits,
misses and effect invalidations; Windows performance improvement is unproved.

IS-2 Shielded (Bot 2) and FV215b (183) (Bot 24) eventually left their small
adjustment areas in this report. Receipts show intentional zero-throttle
alignment, not a collision/support veto. Their changing local connectors and
strategic goals do not yet establish one reproducible defective transition.
Keep their driving/retry/navigation laws unchanged. Publish each applicable
pedal gate, chosen versus requested heading, installed traverse limit, resolved
alignment point and final driver pedals. Clear that evidence on every call and
publish explicit non-drive terminal modes for waits/recovery/holds, rather than
leaking the preceding drive sample. Preserve the Golden Type 59 pressure switch.

Repair priority is repeating deadlocks, then permanent movement stalls, then
prolonged stalls that escape, then combat-policy refinements.


## Report 221844: combat ownership and mechanical arrival

The reported WZ111-1G FT reached a checked gun-angle relocation. Arrival and
stall previously shared a terminal path: reject the target for eight seconds,
remove its published firing lane and resume a route with no selected enemy.
Arrival now keeps the enemy and returns to an aiming hold. Only failed local
attempts retain the existing retry cooldown. That cooldown bounds movement
attempts, never the independent native lane or final ballistic/fire gate.
Failed movement and blocked/expired lanes retain the selected known enemy and
use the existing contact-approach/navigation owner instead of ordinary route
travel. The idle-ready-fire release also approaches its combat target rather
than a route point. Death, knowledge/range loss, original attacker priority,
low-health/magazine tactics and base-defense travel remain separate lifetimes.

A stationary engagement preempts retained contact escapes and wreck pushing;
the existing hold path terminates the driver's pending recovery. Base defense
and movement without an enemy keep their checked recovery owners. Real world
collision/contact resolution still applies. Pressure may update the background
route but does not steal a selected combat objective through these handoffs.
No authored routes, C, avoidance, retries, slope or support law is changed.

Tiger II's small-pocket movement alternated advance, lane reposition and route
orders while firing three shots. That does not yet prove one defective driver
transition. Keep navigation policy unchanged. Complete the existing control
receipt with the action owner; reuse its existing objective-progress snapshot
instead of copying that nested history on every command. Preserve the previous
credit reason/frontier/alignment when a changed order resets its clock.

The worker profile still shows world bridging, ground and destructible scans
as significant costs. Exact unfiltered world-ray reuse had no hits in this
session. Do not broaden that cache or weaken filtered collision checks. Reuse
one immutable collision-body preparation across all five synchronous reverse
sweep samples; every native/vehicle check remains executed. This removes four
redundant preparations per reverse assessment, not four collision checks.
Native gameplay and end-to-end worker FPS remain Windows acceptance items.

## Ordered aim and blocked-action follow-up (report 232728)

The ordered-search state machine from the first test package is withdrawn after
report 001415 reproduced a moving-source starvation regression. Restore the
original rotating two-candidate lane probe, armour ranking/competence, exposed
fallback, selected-part lifecycle and boolean lane publication. Remove the added
mechanical precheck, evidence ages, motion thresholds and pending return path.
The only attack-aim production change from the pre-search implementation is the
candidate list: lower hull, hull centre/left/right/up, turret up/left/right/centre.
The original eight geometry samples already include turret up; this explicit
nine-point list adds lower hull only. Do not invent an extra tenth point.
Exposure/cover/incoming samples and the final projectile safety gates retain
their original owners. No additional search completion or refresh law is added.

Retain unexpired radio-scoped route assignments in the pressure catalog even
after the last original donor dies. Radio loss and lease expiry still release
them. Assignment receipts enumerate all simultaneous invalidation causes.
Repeated live remembered-rotation refusals now feed the existing private Bot
retry lifecycle. They do not publish a global wall or change path ranking.
Mixed/unknown refusals do not authorize this feedback. Record rejection kinds
and the original rotation contact for unresolved stalls. Preserve support,
collision, wreck progress, C, avoidance, target priority and retry policies.

## Solid railway stock (report 004112)

The October 16 navigation rollback also removed the October 15 railway raster
exception. Restore this object classification without restoring later driver
strategies: exact rw004_Carriage and rw005_locomotive resource families remain
solid in the compiled raster, the first Python planning ray, the native query
callback, and the exact kinetic gate. Tracks, signs, fences, houses and trucks
keep their existing rules. Ordinary original materials remain planning-soft;
intact or damaged railway identities cannot authorize a crush-through route.
Native shot/destruction presentation is not a navigation permission.

Fixed baked chunk/item identities are indexed once with the catalog so cold
planning does not depend on streaming or scan the resource list per ray. The
C++ oracle delegates original-material classification to its existing owner
callback instead of returning false based on material number alone. It keeps
hard-material fast paths and the existing synchronous owner/lifetime guards.
The crush-gate receipt distinguishes solid_railway_vehicle from energy rejects.

The railway repair tool samples exact compiled railway triangles against the
existing vehicle clearance law, masking only blocked nodes and crossing links
in the retained main and local grids. It preserves all route points, unrelated
geometry and directed ingress links. Validation must check every default route
segment and both base connectivity, plus all baked/streamed railway identities
and the real compiled host callback. Ship the rebuilt native bridge with the
matching Python and graph data; real Ensk traffic remains Windows acceptance.

Validation on the pinned client resources: eleven maps, 990 default route
segments and base connections pass the existing strict validator. Original
waypoint arrays remain byte-equivalent as data; two old waypoint cells now
occupied by railway stock use the existing adjacent-cell projection (4 m),
without a new runtime fallback. Editor/default-profile identities are rebuilt.
An optional full native navigation-state comparison still fails at frame 0/0;
rebuilding the parent filter produces the exact same failure text/state. The
current CI's water/grid subset (63 checks), actual native railway callback and
native aim parity pass. This pre-existing full-state mismatch is not claimed
as passed and is not repaired by changing driver/navigation policy here.

### Full native-state audit boundary

The full comparison explicitly installs `NativeNavigationCore`, an older C++
TerrainNavigator state machine. Production `NativeSimulation` deliberately
leaves its navigation and motion owners unset, retaining the Python navigation
laws with independent native search/geometry primitives. Do not confuse the
inactive full-state owner with the active native railway collision callback.

Recording differences without stopping at the first assertion completed 30,795
comparisons across five scenarios/900 frames. This diagnostic run is NOT a
passing parity test: 528 next-target calls differ, beginning at scenario 0,
frame 2, Bot 7: Python returns (8, 0, 4), native returns (32, 0, 4).
Later cached paths and progress clocks differ too. Initial missing receipt
fields alone therefore do not explain the failure. Python tracks temporary
fallback visits, stalled episodes and pending-prefix progress; the old native
state/serialization and observe_macro implementation do not mirror these laws.

Rebuilding the pre-railway parent native filter and rerunning the expanded
diagnostic produces identical comparison counts and every recorded difference.
This is existing inactive implementation drift, not a railway-fix regression.
The CI water/grid-only subset passes but does not establish full-state parity.
Keep the inactive owner disabled; do not erase differing fields or alter live
navigation to make this optional comparison pass. Any future activation must
first port the complete current lifecycle and pass strict full comparisons.


## Minute pressure dispatch and blocked-action handoff (October 20)

Reports `011649-2394e88f32a1` and `013754-d56ca0a33b56` establish these
separate failures. This change retains the production Python navigation owner,
real collision/occlusion, C/avoidance, retry/reroute, and one-invalid/five-valid
support switching. It does not introduce a slope preference or rerank routes.

* Grille and T28 Prototype exhausted a mixture of native hard pivot rejections
  and remembered pivot failures, but the handoff required heading-aligned or
  homogeneous evidence. Complete the existing private local-target failure
  lifecycle for this exhausted case. Unknown/available candidates and traffic
  without native/remembered hard evidence cannot authorize it. No global wall
  is published. Replaying their recorded receipts now calls the private replan
  owner; the old receipt for Jagdtiger alone remains insufficient evidence.
* Jagdtiger had a valid current coarse hull pose but all candidate coarse
  poses failed. Candidate rejection now invokes the existing authoritative,
  noncommitting next-rotation-slice sweep, just as an invalid current pose did.
  Native rejection and the final real collision commit remain authoritative;
  missing/exceptional coarse probes still defer to real commit. A valid current
  coarse pose with a rejected candidate cannot be cleared by an unavailable
  native precheck: retain the old candidate rejection in that case. The first
  CI pass exposed this missing-query regression in the fixed recovery-alley
  fixtures; unchanged tests pass again after completing this branch. Logs retain
  both coarse results, native proof, candidate outcomes, handoff and retirement.
* Pressure evaluation changes from four seconds to sixty seconds. Assignment
  renewal, radio-loss release, expiry and return are evaluated at the same
  minute boundary. A 61-second lease crosses the next evaluation instead of
  expiring between it. Combat radio knowledge still expires normally. The
  independent 20-second ineffective-wreck reroute and ordinary local retries
  are unchanged; this is not a one-minute freeze of movement or combat.
* The Ensk M40/M43 retained slot overlaps a carriage with the mounted hull,
  although the old chassis-only envelope missed it. The offline spawn repair
  reads all 1,068 chassis and mounted-hull bounds, with real hullPosition mounts
  and no undonated hulls. The conservative maximum body rectangle is 4.836 m
  wide by 12.818 m long. On eleven railway maps, all 330 slots are checked
  against compiled geometry, soft props, pairwise spacing and directed home
  connection. 151 invalid slots move at most 32 m; 179 remain unchanged.
  Each changed slot retains its yaw and records before/after coordinates. This
  count includes other existing clearance failures found by the complete body
  recheck, not just the one reported M40/M43. Grid nodes/links, local meshes,
  hazards and waypoint arrays stay equal to parent e87b0108. All 990 default
  route segments/base connections still pass the strict validator.
* Lethal fire now publishes its extinguished state in the same canonical
  damage result. A dead participant also clears residual durable fire and
  attribution on the next active tick. Client critical state/effects reject
  late fire on an already dead hull, including native HUD presentation.

Tests cover mixed exhausted evidence, traffic/unknown exclusions, native clear
and hard candidate sweeps, pressure transfer/renewal/release over several minute
boundaries, actual lethal-fire mechanics, late dead snapshots and canonical
cleanup. Spawn tests bind all recorded relocations to the retained parent data;
mounted-body fixtures verify country-resource mapping and hull offsets. Updated
old assertions preserve their original safety purpose under the new interval
and body envelope. The inactive full-native-state parity limitation above is
unchanged and must not be represented as passing. Windows gameplay acceptance
of these changes remains the user's next test, not an engine-free test claim.


## Combat progress ownership and active-capturer exclusion (October 20)

Baseline: `6f370f47`. Reports `022452-476a3cfef008` and
`023149-1f826bf4b0e2` expose separate ownership defects, not a new path policy.

* M4190, AMX 13 57 and T-54 change mechanical/approach/withdraw sub-actions
  within one enemy task. Previously moving enemy coordinates or a firing hold
  erased the objective clock, and a hold cancelled an unfinished recovery.
  Keep the physical progress frontier, alignment anchor and retry episode for
  the same selected actor. Intentional holds pause rather than erase travel
  failure time. New enemies/noncombat tasks release that scope. Actual travel
  out of the hull-sized pocket still starts a fresh frontier; target movement
  alone earns no translation. Existing collision admission, recovery actions,
  failure counts and reroute policy remain authoritative.
* T28 Concept and SU-100M1 can replace a known blocked-lane approach with rear
  mechanical parking. Read the existing exact pair/pose lane cache before rear
  ownership and fence both episode continuation and later creation in the same
  update. Only fresh blocked approach evidence prevents that parking. Unknown,
  expired and clear evidence, normal rear withdrawal and limited-traverse
  aiming retain their original laws. No additional collision/shot query is
  introduced. The existing eight-second rear timeout already works and is kept.
* Base defense changes only eligibility for actual active capturers of the
  opposing base, using canonical `(kind, id)` contributor records. Exclude them
  from new/backup choices and release any existing responder which enters
  capture. Leaving capture restores eligibility. Quotas, ETA ranking, deadlines,
  release timing and pressure dispatch do not change. Capture entry/exit and
  responder releases retain bounded history alongside the existing full input
  and final-order log. A 96-case comparison against baseline gives identical
  non-capture responder results; quota regression tests include a capturer plus
  two available defenders, so exclusion cannot silently shrink the old quota.

The new ownership suite covers moving targets without self movement, sub-action
changes, paused/completed recovery, true new tasks, real curved translation,
recorded decision inputs for all three loop cases, native-cache freshness and
full runtime continuation/creation of rear episodes. It is included explicitly
in CI. Existing support one-invalid/five-valid, physical/occlusion and retry
checks remain. No navigation grids, routes, slope rules, shot candidates,
crushing damage or independent test layouts are changed.

Recorded input replay proves the progress owner, not unseen native motion.
Windows gameplay acceptance is still required. The pre-existing Airfield 24-FPS
fixture failure (Bots 18/27 at 5.877/11.344 m) and inactive full-native navigation
state drift above must remain visible; neither is suppressed to publish a pass.

## Highway bounded escapes and spectator observation contract (October 20)

Baseline: `164f3cbc`. Report `032152-e7cf305674fe` contains 1,193 worker
motion samples across Live Oaks and Highway. The second round ends with a
worker disconnect coincident with the game closing; the report has no dump
which proves a native crash. Exception files contain session headers only.

### Confirmed repairs

* Highway Bot 25 is **AMX CDA 105**, not Foch 105. Its final retained reverse
  proof covers 0.318034 m from (-158.518135, -13.082677, -243.540265), with
  heading 3.491454 radians. The execution layer expanded this to at least
  0.5 m. The shipped graph with runtime shore hazards accepts the intended
  interval but rejects the expanded interval entering cell (85,63), bits 10
  (erosion plus shore). A cached command could also reuse its old distance
  from a newer origin. Preserve the selected origin, direction and total
  distance through LocalDriver -> BotAdapter -> execution. Each physics slice
  uses the remaining projection to that same fixed endpoint, without the
  half-metre floor. Completion retires the cached action; the existing driver
  continues normal retry/reroute ownership. A genuinely rejected, already
  aligned short escape retires its cache for a fresh local check. Turning
  toward a candidate still keeps its catch-up command. Real hazard, collision,
  shallow-water admission and native sweeps remain active. No failed edge is
  permanently banned and no route strategy/timer is replaced.
* The worker and server allow independent current shooting lanes during valid
  spotting memory (`fresh=False`, `visible=True`, positive `time_left`). The
  old LANClient predicate rejected such contacts and dropped the **whole**
  observation batch. At least 303 and 401 batches were dropped in rounds 1
  and 2, including a 58.331 s accepted-observation gap after the player died.
  There are 180 recorded current-lane/nonfresh publications. Align the visible
  consumer with the producer/server contract. Do not invent direct observers,
  extend memory, bypass radio recipients while alive or force enemy models
  visible. Identity/team/range/duplicate/freshness/threat validation remains.
  Existing dead-player presentation and stock AOI remain unchanged.
* BOT MOTION now captures short-escape origin, selected heading/length,
  cached distance, current remaining distance, completion, and final hazard
  verdict **after contacts and support**, rather than before integration.
  Final guard receipts include simulation time, actual origin/post-turn yaw,
  shallow/wet permissions, requested throttle/turn, action mode, target yaw
  and whether the refused straight action cache was retired. Non-short and
  nonintegrated paths have explicit terminal reasons. Existing sampled
  selection/execution receipts retain their timestamps and history status.
  This closes the missing horizon/commit evidence for remaining uncertain
  cases without changing their steering or adding world queries.

### Other stationary vehicles audited

Small-pocket durations are sampled observations, not a claim that every frame
was motionless. IDs below are round-local Bot IDs, distinct from player IDs.

| Round / Bot | Observed outcome and cause boundary |
| --- | --- |
| 2 / 1 Caernarvon | 52 s small pocket; retained reverse proof only 0.263584 m but old commit probes at least 0.5 m into a shore cell. Same confirmed horizon mismatch; shared fix applies. |
| 2 / 7 Edelweiss | 100 s pocket, nine shots, later killed at 03:20:22. At 03:19:04 and 03:19:27 the intended 0.094175/0.114046 m reverse intervals are clear, but the old half-metre commit reaches shore hazards. Shared correction applies. The final low-health hold already requests zero throttle and is preserved. |
| 2 / 6 T-44 | 64 s pocket, three shots, then travels about 295 m. Existing recovery completes; not terminally stuck. No independent policy change justified. |
| 2 / 21 T-44-100 | 51 s pocket, then travels about 658 m. Existing recovery completes; no independent policy change justified. |
| 1 / 8 AMX AC mle.48 | 27 s late pocket; final short reverse really moves. Blocked firing lane and successive local attempts are recorded, but no final execution hazard/native hard-contact veto establishes a separate root cause. Add commit evidence; do not invent a path fix. |
| 1 / 9 KV-4 KTTS | 31 s close-range adjustment. Recorded required pitch 7.47-10.08 degrees exceeds the native 5-degree limit; several target yaws also exceed its -15 to +45-degree traverse. Zero extra shots does not establish a legal shot being refused. Preserve mechanics and log execution. |
| 1 / 4 Panther II; 11 T-44-85M; 19 WZ-111; 22 M46 KR; 25 Jagdtiger 8.8 | Stationary intervals include continued fire; some later move. No evidence that parking is a terminal navigation loop. |
| 1 / 13-15, 28-30 artillery | Long firing-position holds include two to five shots. Their role's hold is not a failure merely because they stay put. |
| 1 / 27 BC 12 t; 2 / 13 ELC EVEN 90 | Magazine-retreat holds include later firing and about 500/148 m subsequent travel. Preserve magazine behavior. |
| 2 / 4 Chieftain/T95; 10 KV-4 KTTS; 12 Kanonenjagdpanzer; 22-23 Panthers | Continued firing during engage/support holds; not established permanent movement failures. |
| 2 / 9 T-103; 11 ISU-152; 24 WZ-111G FT | Authored hold/advance, subsequent travel about 247/179/67 m. Do not remove the hold policy. |

The first round has zero Bot detailed-support transitions; the second has one
enable and one disable (`point_support_lost` / `all_points_restored`). Keep
one-invalid/five-valid. Worker averages are about 13.2 and 10.8 FPS respectively;
different maps/load do not establish a build regression. No collision/native
performance rewrite, grids, slopes, targeting, defense, support, crushing
physics or independent test arrangement changes are part of this patch.

The new `test_port_0922_escape_observation_contract.py` suite covers selected
and retained fixed endpoints, forward/reverse/rotated projections, the exact
CDA/Highway graph witness, actual runtime commit/completion/refusal, server
relay -> visible client, mixed batches, malformed negatives, and visible-client
delivery -> dead-player presentation without new LOS. CI includes it explicitly.
These are engine-free contracts and shipped-data replays, not native gameplay
acceptance. The user's new package test must confirm escape behavior and
postmortem enemy rendering on the exact Windows client.


## 040013 follow-up: empty-magazine withdrawal and rotation proof scope

Baseline: `8fcb8fcf`, report `wot-error-report-20261020-040013-afe60b71198a.zip`.
The requested policy now removes low-health withdrawal for every vehicle.
Delete both focused and targetless producers, retire an existing non-magazine
retreat state, and retain the fired/empty/reloadable magazine predicate, cover,
reload completion, attacker priority, finite-traverse aiming and base defense.
Health fraction remains diagnostic data, not a movement trigger.

Emil 10 behind wreck 2 had a rear-laying episode with no movement lease while
an incoming movement order was rewritten to engage/current-position. Install
that lease before rewriting an existing episode's new movement order. Target
changes retain its start, the existing eight-second budget and retry cooldown;
arrival, real departure, explicit holds and cooldown expiry still release it.
`rear_motion_observation` records incoming movement, before/after lease, clock
and seed/active/exhausted/completed/retry-expired outcomes. Removing low-health
withdrawal also removes this report's retreat-versus-laying contention source.
Do not remove legitimate finite-traverse rear laying.

VK 18's requested 12.175/24.351/36.526/48.701-degree recovery poses all received
one 1.872-degree cached native check. Keep each requested arc as its own cache
key and prove the complete stationary arc through the existing read-only
rotation resolver. Split longer arcs into at most three sixty-degree chunks,
below its sixteen five-degree native-slice bound, stopping on the first hard
or commit-required result. Diagnostics distinguish requested/checked extent,
chunk counts, full proof and provisional commit requirements. The actual
moving-body physics commit is unchanged; no teleport or elapsed-time dropping.

Panther 5's baked-pose acceptance contradicted a realised native rotation at
03:59:15.087. For the existing two-second native-refusal lifetime, recheck
candidate arcs even when the coarse pose is green. Keep the normal green-grid
fast path outside this condition and current coarse-missing native review.
Unknown native proof retains the previous safe commit/coarse-refusal behavior.
The report does not prove that all of VK's requested arc was physically blocked.
It does record a later private replan and successful short reverse movements.

Panther 5's 67-to-773-metre strategic turnback came from pressure donor ranking
without transfer distance, followed one minute later by radio-knowledge loss.
Do not change that strategy in this fix. M40/M43 did align and then travel about
96 metres during defense; sparse motion-triggered log rows are not continuous
immobility. Other intentional firing/artillery holds are not removed.

Coverage replaces retired low-health policy expectations, keeps magazine
retreat endpoint and completion checks, and adds independent recovery-fraction
proofs, a clear-first-frame/blocked-later-arc case, signed/wrapped/half-turn
coverage, bounded chunks, native-refusal fast-path expiry, and an inherited
rear episode across enemy changes, budget expiry and arrival. These are source
and adapter contracts; native Windows motion and performance need playtesting.
No pressure policy, slope ranking, grid, support, collision-damage, crushing or
test-arrangement change. One invalid point still enables detailed support;
all five valid points restore basic support.
