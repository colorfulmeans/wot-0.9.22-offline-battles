# Replay capacity and committed magazine follow-up (2026-10-20)

## Evidence and scope

Report `wot-error-report-20261020-174909-63ea0004498b.zip`, build
`539053dc`, Great Wall. The writer stopped at 17:44:41 with a generic bounds
error. Its retained compressed prefix contains 805,198,408 logical bytes,
107,960 bytes below the former 768-MiB ceiling. The battle continued normally;
the previous complete last-battle replay remained published.

Enemy Foch 23 retained target 7 while alternating cover movement and fixed-gun
laying. After shots around 17:42:24 and 17:42:31 its chassis turned away and
then back before the next shot. This is a magazine-specific combat improvement,
not evidence of permanent navigation deadlock. No three-nonpenetration movement
rule, ammunition selection change, new aim candidates or navigation strategy
is introduced.

## Replay

Raise the cumulative decompressed stream bound from 768 MiB to 8 GiB in the
isolated writer, isolated decoder and original streaming reader/recorder.
This is a finite file bound, not a memory allocation; the 2-MiB row limit,
4-MiB IPC limit, bounded playback prefetch and four-hour duration cap remain.
Keep sequence/footer validation, atomic publication and incomplete `.part`
retention. Failed recordings never replace the previous complete file.

Distinguish row/total-limit failures and include accepted bytes, next row size
and limit in total-limit errors. Writer startup/failure status includes the
logical-byte limit. Rebuild the pinned official CPython 3.11.9 embedded
resource with the new writer, update its accepted content digest, and update
the standalone decoder digest. Old schema-1 recordings remain readable.

## Magazine ownership lifecycle

Only an actually committed stationary shot may admit/renew follow-up ownership.
It requires a magazine larger than one round, rounds still in the clip, an
existing stationary combat mode and an ordinary vehicle. Both turreted and
limited-traverse vehicles use this ownership; moving shots, SPGs and single-shot
guns do not acquire it. No extra ray or armor query is added.

A successful shot leases the same target for its remaining intra-clip reload
plus two seconds. Cover steering temporarily yields to the current-pose engage
order; real collision/recovery and final gun alignment, reload, obstruction,
wreck and friendly-fire gates remain authoritative. Fire permission is not
fabricated. Successful fire already completes older rear-laying/movement leases;
those clocks cannot silently expire under the new follow-up hold.

Only the next committed shot can renew the deadline. Turns, incoming orders,
waits and changing cover positions cannot renew it. Empty magazine, exhausted
loaded ammunition, target death/change/loss, fresh blocked lane, mechanical
recovery, actual translation beyond 1.5 m, parking/base-defense priority,
actor death or deadline expiry releases the hold to existing action ownership.
No target is invented and no partial magazine is forcibly reloaded. Existing
empty-magazine/capture rules remain. Diagnostics retain the target/shot,
original fire time, absolute deadline, incoming move, existing lane witness,
active status and timestamped last terminal reason.

## Validation boundary

Focused tests exercise the measured cover destination, successive shot-only
renewals, no-renewal timeout, both vehicle types, all release conditions,
old mechanical-clock cleanup and actual runtime fire admission. A real
770-MiB logical stream is written, atomically published and read through both
readers to a count-checked end. Separate tests retain row limits, total-limit
failure diagnostics and previous complete replay preservation.

The older replay integration/R4 fixtures have six unchanged failures, reproduced
on pre-change HEAD 539053dc: sparse player-presentation equality, obsolete
replay-runtime setup/BigWorld fake and asynchronous reader/pacing assumptions.
Do not weaken assertions or claim those groups passed. Preserve their baseline
comparison in delivery evidence. This change does not certify native Windows
rendering/timing; gameplay acceptance requires the user's new client run.
