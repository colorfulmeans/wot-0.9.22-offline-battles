# v0.10.2 pre-publication failure audit

The first publication attempt never created a release or tag. Preserve the
source history for comparison; discard that failed build and generate the
release only from the final verified main commit. Do not reuse an earlier
launcher or claim that source tests prove native gameplay.

## Confirmed runtime defects

- The direction-observation callback assigned its receipt through a closure
  reference to itself. With automatic GC disabled, 200 controlled updates
  left 3,774 unreachable objects. `DEBUG_SAVEALL` identified 200 instances
  each of sample_clear, sample_clear_impl and planner_sample_direction.
  Keep the receipt attribute and all probe calls, but reach the callback
  through a weak reference. The unchanged zero-garbage regression now
  observes zero; manual round-end collection remains tested separately.
- A standalone server entry assumed that the interpreter adds its script
  directory to sys.path. The isolated embedded interpreter does not.
  Explicitly resolve that directory alongside the existing client source
  directory. The existing foreign-working-directory --help test passes.
  This changes import setup only, not server planning or battle rules.

## Test inputs that no longer represented the production contract

- Support lifecycle lambdas rejected the `evidence` keyword before asserting
  five-point behavior. Accept the real optional diagnostic argument; retain
  every one-invalid/all-valid, pose and velocity assertion.
- Navigation oracle mocks invented a Mock-valued last_receipt. The real
  producer publishes a dictionary. Supply that dictionary in the mock.
  Known blocker, unknown retry, fair query service and cancellation tests
  pass without changing NativeNavigation or TerrainGrid behavior.
- The wreck invalidation fixture hand-edited a raster edge but omitted the
  authoritative footprint. Publish the same real static hull input used by
  production. Retain the rejection of a path crossing the new wreck.
- The team-command recorder replaced BotPlanner without its live-bot input
  contract. Derive the recorder from BotPlanner and retain validated-order
  admission assertions. No change to production team-command policy.
- The sealed-wreck scene used movable contact bodies while asserting zero
  attempted pushes. Observation showed 2.8 m of real wreck displacement,
  bounded motor episodes and subsequent ordinary recovery. Require bounded
  unproductive motor time, terminal reasons, recovery and no passing the
  sealed wreck. Keep open-lane and real-bypass arrival tests.
- The Airfield 24-FPS scene had actual friendly rotation vetoes for two
  vehicles. Without any navigation modification they departed beyond 20 m
  at 79.75 and 106.8333 simulation seconds. Keep the 60-second departure
  assertion for unexplained/unobstructed stalls; only witnessed physical
  neighbour refusals may continue, and every non-SPG must still depart in
  the bounded 180-second scene. Preserve the five-second traffic yield and
  half-second false-arrival bounds. Do not introduce any in-game timer,
  holding policy, route ranking, slope rule or navigation strategy change.

## Build and verification defects

- Mixed indentation in the folded CI command turned later `--pattern`
  arguments into separate commands after 69 passing test files. A first
  single-line correction missed two other over-indented lines. Replace the
  entire folded command with a literal Bash array and one invocation. Parse
  the actual YAML and execute shell argument capture: all 58 patterns and
  the selected files are preserved, with no split or dropped argument.
  A final per-pattern audit also found three empty selectors for tests deleted
  with the earlier navigation rollback. Replace them with current authored
  progress, crush handoff and recorded-bypass tests. Reject any unmatched
  selector even if other patterns match; add a negative regression so an
  empty test name cannot silently count as verification. The customization
  selector belongs to launcher/tests, so invoke it in that directory instead
  of silently losing it in tests/. Separate per-stage report directories
  preserve every summary rather than overwriting it with the last group.
  Retain nonzero failure status and every selected test.
- The replay reader changed during the earlier capacity update. The reader and writer-runtime
  consumer pins were updated then, but the independent package validator
  still pinned both old resources. Match the reviewed current bytes and
  assert that both independent resource pins agree with their consumers. Keep the strict archive validation and actual replay capacity tests.
- After all 378 client files and 23 launcher files passed in CI, its client
  packaging step exposed another producer omission: the general test workflow
  used the tracked old native binary without rebuilding it. The release build
  already rebuilt correctly. Add that same source-stamped x86 build before
  general CI packaging; retain the strict source/payload identity rejection.
  Never replace the identity check with a stamp-only rewrite of old bytes.
- Independent inspection of the completed Windows download found identical
  batch scripts encoded as CRLF while Linux checkout uses LF. The initial
  publisher raw-byte comparison wrongly rejected that representation. Verify
  the three text entries with CRLF/LF normalization only; preserve every
  other byte and all binary/data integrity checks. Regress both line endings,
  altered test-mode flags and every missing entry.
- Include the repository root in isolated test sys.path so namespace imports
  work even with the Windows embedded interpreter's _pth isolation. Add an
  actual isolated import regression. File-level test isolation remains.
- The local embedded host lacked Pillow and tkinter; missing dependencies
  are not product failures. Install pinned Pillow for local image tests;
  use the normal Windows Actions interpreter for full Tk/editor checks.

## Scope retained

No edits to route selection, retry switching, collision geometry, support
thresholds, gun target priorities or crushing damage. Keep one invalid
support point enabling detailed support and five valid points disabling it.
Low vegetation crushing is deliberately unchanged by user decision.

## Follow-up from the 2026-10-21 03:50 report

- The retained enemy entity is hidden on an AOI/spotting exit, but remains
  registered and keeps receiving poses. Exact #1513 PostmortemDelay normally
  freezes its provider in __onVehicleLeaveWorld. Forward that camera-only
  lifecycle edge when the hidden entity is its active killer, including a
  hide during the initial fade. Keep the stock five-second return timer and
  kill credit. Do not broadcast entity destruction or replace shared methods.
  Reconcile unchanged dark presentation passes; deduplicate by a weak reference
  to the actual delay, not a reusable object address. Pin the exact callback
  signature and names in the native ABI auditor. Test fade/vision timing,
  marker-only memory, other targets, visible wrecks, new delay identity and
  normal return to the local wreck.
- T28 Concept repeatedly aligned to nearby local points; ISU-122S repeatedly
  recovered around a real SU-122-44 wreck. The report does not establish a safe
  navigation-law correction. Preserve all driving/retry policy. Record compact
  target lineage at every navigation return, including early no-target returns
  and exceptions, with owner, requested/returned/previous points, rebase distance,
  counts, bounded event history and explicit history truncation. Publish it
  with the existing final motion/execution evidence. Observe accumulated small
  rebases too. No additional native probes are introduced by this observation.
  The isolated height-scope exception fixture must include the runtime's
  existing states registry (empty for that cleanup-only test). Preserve the
  original exception and scope-release assertions; the new owner-present
  test separately verifies exception receipts without masking the error.
- Reuse only the unchanged current baked hull footprint within one synchronous
  actor planning call. Exact position, yaw, dimensions and grid identity are
  keys; candidate poses remain checked and all native collision sweeps remain.
  Discard the cache before the next call. For five candidate headings the focused
  test reduces ten footprint calls to five while preserving all verdicts.
- Compact JSON and avoid allocating a full extra list of fragment strings.
  Keep every field and every fragment below the engine line limit. Reassembly
  tests include embedded spaces, quotes and slashes. In a CPython 2.7 benchmark
  over 20 recorded motion payloads, output fell from 2,659,593 to 2,472,622 bytes
  and writes from 810 to 753; serialization CPU was approximately unchanged.
  This is an I/O/allocation reduction, not evidence of an in-game FPS gain.
  Add separate observed preparation, finish and JSON-write stages so the next
  report can distinguish diagnostic overhead from simulation work.

## Report 20261021-135311: expired lanes and repeated occupied-point bypass

- Jagdpanther II (27) retained the same human target while alternating between
  contact approach and stationary laying. Positive native lane receipts aged
  1.54-2.06 seconds and were omitted from the shooter list; the server treated
  an unfinished refresh as a newly blocked lane. Publish selected expired
  positive receipts separately as `pending_lane_by_bot_ids`. Validate live team
  and radio ownership on admission. Retain only an already stationary combat
  owner, with fire disabled. Fresh blocked evidence still releases that owner
  to the original contact approach; fresh positive evidence restores ordinary
  firing. No existing approach becomes a new hold. Final native fire checks
  remain authoritative.
- Sturer Emil (12) repeatedly received occupied-point bypasses while the global
  corpse-grid revision advanced. That revision invalidated completed local
  actions even when the original endpoint remained occupied. Revalidate
  geometry after a revision without renewing the action. The original actor
  replan generation still permits another attempt; an endpoint becoming free
  releases the completed action. Log previous/current epoch, renewal versus
  geometry-only invalidation, and timed physical blocker positions/radii.
  This fixes the demonstrated invalidation defect, not every possible source
  of route oscillation; preserve the complete target/driver lineage for the
  owner's next gameplay report.
- Extend synchronous exact baked-footprint reuse to identical candidate poses.
  Twenty repeated checks of one candidate now need two grid calls rather than
  twenty-one (current plus candidate); a new planning scope repeats both.
  Native world queries, physical collision shapes, water and support are not
  cached or bypassed. This call-count result is not a Windows FPS claim.
- Regression coverage distinguishes pending/blocked/clear lanes, end-to-end
  observation admission, radio/visibility loss, existing movement ownership,
  completed bypass retention, original retry renewal and exact cache scope.
  The report's detailed support enabled once with four valid points and
  disabled once with five. Keep that rule unchanged.

## Report 20261021-144050: traffic-vetoed gun laying

- First-round Jagdpanther II (27), 14:31:55-14:32:16, requested a positive
  firing pivot but traffic safety returned zero turn. Replaying the recorded
  poses identifies allied Steyr (24): the full requested sweep is blocked
  (legal fraction approximately 0.34), while the gun remains outside its
  +/-10 degree arc. The sweep veto is valid; the missing recovery handoff is
  not. The stationary driver did not advance its movement-stall clock.
- Preserve that exact rotation guard and record its timestamp, original and
  candidate yaw, shape, allowed fraction and peer poses without a second
  native query. A denied active gun-laying turn feeds the existing
  `_gun_angle_pivot_refusal` owner and invalidates the old decision once.
  Existing bounded gun-angle recovery then owns facing, checked relocation,
  arrival, failure/cooldown and target/priority cancellation. Clear a pending
  unconsumed handoff if the traffic veto clears; do not cancel an already
  admitted relocation merely because it is no longer requesting a pivot.
- Ordinary route steering, base defence, parking and artillery deployment
  do not gain a new recovery policy. Actual collision shapes, shooting
  obstruction, retry/route switching and support thresholds remain unchanged.
- The German Emil, Swedish Emil and E50 eventually left their logged pockets.
  Recorded terrain collisions and missing-ground rejects do not establish a
  safe routing-rule correction. Keep their laws and full target lineage.
  Preserve the nested native sweep's specific rejection reason in the outer
  planning reason/counts instead of `unspecified_callback_rejection`.
- A committed recorded-pose fixture tests guard -> refusal -> cache expiry ->
  existing checked relocation -> stalled exit, alongside blocker release,
  target loss, priority handoff, ordinary movement and diagnostic provenance.
  Geometry replay verifies logic, not Windows gameplay feel.

## Report 20261021-151509: final support ownership and full-solver replay

- Build 431 reproduces the player's bridge-edge tumble at approximately
  15:14:34-15:14:40. The player already runs detailed support. Do not describe
  its instability as a support-mode toggle or a tank-on-tank contact bug.
  Player and detailed Bot support share the numeric solver. This report does
  not isolate which spring-force or hard-projection operation causes the
  player's repeated lift, so no speculative solver-law change is made.
- A separate confirmed worker ownership defect is corrected: the timed
  vertical solve could release detailed support at its provisional endpoint,
  before tank translation/separation restored a different endpoint. Somua SM
  16 has repeated enable/disable pairs at those different X/Z poses around
  15:13:11. Defer release through the final physical-contact and pose guards;
  then check the actual five points. Keep one-invalid enable, all-five-valid
  disable, real collision, gravity, landing effects and route laws.
- Both detailed adapters now capture a complete serializable numeric input
  and actual output. The explicitly labelled Python reference replay breaks
  each substep into force integration and hard projection, and compares its
  terminal result with the actual solver. No extra world or native query is
  issued. Replay failure is diagnostic only. Normal edge samples remain at
  two seconds; abnormal lift/rotation receives a bounded 0.25-second cadence.
  The local YPR chart receipt distinguishes equivalent angle remapping from
  a physical rotation, without modifying the existing remapping law.
- WZ-120-1G FT 9 remains in a small pocket until 15:14:47 despite repeated
  attempts. Existing evidence includes real collision refusals and changing
  retreat/contact/defence actions, not a proven reason to change navigation.
  The common applied-control window now retains a bounded sequence of action
  goals, targets, decision identities, arrival gates and final physical
  outcomes, including cached controls and no-emission frames. Omitted actions
  are counted. No routing or retry timer is changed.
- Sturer Emil 12's corpse push terminates as `own_stalled`, followed by reverse
  and movement. Preserve that bounded attempt; do not call it a permanent
  push or identify this German TD as Dicker Max. Tiger 18 and Somua 16 later
  move/fire. ISU-122S 26 executes the existing mechanical recovery and fires
  again; these facts do not prove that every blocked pocket is bug-free.
- Tests include the runtime contact phase, final lost/restored support,
  JSON-roundtrippable numeric replay, force/projection attribution, explicit
  native/reference disagreement, diagnostic exception containment, cached
  action lineage and bounded omissions. Full-solver Windows acceptance remains
  pending; this candidate must not be presented as a verified tumble fix.

## Publication status

The owner withdrew publication on 2026-10-21. GitHub has no v0.10.2 release
or tag; the publisher's outstanding runs were cancelled and its workflow
was disabled. v0.10.1 remains the current published version. Source and
verification fixes continue in PR #113 on `fix/0102-release-verification`.
Do not merge as a publication shortcut, create a release tag, or re-enable
publication before new explicit authorization after Windows acceptance.

The exact main commit `df24fdf974dafb7727de690441ff1492969db8ed`
passed complete CI run 39481277906. Earlier complete CI runs 39479640906
and 39481242691 also passed; they establish repeated checks but do not
substitute for validation of the final PR commit and its fresh package.
The additional launch-entry verifier must pass on the final PR tree.
Build the candidate through `build-launcher.yml` on the PR branch, without
running the publisher. Inspect the downloaded artifact independently.

Validation outputs must record exact test identities, skips and failures.
The publisher independently waits for successful complete main-branch CI
on its exact source commit as well as a successful clean package build.
Only publish after final source, CI and independently inspected package agree. The release contains the normal launcher and all three optional
batch entries, complete source, history bundle and recovery instructions.


## Report 20261021-172717: authored combat approach and water evidence

The owner narrowed this candidate after the audit: fix only the reproduced
Jagdpanther approach-state omission. Do not change drowning rules before its
actual failing boundary is captured. Keep PR #113 open; do not publish 0.10.2.

- A fresh blocked firing lane released rear laying for `advance_contact`, but
  `advance` bypassed that check. Report Bot 11 repeatedly received `advance`,
  stopped/turned toward an occluded target, timed out, moved, and repeated.
  Apply the same existing check to both combat approach modes. Preserve clear,
  unknown and expired evidence behavior, ordinary rear aiming, parking and
  withdrawal ownership, real collision and all route/retry/support rules.
- Water is diagnostic-only: retain the ten-second gate, proposal admission,
  damage attribution, module settlement, safe/stale handling, and remaining HP
  displayed on drowning death. Do not claim the live drowning failure fixed.
- Correlate `PLAYER WATER` records across the visible warning, worker hull/body
  geometry and native ray result, proposal/error, send gate/transport, server
  admission/ignored row, freshness/reset/countdown, missing terminal proposal
  and terminal commit. Include round, player, input/sample sequence, time/tick,
  actual hull bounds and query data. Repeated reasons are bounded at two
  seconds; changed level/proposal/failure state is immediate. Reset per round.
  No extra water/world query, protocol field, timer or terminal rule is added.
- Regression coverage includes both approach names through real control
  updates, retained normal rear aiming, complete JSON evidence, query counts,
  unavailable geometry/entities, failed/recovered submission, rejected/stale
  messages, countdown pause/reset, unchanged missing-proposal behavior,
  remaining-HP death display, once-only settlement, and failed log sinks.


## Report 20261021-182526: unresolved native water and edge projection

This candidate adds evidence, not a speculative drowning, support or navigation
repair. PR #113 remains unmerged and 0.10.2 remains unpublished.

- The visible client classified full submersion for 52 seconds. At essentially
  the same body pose the worker's `wg_collideWater(..., False)` returned -1,
  published level 0 and caused the server to keep resetting its timer. This
  report does not reach the previously suspected ten-second terminal gate.
  The original HP, countdown, critical-proposal and death rules are unchanged.
- Water receipts now include avatar/engine-player space, camera position,
  rendering settings, and complete reverse/extended-ray outcomes after a miss.
  The two extra rays run only at the admitted two-second diagnostic cadence.
  Neither their hits nor their exceptions replace the authoritative query.
  Render configuration differences are observed, not a proven root cause.
- The captured full-support input repeatedly produces about 1.57 m of contact
  projection, then the adapter restores the earlier pose and zeroes velocity.
  All 132 captured native/reference terminal replays agreed, including 74
  rises over 1.5 m: agreement is not a physical-correctness test. Some offending
  contacts are metres from the previously fitted plane. Do not relax the guard
  or delete those contacts before their actual native layer is established.
- Projection receipts include every iteration's selected constraint, excess,
  gradients, denominator, before/after pose and residual heave. Player and Bot pseudo
  contacts also carry actual ray bands, layers, retention and chosen heights.
  Player/Bot rejection receipts identify both planes, both poses and terminal
  rollback. No solver coefficients, support admission or 1-lost/5-restored
  rule changed. The numeric fixture preserves the unresolved failing input;
  its test verifies observation parity, not that the physics is repaired.
- Bot 9 (Object 263) accumulated 13 recovery attempts in a small region while
  sometimes meeting real native geometry, relocating and firing once. A new
  bounded observation episode joins existing stall receipts across owner and
  local-target changes and records when it leaves the diagnostic pocket.
  This state is never read by navigation, retry, route selection or gunnery.
- The slow worker window averaged 166.4 ms execution, including 151.5 ms in
  Bot update. The old normal-entry report had no measured inner probe costs.
  Normal workers now use three bounded 30-second capture windows, 30 seconds
  apart, sampling one complete control callback in 32 with a rotating slot.
  Explicit profile entries retain their original cadence and explicit disable
  flags still disable capture. No simulation time or physical query budget is
  discarded. Further optimization requires the measured inner-stage result.

Validation includes captured-input diagnostic/non-diagnostic solver parity,
non-mutating native water probes (including errors and diagnostic rate limits),
normal-entry capture lifecycle, and cross-owner stall evidence. Native water
registration, layer selection and gameplay pacing remain Windows acceptance
items for the owner's next test; no successful fix is claimed for them here.
