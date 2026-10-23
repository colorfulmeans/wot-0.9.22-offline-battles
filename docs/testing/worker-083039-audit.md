# Worker audit: 2026-10-23 08:30:39 report

Report: `wot-error-report-20261023-083039-22cb2d8fbb5c.zip`.
Input build: 469, commit `987ef97dc95318addc5f893bc9ae880fd0b9ec2d`.
Map: `101_dday`, 29 Bots and one player. The battle ends normally with
`team_eliminated`. Exception files contain recorder headers, not exceptions.
There is no new traceback, system-error exit, or missing-interior warning in
this roster. Absence in this report does not prove all rosters are covered.

## Measured cost

Worker speed falls from 33.40 FPS to 5.00 FPS while execution averages
194.416 ms (maximum 376.191 ms). Outside-worker time is approximately 4--7 ms.
The limiting work is the worker's Bot update, not an observed render wait.

One 30-second capture ending at 08:26:32 contains:

| Stage | Calls | Inclusive ms | Self ms |
| --- | ---: | ---: | ---: |
| Bot physical slice | 167 | 25,605.056 | 5,956.118 |
| Planner / driver | 4,083 | 8,308.923 | 3,735.500 |
| Rotation physics | 5,608 | 7,364.655 | 1,032.890 |
| Native world rotation | 5,590 | 4,274.880 | 4,139.759 |
| Translation physics | 3,259 | 1,902.107 | 1,835.015 |
| Ground probes | 40,537 | 2,011.881 | 2,002.334 |
| Vertical physics | 4,768 | 2,945.620 | 1,056.010 |

Inclusive rows overlap and must not be summed. Sparse detail captures sample
complete control callbacks (one in 32); they are not whole-window totals.
In those samples, rotation catalog probes cost 1,988.554 ms, native probes
4,313.479 ms, and actual catalog commits only 6.678 ms / 12 calls. Sampled
native ledgers attribute most `world_run_native` inclusive time to callbacks,
not its C++ arithmetic body. Moving more arithmetic to C++ alone does not
remove live engine/filter preparation or the number of required ray lanes.

Visibility/control projection reuse introduced in build 469 is working:
344 reuses / 6 builds in this capture, with 350 unchanged configurations.
Oldest queued work reaches 1,090 ms; completed wait p95 is 908.997 ms. A later
capture reaches 2,963 ms oldest wait. These are real latency observations,
but do not justify dropping accepted shots, skipping collision lanes, or
changing driving/route/catch-up rules.

## Confirmed changes

* A read-only rotation previously rebuilt the identical analytical local
  envelope and descriptor for each equal-angle slice. Prepare them once per
  synchronous sweep. Keep every midpoint pose, departure proof, travel vector,
  ground attitude, probe direction and live-world query.
* Synthetic body envelopes now carry their already-read motion geometry.
  Only the private synthetic snapshot uses this path; live descriptors still
  read current hull/chassis bounds and mount, including Siege changes.
* Native surface candidate collection was active whenever a contact trace
  existed, including the basic entrance. Basic mode now returns the original
  collision filter directly. Only the diagnostic entrance records candidates;
  material decisions, bounded candidate lists and hard-contact evidence remain.
* The old `wreck/2` pipeline assertion compared a legacy path without ray
  reuse against a production path with reuse. Its actual lists contain 2,082
  versus 2,074 queries and identical unique geometry. The updated audit first
  disables reuse in both paths and compares complete ordered frontiers. A third
  production arm then verifies full states, reports and effects, plus ordered
  query omissions limited to previously seen identical unfiltered rays. The
  separate scope/invalidation tests continue to enforce where reuse is legal.

No native ABI, collision coverage, collision tolerance, physics budget,
decision cadence, route policy or ammunition behavior changes in this patch.
The relevant analytical envelope and world-query laws already run in C++.

## Unconfirmed observations

Stationary artillery continues increasing its shot sequence. T54E1 also
fires while holding position, later reporting a destroyed gun and an arrived
reload-retreat target about 4.36 m away. E75 reports a destroyed engine.
These records are insufficient to establish a new navigation or firing bug;
no speculative behavior change is made. Existing opt-in motion histories,
critical state, rotation substages and queue/native ledgers retain the evidence.
Bulk diagnostic byte ceilings remain 2 MiB/minute and 32 MiB/process.

## Verification

Regression coverage checks exact prepared geometry, current live-descriptor
mutation, all retained rotation poses/directions, read-only query flags and
basic/diagnostic filter parity. Existing tests cover backing walls, damaged
BSPs, ground slopes, departure witnesses, query-scope invalidation and failures.

A host-only preparation benchmark with synthetic clear queries retains two
queries for a 0.01-radian sweep and fourteen for a 0.6-radian sweep. Median
preparation time over five batches of 500 calls was approximately 0.0173 to
0.0163 ms and 0.1104 to 0.0447 ms respectively, using CPython 3.11. These
numbers demonstrate removal of repeated preparation; they are neither a
BigWorld benchmark nor a prediction of Windows client FPS.

Final isolated-suite, native pipeline, exact-commit CI and package results are
recorded in the PR and delivery evidence. Only a real #1513 Windows playtest
can establish the resulting FPS, native contact behavior and gameplay feel.
