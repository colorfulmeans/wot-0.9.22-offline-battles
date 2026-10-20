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
