# PR119 control-offset correction — November 10, 2026

## November 11 follow-up — current-target HE and front-vehicle admission

The L-120 TD round in `wot-error-report-20261111-173700-f67e91ff6225.zip`
used `colorfulmeans-42987574283-1`. Between 17:34:19.879 and
17:35:10.772 the AP clip did not fire. The player repeatedly handed the
hull to combat targeting enemy 14 with a still-obstructed ray. The report has
50 `auto_front_vehicle` refusals in that round, including blockers 10,
11 and 13. The player learned of those contacts at native trigger
admission, after combat had already taken the hull.

- Mounted player HE checks penetration points on its held vehicle and
  skips obstructed points. It uses the first executable penetrating
  point. After all available points fail penetration, it compares
  estimated non-penetrating blast damage on that same vehicle and
  rechecks the highest-scoring usable point for the trigger. An
  incomplete comparison can only pre-aim. Ammunition return remains
  driven by committed rounds and the native clip reload.
- Before a point can qualify for route-to-combat admission, the intended
  trajectory checks which hostile hull it would strike first. A
  foreground vehicle excludes that point and interrupts its attack
  evidence. A continuously usable ray qualifies after two seconds, and
  the real barrel or hull can finish laying after handoff. The final
  native shot still requires its independent physical check.
- A confirmed wreck, friendly vehicle or world obstruction still enters
  the existing finite recovery for owned combat. The driver, waypoint
  arrival, route selection and capture navigation retain their existing
  implementation. The detailed diagnostic option records front actor
  IDs and the progress and scores of the held vehicle's HE comparison.

The regression suite exercises a moving front hull, a clear alternate
point, the two-second reopen boundary before physical alignment, a later
penetrating ordinary-HE point, and unequal native blast scores. Its HE
cases also cover obstruction, target retention and the distinction
between potential penetration and non-penetrating blast damage.

### Intermediate Windows HD #1513 verification

[Windows build 43004424175](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/43004424175)
packaged runtime `0f959debb5153c8093de7baa66bb1cd6fe4147c0`.
Artifact `13847748397` has build identity `colorfulmeans-43004424175-1`.
The downloaded ZIP, embedded client ZIP, x64 launcher and 263 packaged
Python 2.7 modules were independently checked before the launcher was
used to install and run the build.
[Tests 43004427958](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/43004427958)
passed at the same runtime commit, including the navigation, bot,
client, Windows launcher and native geometry jobs.

- L-120 TD / PFM-42 with `_20mm_pvlvkan_m_40` and 80/80/80 stock,
  Mittengard team 2, stationary-target preset. The first handoff took
  2.021 seconds with the gun still unaligned, and the first AP round
  followed 1.705 seconds later. The detailed records excluded samples
  on enemies 2 and 14 when the intended ray met enemies 5 and 7 first.
  Another AP round followed the last such record in 1.448 seconds.
  The report contains one route handoff and zero late front-vehicle
  refusals.
- In the same round, the launcher test control loaded ordinary HE with
  automation released. Automatic fire evaluated all nine eligible
  points on enemy 7 before fallback. It used different points on that
  same vehicle through the 20-round clip. The next clip used the
  lowest stocked penetration shell, APCR, since AP was exhausted.
  The 138 committed projectiles all matched server shots. The visible
  and worker exception trails were empty. Report
  `wot-error-report-20261111-185105-7d3070a546b4.zip`.
- Škoda T 24 with `_75mm_Skoda_A18` and 17/17/16 stock on the same
  map and preset reproduced a remaining HE ownership loop. It made
  five confirmed handoffs to enemy 2 before the first shot. Immediately
  after handoff, the running penetration review stopped publishing its
  still-clear HE contact, so the existing opportunity-loss grace period
  expired during the sweep. The same battle later compared four clear
  points on enemy 2, chose sample 8 with an estimated blast of 69 over
  the other three at 0, and fired that point twice before returning to
  AP. Report `wot-error-report-20261111-185617-4df4afa1ed92.zip`.

The follow-up lets the current, unblocked HE contact continue to support
the already confirmed stop while the same target is being reviewed.
It still needs the complete ranking to fire a fallback shot. A fresh
blocked line cannot retain that proof. The first follow-up still lost
the opportunity during small source changes in
`wot-error-report-20261111-191311-dcf5614e43fa.zip`. The earlier armour
failure was valid within the ranking tolerance, so blocked points took
both foreground probes while the clear point's exact lane expired.
The final change gives that point the first available foreground probe
and applies the normal obstruction checks to the refreshed ray. The
native-observation regression reproduces that release and requires one
handoff followed by a real HE launch with the completed ranking.

### Windows retest of the HE handoff

`wot_PR119_1d45aa54_Windows_2026-11-11.zip` uses runtime
`1d45aa54a8809d2affd637393214e968bbd10270` and build identity
`local-qa-1d45aa54`. The ZIP reuses the verified x64 launcher, server
and native resources from Windows build 43004424175 with the updated
CPython 2.7 client modules. The outer ZIP, inner client ZIP and mod
passed archive checks. The complete inventory of 263 client bytecode
modules matched the runtime source. The acceptance run used a fresh
extraction of this same ZIP. [Runtime Tests 43010296857](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/43010296857).

The same T 24, map, side and stationary-target preset reproduced
foreground obstructions on enemy 2. The report shows one HE handoff
for that enemy after 2.021 seconds of confirmation while the gun was
still unaligned. Enemies 3 and 5 obstructed eight of the nine samples
at fallback selection. The gun used the remaining sample, 5, for
both HE shots and returned to AP. The first HE shot followed handoff
in 4.891 seconds. All 12 local launches matched the server, with no
late front-vehicle refusals and empty visible/worker exception trails.
The later handoff in this capture was for enemy 7 with AP.
Report `wot-error-report-20261111-191748-abfd2a01065b.zip`.

### HE return after two consecutive fallback rounds

The return to the lowest stocked penetration shell now counts
committed HE rounds by the mode of their accepted trigger. A
penetrating HE round resets the consecutive fallback count. A
single-shot gun uses the lowest stocked penetration shell for the load
after the second consecutive fallback round. A clip or burst gun
finishes the mounted clip once that threshold is reached. A still-valid
complete failure certificate for the lowest penetration shell defers
the change, and stock exhaustion still selects a stocked shell.

The last native trigger can stage NEXT for its confirmed HE fallback
mode, and the native gun promotes it only on the actual reload
boundary. A refused trigger releases that provisional setting and
spends no round. An existing manual selection retains its own
ownership. The code uses the current trigger and committed burst
receipts with no extra armour scan at the trigger.

Regressions exercise a penetrating HE round between fallback rounds,
continued penetration across a full clip, two fallback rounds
followed by penetration in the remainder of the same clip, a refused
second fallback trigger, actual burst tails, and the cached complete
failure proof that defers the lowest-shell return.

The delivered `wot_PR119_845d87b3_Windows_2026-11-11.zip` contains
runtime `845d87b378be5a26886c285c2e7cd5e1281bbc8a` with identity
`local-qa-845d87b3`. It uses the same verified x64 launcher, server and
native resources. All 263 bundled client modules matched the runtime
source. All 39 local player-control and report-regression test files
passed. [Runtime Tests 43012626933](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/43012626933).

The T 24 acceptance run started from a fresh extraction of that ZIP
with the same stationary-target setup. The log excluded the blocked
samples on enemy 2 and compared the four clear points. Sample 8 won
with estimated blast damage 80. The other three scored 0. Both HE
rounds used sample 8. The first trigger kept HE with zero preceding
fallback rounds. The second trigger had one prior committed fallback
round and began the AP reload after its own commit. The third
projectile was AP. All 16 local projectiles matched the server, and the
visible and worker exception trails were empty. The capture contains
no repeated HE takeover and no late front-vehicle refusal.
Report `wot-error-report-20261111-193538-ba5271e3f0c1.zip`.

The first PR test run exposed a wall-clock dependency in the 141918
wreck regression. A slower runner paused during penetration review.
The fixture now uses a repeatable native work clock to reach a
partial blast comparison in the first callback, before admission.
The route, turret, native reload, no-fire and wreck evidence
assertions still run through the same production code.

## Follow-up for the 15:47 T 24 report — native fire receipts and ammunition return

The single-shot Škoda T 24 report `wot-error-report-20261111-154736-4f1e0a10cc53.zip`
ran `d5a9ff9f` / `colorfulmeans-42955381063-1`. It first handed off
at 15:42:33.438 and fired at 15:42:53.357. It recorded 21 front-vehicle
refusals and 21 native calls without a receipt. The stock HD #1513
`PlayerAvatar.shoot` starts its acknowledgement timer and its two-second
gun-command deadline after the local mailbox returns, including after a
refusal. The old rejection cleanup cancelled the timer alone. The
new cleanup restores the pre-call deadline for that same rejected
mailbox, fenced to the Avatar, generation and local projectile sequence.
Exact CPython 2.7 bytecode inspection and a regression cover both waits.
The detailed diagnostic checkbox adds the early missing-context reason,
same-point refresh refusal and stock gun/HUD state for a silent return.

- Ordinary player route acquisition requires two seconds of continuous
  attackable evidence. The no-HE handoff starts its independent five-second
  cooldown. The change is at the existing combat admission boundary.
- The five whitelisted HESH pairs review the held target's penetration
  points and take its first executable point. A completed failed HESH
  review uses one fallback point on that target. Ordinary HE uses a
  single point for both its penetration trial and fallback.
- High-penetration and HE single-shot loads queue the lowest stocked
  penetration shell for the reload after two committed rounds. Clip
  and burst guns change at the native full reload after the current clip.
  Existing, still-valid complete negative evidence for the lowest shell
  defers that return. The next load uses current cached evidence and the
  existing geometry tolerance. It issues no fresh armour queries at
  the trigger. An empty stock or a complete current-shell failure can
  still select a replacement before the quota.

### Windows HD #1513 evidence

[Windows build 42987574283](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/42987574283)
built runtime `3dc4132c72e5e6c7a3f7207545aa3983ae53cc3b`.
Artifact `13841156147` carries build `colorfulmeans-42987574283-1`.
An independent download passed all ZIP checks, x64 launcher inspection
and the comparison of 263 packaged Python 2.7 client modules with the
runtime source. The following sessions used the downloaded launcher.

- T 24, `_75mm_Skoda_A18`, 17/17/16, Mittengard team 2. After a slow
  opening around parked allies, the first qualifying handoff completed
  in 2.005 seconds and led to an AP launch 3.424 seconds later. The
  report contains 38 matching local and server launches and eight
  physical front-vehicle refusals. The first refusal at 16:48:35.033
  reached the next native check at 16:48:35.391. The next committed AP
  shot followed at 16:48:40.970 after further blocked/pending points.
  No attempt returned without a receipt in this capture.
  Report `wot-error-report-20261111-165102-bd0400ab00e0.zip`.
- T 24, same gun and stock, Mittengard team 1. The native test command
  loaded APCR while control was released, then the normal control loop
  admitted after 2.020 seconds and fired after another 0.637 seconds.
  The actual sequence was APCR, APCR, AP. A second control activation
  with HE produced HE, HE, AP. The two HE launches both used target 24
  and sample 0. All six were received by the server.
  Report `wot-error-report-20261111-165723-e79f8ba283bb.zip`.

- AT 7, `QF_6_pounder_Mk_V_AT`, ten rounds per clip and 40/40/40
  stock, Mittengard team 1. Route confirmation completed in 2.023
  seconds. The native APCR launch followed 2.462 seconds later.
  The server recorded ten APCR rounds before the reload and one AP
  round from the next clip. The capture ends after the test stopped
  automatic control. Report `wot-error-report-20261111-170514-b9a35684ac43.zip`.

The visible and worker exception trails contain headers only in all
three captures. The Windows battles exercised the ordinary HE and
penetration return paths. The five HESH identities, the scoped fallback
and the expiry of the lowest-shell failure proof were exercised by
the native-observation regressions. The first full CI run found two
files that still expected the old five-second route handoff. The
follow-up adjusts those fixtures and preserves their control and
capture assertions.

## Follow-up for the 11:28 AT 7 and 11:44 Škoda T 24 reports

Both reports identify `5d82c2b2` / `colorfulmeans-42894631616-1` and
record zero player launches. The ten-round AT 7
`QF_6_pounder_Mk_V_AT` in
`wot-error-report-20261111-112828-ef1151939b8a.zip` had a clear
penetrating ray for enemy 23, sample 5, which still needed a hull turn.
The last route receipt recorded 0.557 seconds of confirmation. The
single-shot turreted Škoda T 24 in
`wot-error-report-20261111-114425-6fa3861491cd.zip` had a clear,
penetrating and mechanically reachable AP point on enemy 23, sample 7,
at 11:44:00. Both switched to automatic capture travel before the
five-second confirmation could complete. The travel-mode transition
suspended combat review in both reports.

On a moving source, the mounted-shell firing sweep repeatedly revisited
the first obstructed contact as the exact muzzle changed. The existing
bounded foreground review now rotates across mounted-shell points before
movement admission, with the current positive ray first on the next
observation. A clear, penetrating ray can qualify while its hull still
needs to turn. Automatic travel to the capture circle participates in
the same confirmation, retaining the original destination up to
handoff. The five-second gate and native firing checks apply at their
respective stages. The detailed checkbox records each sample's mechanical
result and stationary projection reason.

Full control-loop regressions use a ten-round limited gun and a
single-shot turreted gun behind an obstructed nearer enemy. They require
the original travel order during confirmation, one combat handoff after
five seconds and a real native AP launch after aiming. A capture-route
case crosses from its authored route into capture travel during the
same confirmation while the tank remains outside the circle.

## Follow-up for the 02:25 AT7 report — mounted shell and same-target points

`wot-error-report-20261111-022506-022abba6ab9f.zip` showed an admitted
engagement with ten AP rounds remaining and no launch during a 46-second
hold. Native first-trigger admission identified hostile actor 1 in front of
actor 3 on several separate samples. A timer let the same blocked sample
return to the front of the old global review even while the blocker remained.
The report also showed a grounded final route-circle observation during
combat ownership followed by a return to its centre on handoff.

- The ordinary foreground gun opens a pass with its retained eligible target
  or the existing nearest-visible ordering. Ties use nominal armour and the
  existing stable actor key. It inspects the mounted penetration shell one
  target at a time, skips obstructed samples and consumes the first current
  executable point. A front contact is recorded against its obstructed sample
  and geometry. Native first-trigger admission still checks the live barrel.
- A completed mounted-shell pass qualifies the next stocked higher penetration
  shell and permits a native whole-clip reload. Exhausting those roles selects
  HE on the last target. Current HE uses one sample for penetration and its
  contact fallback. A fired HE round or the last round of its clip queues the
  lowest stocked penetration shell by inventory alone. The physical burst
  and manual ammunition setting keep their existing ownership.
- A no-HE release starts a five-second cooldown from the actual handoff. A
  fresh continuous attackable observation can accumulate in parallel on the
  original route. A grounded entry into the assigned terminal disc is recorded
  while combat owns movement. Authored route data, intermediate arrival
  checks, base occupancy and the underlying driver remain separate.
- The ordered policy applies to ordinary player-controlled guns, including
  fixed and limited traverse. Worker, artillery and native siege actuator
  paths retain their existing policies. Analytic regressions cover exact
  launch, native ammunition input, trigger tails, route inputs, and real
  motion invalidation alongside negligible source settling.
- The existing detailed-diagnostic checkbox enables `ordered_attack`
  records with loaded shell, target order, completed count, selected sample,
  proposed shell and the current target's point verdicts. These records help
  separate missing native geometry, mechanical restrictions and obstructed
  points in a fresh Windows battle.

The first #1513 preflight used the team 2 east route in the same Mittengard
stationary-target scene. The exported report `wot-error-report-20261111-042019-0aa0ba72934c.zip`
records eight AP and one HE launch. When actor 2's points 1, 2 and 4 were
obstructed, the next committed AP shot used point 5 on actor 2. The later
HE fallback fired point 0 on actor 9, and its native reload mounted AP.
The follow-up retains the earlier out-of-range review receipt without
granting firing or movement permission. It also distinguishes the fired
shell from the shell mounted by the same trigger's reload in the detailed log.

## Follow-up for the 23:53 AT7 report — circle handoff and current shot

The report `wot-error-report-20261110-235323-94c3a3f842a5.zip` identifies
`ef5b7cca` / `colorfulmeans-42842677225-1`. It exercised the five-second
route gate and a committed AP shot after manual HE-to-AP. HE stayed at ten
rounds during a roughly 51-second engagement despite verified aim and
permissive orders. Capture scoring began at 23:51:24, the original route
resumed inside the circle at 23:51:39, and the vehicle held near the end of
the lane at 23:51:44 without a firing target. The capture hold itself was
registered at that stop.

- The shared planner records actual circle occupancy independently of
  combat's movement lease. Eligible route orders carry the capture objective
  so each binding can accept entry from its current grounded pose even on
  a cached order. The circle hold owns translation and leaves the existing
  gun handoff available. A blocked initial hint cannot veto travel from a
  completed route terminal outside the circle. Actor-local circle entry
  constrains the accepted ordinary order after mission selection, so it
  cannot create a new mission or displace a controller-owned task.
- The mounted shell takes a still-valid selected or cached executable point
  before issuing new point queries. NEXT's bounded preparation runs after
  current-shot control during the reload before the final in-clip trigger.
  A ready gun uses the ordinary fair background pass. The last trigger
  consumes a prepared plan, with
  existing ranking tolerance for an already accepted queue and live lane
  and domain checks. The existing native launch admission proves the shot.
- The launcher checkbox **Collect detailed diagnostic logs** explicitly
  enables the new `BATTLE REVIEW` stages for direct-fire gates, trigger
  context and native submission, last-trigger NEXT, current-point
  invalidation, and capture handoff. The checkbox is independent of other
  settings that enable general diagnostics. Records reuse observed facts,
  summarize repeated reasons, and share the existing review limits.
- The regressions compare actual drive commands with and without fire,
  require forward travel in the clear-route fixture, and exercise a living
  enemy, the real five-second dwell, entry on a cached route order, and a
  subsequent committed shot at zero throttle. The tests also cover cached
  green-point priority, an expired NEXT plan without trigger-time scanning,
  an HE magazine into AP, manual HE-to-AP, and diagnostic opt-in.

On Windows #1513, enable the checkbox before launching. Recheck the AT7
entry and parked fire, first HE launch, and the final round of a cassette.
Export the report after the match. Use the direct-fire and NEXT stages to
identify the missing native HE step and distinguish load ranking from
current-shot refusals. The current penetration-cache motion envelope awaits
measured deltas from that report. The PR identifies the verified build.

## Follow-up for the 22:01 AT7 report

The report \`wot-error-report-20261110-220155-71db166b8729.zip\` identifies
\`3c6deb7e\` / \`colorfulmeans-42817074658-1\`. Its AT7 stayed at the same
horizontal position from 21:58:31 to 21:59:33 while the shared engagement
episode went from 9 to 369. Actual commands alternated route turn -1.00 and
combat turn about +0.65. A briefly clear ray could start laying with unknown
armour. The next blocked ray returned to the route and the following clear
ray recreated the pivot. The early route-only collision wait is separate.

The last HE round produced \`higher_rank_pending\` (2/14 current HE-rank
checks) followed by a native same-shell reload. NEXT was empty in all 22 HE
status samples. The HE phase recorded 1,510 source-proof revocations. A
manual CURRENT change later loaded 10 AP rounds, but the preceding HE
fallback phase left the gun in \`he_damage_comparison_pending\` after reload.

### Contract and implementation

- A normal player-controlled automatic route remains the movement owner
  until one enemy has a proved opportunity with the current shell for five
  continuous observed seconds. An invalid, absent, or changed opportunity
  resets the timer. The timer also resets after a gap longer than 0.75 s.
  Current HE contact must satisfy the existing HE fallback law. A verified
  stationary projection can qualify a limited traverse point. An in-motion
  hull-lay candidate may also qualify from a clear ideal ray and a confirmed
  plate or the legal one-point ordinary HE contact. The ordinary native
  actuator still checks each physical turn.
  A clear ray with unknown armour, or a translated line preview alone,
  grants no route takeover. Worker tactics, explicit travel/capture and the
  separate hydraulic siege request/echo protocol keep their existing scope.
- For an admitted route-derived pivot, brief observed lane blockage freezes
  the turn and removes fire permission. After one second of lost opportunity
  the route resumes. Reentry requires a new full five-second observation;
  an unchanged failed rotation or stalled lay cannot repeat from the same
  location. The existing six-second mechanical watchdog still runs while
  checking the lane and only actual turn progress refreshes it.
- NEXT keeps completed ranking evidence anchored to its measured geometry.
  The experimental limits are up to 0.20 m of source/target movement (stricter
  near the target), 0.5 degrees of target/component rotation, and 0.15 m/s
  change in target velocity. Changes in weapon, target geometry/armour
  identity, scene, or a relevant moving blocker invalidate the corresponding
  evidence. A known failed plate or a static world hit can retain its rank
  outcome across traffic changes. Unchecked/blocked armour does not qualify
  global HE fallback. Tolerant NEXT observations are kept out of the exact
  physical failure diagnostics. The winning point is freshly checked before
  queuing NEXT, and current aim/fire still uses exact geometry and the
  original native shot-admission checks. No query quota is increased.
- A real ammunition change clears the previous shell's fallback and lay
  retry state. Queuing a future shell or continuing a same-shell reload does
  not reset the current shell phase. NEXT remains independent of the
  current clip and keeps HE penetration, AP, higher-penetration, HE fallback
  order. An unfinished ranking grants no current clip unload authority.

### Verification and native acceptance

The report regression exercises a real authored route through the five-second
gate, clear/blocked alternation, a sustained limited-traverse opportunity,
a full ten-round HE clip with source jitter and actual AP reload, and a
manual CURRENT HE-to-AP input followed by the actual AP launch. Controlled
queries also verify expiry beyond the ranking envelope and the requirement
for fresh winning-point proof. Existing downstream fixtures that assume an
eligible engagement isolate the route-dwell decision in their setup; the
report and embedded ownership regressions use the production threshold.

On Windows #1513, compare a brief spot with a sustained attackable point on
the same AT7 opening. Check that brief peeks preserve route direction and a
stable contact takes the hull once. Repeat at a wall and with an intervening
friendly, then let one HE cassette finish and separately switch manually to
AP. The PR delivery header identifies the exact CI run and Windows package.
All lower-level driving, traffic, navigation, route, physics, and collision
files are outside this change.

## Live-report continuation: implemented and locally verified

The user's `wot-error-report-20261110-184606-069fba6421d8.zip` rejects the
in-battle completeness of the previous delivery. Its installed and bundled
build is `colorfulmeans-42796652971-1`, the actual `2f8db7b6` PR head, not an
older package. The current continuation starts from that exact remote commit.
The prior verification results below remain historical evidence, not proof
that the reported control and HE failures are fixed.

The reviewed report and production-order reproductions identify three issues:

- An unchecked blocked-point recovery can first take the hull, face the
  enemy, fail and release the route. A route-only yaw change can then admit
  the same failure again. Opening-route controls alternate between opposing
  turns even though the original driver and route laws were not edited.
- A valid limited-traverse native hull lay can be replaced by a candidate-less
  stationary-review wait. Exact physical-source changes invalidate evidence;
  review then freezes the admitted hull instead of continuing the same lay.
- Loaded ordinary HE contact review receives only the budget left by repeated
  penetration review. Current-source jitter can retire background contacts
  before consumption; even a completed historical coverage count is not a
  current executable contact.

The user has now authorized implementation, independent review, original-PR
update and a fresh Windows test package after reading the handoffs and dialog.
The controlling rules are:

1. Loaded HE reviews current HE penetration, then its legal HE fallback,
   before AP and higher-penetration alternatives. Ordinary HE penetration and
   fallback share one stable sample per target. Whitelisted full-validation
   HE keeps its existing point domain. Non-HE selections use the ordinary
   HE-penetration, AP, higher-penetration, final-HE-fallback ranking even when
   the physically loaded shell is the higher-penetration one.
2. Validation order does not grant a new unloading authority. Current valid
   rounds/cassettes and accepted trigger tails retain their existing ownership;
   independently reviewed NEXT chooses the subsequent load. Loaded HE cannot
   be discarded just because a different shell has a better NEXT plan.
3. A proved legal current ordinary-HE contact can execute without waiting for
   unvisited or pending competitors. Completed usable candidates remain
   damage-ranked. This supersedes historical wording which makes a complete
   all-enemy HE comparison a prerequisite for ordinary CURRENT execution;
   it does not remove the independent NEXT or SPG validation requirements.
4. Scheduling progress and point intention survive exact proof refreshes.
   They are not negative-armour certificates, movement permission or fire
   permission. Current geometry, ammunition and native first-edge checks stay
   strict; work quotas and the penetration threshold are not increased.
5. Before initial recovery takes a route-owned hull, it needs a current
   executable point, a justified native stationary lay, or a concrete checked
   same-point recovery destination. The existing native siege mode-entry
   protocol remains a separate, narrow authorization; it cannot grant a shot
   or an unchecked relocation. A blocker or pending probe alone cannot stop
   or steer the vehicle. Relevant changes may schedule another check; only a
   newly proved action, not a yaw threshold, admits another episode.
6. An admitted same-point native lay continues through planning waits using
   the original live actuator and collision checks. Manual/task/capture
   restrictions, identity loss, actual completion and real lack of progress
   remain terminal boundaries. A stale steering value is not replayed.
7. Friendly line obstruction joins the same point-bound recovery. Its old
   independent side-choice, arrival-success and retry owner must not survive
   as a fallback. Physical ally collision and firing-safety checks remain.

No driver gain, steering speed, authored route, navigation law, damage model,
eight-second penetration search, extra controller, main merge, tag or release
is authorized. Modified regression expectations must name the superseding
rule; old-source failures and final-tree results are recorded separately.
Implementation and independent cross-module review are complete. The frozen
runtime passes the final local inventory below. The original PR's current
delivery section records the exact commit, same-commit CI outcome, artifact
identity and downloaded-package hashes; historical delivery entries below
must not be used as the evidence for this continuation.

### Implemented boundaries and review findings

- `CombatStop` separates an unadmitted inspection from actual motion
  ownership. The original route remains in control while future positions
  are being queried. A completed failed inspection cannot gain ownership
  merely because the normal driver changes yaw. A checked destination, a
  genuine newly opened same-point native lay, or another current legal point
  can create the next episode. The failure latch is not global to all targets.
- An admitted pivot retains its exact target and point through planning
  waits. Both the contact ID and the aim/face point are rebound before the
  ordinary live-target overlay, eliminating a second target's opposing turn.
  Physical progress, rotation refusal, task cancellation, target loss and
  current gun identity remain live boundaries. Missing geometry does not
  replay an old steering value, and continuing a pivot never grants fire.
- Current ordinary HE's qualified local contact work uses the existing
  foreground or same atomic slice before unrelated unknown penetration work.
  Historical damage hints are rechecked exactly. A high-damage hint whose
  current check is pending can yield to a current executable contact without
  converting the pending target into a zero-damage or armour-failed result.
  A newly proved current HE penetration still precedes an uncommitted fallback.
- Finite inspection progress is no longer keyed to the raw source position.
  Exact source poses still revoke all old positive and negative physical
  evidence. Future-position chord work freezes one explicit hypothetical
  source pose for the same destination, shell, target and point; it is never
  a current firing proof. Changed target/component/domain/lane observations
  restart it. Cancellation or replacement during the final native callback
  cannot publish the old plan or destroy a replacement task.
- Friendly obstruction uses the same selected-point task. The independent
  friendly side-choice, retry timer and arrival-success owner, its consumers,
  and the obsolete gun-angle adjustment/rejection store are deleted rather
  than left as fallbacks. Native ally collision and final shot-lane refusal
  remain. BOT death retires its shared control binding while preserving
  already committed launch records; object identity protects a replacement
  binding from an old close callback.
- The integration run caught and repaired a siege-mode admission regression
  introduced by narrowing ordinary recovery ownership. Clear native mode
  admission and explicit attack authority use the existing request/echo
  protocol. A cold wall or single-feature controller cannot acquire a new
  hull/mode permission. Existing siege and full-controller assertions are
  retained. Reload/switch intents are not reinterpreted as failed hydraulic
  geometry or a reason to discard an accepted movement task.

### Regression provenance and scope

New files cover policy scheduling, actual native future-ray work, shared
recovery liveness, BOT friendly recovery/lifecycle, and the reported opening
route plus loaded-HE execution chain. The latter uses the real shared policy,
driver, native evaluator adapter, trigger admission and ammunition accounting
with controlled native observations and deterministic query cost. Its HE
regression reached an actual committed shot and exactly one round deduction,
not merely an `aim` decision. This is still not a Windows #1513 playtest.

Pre-fix failures were retained for HE budget starvation, source-jitter review,
native lay loss during planning waits, unchecked cold recovery, pending
high-damage hints, future-ray progress, final-callback task cancellation,
target/sample mismatch and source-BOT death. A first draft of the live HE
fixture reused the source entity ID for an enemy; that fixture error was
corrected before the valid no-shot baseline was recorded and is not claimed
as a production defect.

Existing tests were migrated only where their expectations required retired
friendly APIs or admitted unchecked blockers/yaw-only retries. The new
expectations require unchanged actual route inputs until a checked goal.
Stationary-domain tests first establish a legitimate current-point combat
stop before testing a planning wait; they no longer depend on freezing an
already admitted pivot. Their negative-domain and no-fire assertions remain.
The original HE damage-ranking, penetration threshold, NEXT unknown-domain,
siege and controller tests are not weakened to hide failures.

The source diff leaves `ai/driver.py`, `ai/navigation.py`, `ai/traffic.py`,
`tank_collision.py` and `vehicle_control/route_tasks.py` unchanged. The only
`native_motion_core.py` change removes a write to the deleted friendly store.
No new test skip, query-budget increase, steering gain, collision bypass,
early current-HE unload, eight-second search or second recovery owner is added.

### Final local verification

Python 3.11.9 used the CI-pinned Pillow 12.3.0, NumPy 2.3.5, ModernGL 5.12.0
and glcontext 3.0.0 dependencies. The final complete run started after all
production and regression edits were frozen, and each test file ran in its own
interpreter to prevent native test doubles leaking between files.

| Gate | Observed result |
| --- | --- |
| Complete client inventory | 529/529 files passed; 10,721 reported tests, including 9 existing environment/resource skips |
| Complete launcher inventory | 49/49 files passed; 1,328 reported tests, with 170 recorded platform/display/resource skips |
| Shared-control ownership checker | 89 tests passed |
| Client source syntax under local Python 3.11 | All 262 modules compile; this is not the Python 2.7 package gate |
| 29-actor analytic shared-control workload | Completed; no-enemy case: 0 launches; mixed AP/HE case: 62 measured launches and 633 armour batches |
| Whitespace/integration diff | `git diff --check` passed; no remaining unstaged runtime edit |

The 29-actor workload recorded an unchanged runtime fingerprint before and
after execution across the 261 files in `offline_lan_0922`:
`afed59ce20df6639c5f44b34ce751ed1f0377443412df474fbc3840ec571db38`.
Its geometry is analytic and its timing is not a Windows-client FPS estimate.
Focused test totals overlap the full inventory and are not added to it.

The unchanged CI workflow must still compile and test with real Python 2.7,
rebuild the shipping x86 native module, compare every packaged client code
object with the same checkout, and build/run the extracted Windows launcher.
Delivery additionally compares the downloaded launcher's bundled Python
sources, build identity and nested client/wotmod bytes with that same run.
The exact post-build attestation belongs in the current PR delivery section,
so this handoff does not invent a future run ID or self-referential commit SHA.

### Native acceptance still required

Use the fresh artifact identified in the PR, not the rejected
`colorfulmeans-42796652971-1` package. The user's next playtest should check:

1. The same AT7 opening route with drive and fire enabled: no unchecked
   enemy inspection may alternate opposing chassis turns with navigation.
2. A target outside the actual gun arc: the original native hull actuator
   should continue the same accepted point through policy review waits.
3. Loaded ordinary HE: a legal current contact should reach an actual shot,
   while NEXT remains independent and does not unload the current cassette.
4. Current high-penetration ammunition: subsequent loading follows verified
   HE-penetration/AP/high-penetration order, not permanent loaded-shell bias.
5. World/friendly obstruction and arrival: retain the same point, revalidate
   at the actual destination, and return the original route on finite failure.
6. Capture/manual/return-base and target death: old movement/gun intentions
   must end without cancelling already committed projectile records.

No new exact Windows #1513 battle or subjective steering smoothness is claimed
by the local tests. Report the installed build identity with any remaining
opening-route, HE, recovery, turret-continuity or frame-pacing failure.

## Historical delivery record

## Authority and starting point

This continuation starts at the original open PR #119 head `d149aadc`, not
the older `D149AD` comparison as a new fork. The user's November 10 review
separates two previously conflated mechanisms:

- the eight-second search *after negative penetration review*; and
- the independent BOT `_gun_angle_order` which tried forward/reverse positions
  around eight **metres** away without proving the gun's selected aim point
  from those positions.

The old eight-second improvement search is removed, including its policy
action, eligibility, timestamps, movement proposals and shared-control special
cases. This is not a zero-second timer. Neither the existing native hull-turn
actuator nor the ordinary route/traffic/ground/collision laws are deleted.
The earlier `shared-he-recovery-contract-20261110.md` and November 9 handoffs
remain historical records; their claims that this eight-second search remains
active are superseded by this review.

## One aim-point owner and physical handoff

`AttackPolicy` chooses the current target, shell, mode and sample. When a
currently reviewed penetration/HE sample is physically blocked or outside
the installed gun's arc, `CombatStop` carries that **same** candidate into one
finite physical recovery episode. It does not ask another module to find a
generic nearby shooting position or reselect an aim point on arrival.

1. An actually executable stationary native hull/hydraulic lay takes priority
   over translation. Stationary review and its pending observations do not
   manufacture a new destination.
2. A genuinely blocked same-point candidate can request projected positions.
   Each position must pass normal navigation checks and the native evaluator's
   future line of sight for the **same shell, target and sample**. Partial
   native queries remain pending; a destination preview never grants fire.
3. The ordinary physical driver executes only the checked destination. The
   phase survives unrelated new candidates and macro target hints. The gun
   target and drive target are both rebound to the phase's original target.
4. Reaching the destination only requests current-pose revalidation. The
   original actual barrel, lane, armour/HE and trigger-admission checks remain
   separate. A recent planned solution cannot stand in for a launch proof.
5. Finite destination exhaustion or a six-second lack of physical progress
   retires the combat movement lease, clears its stopping/turning instructions
   and returns the authored task order. The same failed pose cannot acquire
   the identical task every callback; material source/target motion or fresh
   executable native evidence can open a new episode.

`bot_runtime._gun_angle_order` and its obsolete combat-order call are removed.
The original rear-laying contact and movement safety mechanisms are retained
where they still have independent physical uses. The common combat lease
prevents a separate rear pursuit from co-owning movement.

Capture/parking/explicit travel keep their original translation authority.
An already-occupied capture position may turn a limited gun in place only
after a valid native primary-target laying proposal. A wall-blocked capture
hint cannot steal that hull turn. Mission cancellation clears retained gun
intentions before the next cached physical slice.

## Ammunition and trigger ownership

- With a complete negative penetration review, an available HE fallback is
  considered **immediately**, without an eight-second motion search. A
  verified penetrating shell still fires normally; unknown geometry never
  certifies negative armour.
- Ordinary HE applies its one-point-per-enemy penetration trial to fallback
  contact comparison as well. Only whitelisted high-penetration HE/HESH retains
  full weak-point validation.
- The physically loaded HE round/clip can execute a verified legal current
  contact even when a different enemy remains under review. Independently
  completed `NEXT` evidence selects only the subsequent load; it cannot
  unload or preempt an already admitted current HE trigger.
- HE contact failure may terminate the engagement only after actual complete
  native no-contact evidence; world/friendly blocks and unknown geometry are
  not fabricated no-contact certificates. Actual zero-damage contact remains
  a legal result.
- Retained gun intention only preserves *which point to re-aim at*. Every
  physical first trigger still needs a fresh actual-pose, actual-lane and
  ammunition proof. Dead/despawned targets cannot remain in cached aim input.
- The first-trigger native `auto_world_blocked` receipt now identifies whether
  the hit was on the actual **centre** barrel path or the **scattered** path.
  A centre-path or confirmed wreck obstruction invalidates that point's
  present lane and may request recovery. One scattered ray striking nearby
  geometry refuses that particular trigger with no debit, but does not turn
  an otherwise clear centre point into an automatic movement task. Its next
  trigger still repeats the entire native admission; no shot proof is cached.

## Verification boundaries

Host CPython tests exercise the real shared source with native-observation
fixtures, not Windows BigWorld itself. The frozen local source passed:

- Complete client test inventory: **524/524 files**, **10,666** executed
  methods (**10,657 passed; 9 skipped; 0 failures**).
- Complete launcher inventory: **49/49 files**, **1,328** executed methods
  (**1,158 passed; 170 host/platform skips; 0 failures**).
- The earlier separate `test_player_*.py` pass: **882/882** tests (before
  the additional scatter-refusal regression was added).
- `test_shared_*.py`: **277/277** tests.
- `tools/check_shared_vehicle_control.py --check`: **89/89** tests.
- Capture/contact handoff: **11/11** tests; complete navigation receipts:
  **22/22** tests.
- The 29-actor real worker-scheduling analytic workload committed **101**
  measured launches with exactly matched ammunition debits and no background
  work-quota violations. Its mixed-control CPU mean was **119.320 ms** per
  analytic 100 ms callback on this host; this is not game FPS or a guaranteed
  performance gain. The benchmark now reports the actual point recovery and
  HE fallback state instead of reading the deleted search timer.

The first full client run produced two *environment* errors: the partial
Git clone lacked historical `19d79b1` map blobs referenced by the unchanged
Great Wall and tactical-route tests. Fetching all 42 map blobs restored their
actual historical fixtures. Direct reruns passed **2/2** and **20/20** tests,
respectively. The subsequent full **524/524** source-tree run passed with no
changes to those tests or the routes. The first errors are preserved in the
local logs; they are not reported as a production navigation defect or hidden
from the verification history.

### First GitHub CI caught a real HE scheduling fault

Run [42786557537](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/42786557537)
on head `e222f7b3` completed navigation, native geometry, Windows server/editor
and BOT regression jobs successfully, but its 524-file client job found three
failures in `test_shared_current_he_execution.py` (one failed test file;
the other 523 passed). Its Windows launcher job was consequently skipped;
**no Windows launcher artifact from that run is a valid delivery.**

The CI runner's slower 8 ms native observation slice finished the lower-damage
HE target 14 while the also-negative-armour target 2's higher-damage contact
still had a real `atomic_frame_budget_exhausted` receipt. The policy published
an irrevocable CURRENT aim lock on target 14 before the second comparator
could obtain its fair callback. The outcome is reproducible locally with a
virtual atomic clock that consumes precisely the original wall-clock budget.
This is a genuine first-trigger ranking defect, not a missing fixture, CI
network error, or reason to weaken the three existing expectations.

The follow-up fix postpones **only that first lock** while a currently
penetration-qualified competitor has an explicitly native-budget-exhausted
HE comparison. Its unfinished query must receive an ordinary future slice;
there is no replacement movement timer, extra quota or assumed damage.
A competitor that truly returns `pending`, disappears, changes pose or lacks
positive penetration-failure qualification must not hold an independently
executable loaded HE hostage. Existing tests asserting those distinctions
remain unchanged and pass. New
`test_expensive_second_he_contact_cannot_lock_a_lower_damage_first_target`
forces the budget-expiration schedule without sleeping or stubbing the actual
evaluator. The 23-file shared-control test inventory passed after this fix;
the exact CI Python 3.11.9 dependency set then passed the **entire 524/524**
client file inventory: **10,667** methods, **10,658 passed, 9 skipped, 0
failures**. The standalone 89/89 shared-owner checker also passed. Two fresh
29-BOT worker10 native analytic schedules passed their original quota and
ammunition constraints with respectively **100** and **101** launches and no
background quota overruns; those variable wall-limited counts are not FPS.
The fresh Windows Python 2.7 build and exact downloaded launcher remain
separate CI gates.

### Follow-up CI package and same-run download correction

The corrected head `c75908f4` passed the complete
[Tests run 42792625606](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/42792625606)
client job: 524/524 files, 10,667 methods with 9 skips, plus 49/49 launcher
files, 1,328 methods with 170 platform skips. Navigation, native geometry,
Windows server/editor and the Windows first-chance exception probe passed.
The actual Python 2.7 bytecode and native x86 source stamp were built and
checked in that run. The separately scheduled BOT regression job **failed one
of the 15 cases** in `test_shared_current_he_execution.py`: the expensive
second HE contact was skipped entirely when the atomic frame budget elapsed
immediately after evaluating the first contact. A lower-damage first target
could thus be prematurely locked. Both an explicitly budget-exhausted second
row and a wholly unvisited qualified second contact now defer the first lock
until their expected-damage results can be compared. Dedicated virtual-clock
regressions cover both shapes without increasing the per-frame budget or
relaxing the existing highest-damage HE assertion. The follow-up CI run, not
this failed run, must demonstrate BOT success.

Its Windows launcher was built and **uploaded successfully** as artifact
`13752143372`, 68,578,817 bytes, SHA-256
`d0463d89141ba954c9628a292b34af2d26f537d158906c2b9726439281737fa1`.
An independent download of those exact bytes passed outer ZIP CRC, the x64
launcher PE identity, all **265** bundled server/shared-control Python source
comparisons, the nested client ZIP and `.wotmod` CRCs, shipping x86 native
source stamp, starter equality and replay reader identity. This validates
contents, not execution of the Windows GUI on Linux.

The final Windows job nevertheless failed **after upload**: an immediate
`actions/download-artifact@v4` REST artifact-ID lookup returned `Not Found`
for its freshly uploaded ID. Consequently its downloaded-executable server
smoke step did not run, and that CI run is not reported as all green. The
follow-up workflow uses the documented same-run artifact **name** download
without cross-run `github-token`/REST-ID lookup, retaining the exact
one-extraction Windows server-startup assertion. No shipping gameplay source
or client tests were relaxed for this workflow repair; a new CI result must
pass before the package is considered fully delivered.

The GitHub Actions BOT group, full client suite, actual Python 2.7 compiler,
Windows launcher packaging and user in-game regression remain separate final
gates. Neither a host pass nor a future-path probe proves an actual game shot,
frame-time improvement, or fixed live AT7/STB1 presentation. The final PR
record must cite a specific new pushed SHA, completed CI run and downloaded
Windows artifact; the prior `d149aadc` package is **not** this correction.
