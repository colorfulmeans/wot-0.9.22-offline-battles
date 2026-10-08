# CI contract audit, 2026-10-08

## Observed failure and execution repair

PR 47 at `38442cbcd85a` failed run 37743690390. The main job reported
7,203 cases, 140 failures, 69 errors and five skips. The Bot job stopped after
two recovery-input assertions still required 45% throttle rather than the
current full-throttle escape policy. These are historical results; a newer
commit does not erase their red status.

Run the suites from the repository root:

```sh
python tools/run_test_suite.py --jobs 4 --logs build/client-test-results
python tools/run_test_suite.py --directory launcher/tests --jobs 2 --logs build/launcher-test-results
```

Each discovered file runs all of its cases in a fresh interpreter. Native
module fakes installed during import cannot contaminate another file. Failure,
import error and existing skip semantics are retained. Each file gets a full
UTF-8 log; the console reports assertion tracebacks instead of dumping native
chatter. Runner regressions explicitly prove failure and import-error exit
codes and cross-file isolation. No skip, expectedFailure or continue-on-error
was added to hide the remaining failures.

PR events run once instead of running duplicate branch-push and PR workflows.
Main pushes and manual dispatch remain enabled. Later test/compile/log steps
run after an earlier test fails; package generation still requires success.
All client modules receive Python 2.7 syntax compilation. A separate Windows
job runs the real Tk editor tests even when the Linux test job fails. Git
attributes preserve the exact bytes of hashed catalogs and the pinned
navigation reference on Windows; resource contents are not changed.

## Contracts updated

| Previous assumption | Current contract and retained evidence |
| --- | --- |
| Recovery uses 45% throttle | Signed full throttle; checked distances/deadlines and collision vetoes remain |
| Fixed, balanced route buckets | Random highest-priority allocation, three places per class, empty assignment permits automatic navigation |
| Vehicle mass/gear scopes planning | One shared static policy; kinetic inputs still belong to actual motion, deferral and revision invalidation are checked |
| Runtime repairs every missing baked height | Cold graph remains immutable; local native proof has a separate owner |
| Navigation rejection means a physical wall | Flat traffic fixtures supply current native interfaces; the coarse bake is not a physical receipt |
| Contact immediately penalizes the shared grid | Completed native review and timed per-Bot contact evidence are separate; one vehicle cannot poison others' routes |
| Full suspension runs for ordinary Bots | Production stays on cheap support; explicit spring fixtures opt into the deferred experiment locally |
| Remembered corridor grade provides launch velocity | Only accepted chassis support can provide vertical launch momentum |
| Runtime carries arbitrary stun factors | Native mechanics and stun expiry own effects; obsolete wire factors are not authoritative |
| Collision diagnostics expose only final input | Bounded diagnostic includes planner, traffic input/output and motion gates |
| Wrecks use retired per-push log schema | Current motion logging, actual resolver arguments, bounded falls and collision stops are checked |
| Audio removal must have no callback | Safe relay is permitted; a disposed audition must not be retained |
| Every account inventory is byte-identical after startup | Vehicle ownership and delivery remain durable; later style initialization is accounted for |
| Old calibrated base values | Exact current capture coordinates are checked |
| Parent node can own a wait clock | Shared geometry is travel-only; only explicit small parking places own clocks |

Radio movement tests now supply a graph that actually covers their commanded
positions, start beyond the arrival radius, and retain movement assertions.
Crowded traffic fixtures pin allocation entropy so the same scene can be
replayed at both frame rates. This does not change production randomness.

## Real implementation gaps exposed by valid checks

The following fixes preserve their original checks rather than lowering the
expected result:

- Siege intent brakes with the current installed descriptor before beginning
  a transition, in both directions and modes.
- Physical-hold, SPG reproof and stationary hull-aim stop commands request
  active braking rather than silently coasting.
- A deferred direction without an exact resolver cannot authorize an
  unproved movement slice.
- Rejected final support cannot clear its own contact episode before settling.
  Only accepted drive progress clears it; an invalid later shove does not
  poison that drive edge. No extra ground or native collision queries are added.
- Designated Target reads the validated directive duration/sector while still
  requiring an eligible trained gunner and the actual aiming sector.
- Diagnostic JSON no longer requests needless sorted-key encoders inside hot
  callback owners. Canonical cold tactics serialization retains stable sorting.

## Retained failure boundaries

The remaining checks are not labelled obsolete solely because they fail:

| File | Remaining evidence to resolve |
| --- | --- |
| `test_port_0922_contact_navigation_regressions.py` | Current Pilsen planned path crosses a finite workshop panel about 6.70 m from its center; adding a 2.15 m hull half-width exceeds the 7.71 m panel half-width. Historical route geometry and infinite-plane crossings were removed from this check. Actual doorway interpretation still needs review. |
| `test_port_0922_fjord_departure.py` | Fixed-entropy Airfield flat scene still has vehicles that do not reach the retained 20 m departure requirement within a minute at both frame rates, after the native-interface fixture repair. |
| `test_port_0922_downhill_departure.py` | Grounded recorded Cliff departure is rejected in the analytical mesh and through player/worker adapters. Real backing-wall controls remain; the expected clear departure was not reversed merely to match current output. |
| `test_port_0922_tactical_route_review.py` | Canada west-hills geometry still intersects the historical railway exclusion region. This is a resource-risk check, not proof of a native collision. |
| `test_port_0922_wreck_dynamics.py` | KV-5 pushing through the lighter-owner side and one delayed reverse-owner scene move in the expected direction but fail the retained one-metre progress requirement. |

Final local client discovery ran 7,205 cases in 266 files. It reported no
import/runtime errors; five files retain 13 failing subcases, with four existing
skips. The full run also exposed an unseeded Great Wall traffic scene; pinning
its startup allocation made that scene reproducible and its focused rerun passes.
The launcher ran 969 cases in 21 files with zero failures and 15 existing skips
(the live Tk route-editor cases ran). All 163 client modules compile
under Python 2.7. Source/data simulations do not prove actual native client
physics, rendering or performance. No live profiles, default user tactics,
map geometry or production full-suspension setting were rewritten.
