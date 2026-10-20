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
  their 120 selected files are preserved, with no split or dropped argument.
  Retain nonzero failure status and every selected test.
- The replay reader changed during the earlier capacity update. The reader and writer-runtime
  consumer pins were updated then, but the independent package validator
  still pinned both old resources. Match the reviewed current bytes and
  assert that both independent resource pins agree with their consumers. Keep the strict archive validation and actual replay capacity tests.
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

Validation outputs must record exact test identities, skips and failures.
The publisher independently waits for successful complete main-branch CI
on its exact source commit as well as a successful clean package build.
Only publish after final source, CI and independently inspected package agree. The release contains the normal launcher and all three optional
batch entries, complete source, history bundle and recovery instructions.
