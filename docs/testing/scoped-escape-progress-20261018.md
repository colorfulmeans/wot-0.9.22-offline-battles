# Scoped refusal evidence and connector progress

Report: `wot-error-report-20261018-012526-f80e722e28ca.zip`, Windows359.

## Evidence and scope

- Round 1, T57 (18): forward samples rise approximately 0.33 m / 0.5 m,
  0.62 m / 1 m and 1.22 m / 2 m. These fail the existing grade rule. This
  change does not remove or relax that rule. Rear short probes were suppressed
  by the yaw failure bucket; the old receipt did not identify its producer or
  distance. Up-facing rotation hits alone do not establish a false collision.
- Round 2, IS-5 (11): local connectors and remote progress targets alternate.
  Replacing the progress target over 2 m apart recreated its timer and heading
  anchor even when the actual movement order had not changed. This is a
  bookkeeping defect, not proof that every route reassignment was wrong.

## Changes

1. Failure receipts identify origin, distance, driver clock, expiry, renewal and
   source. A distant forecast cannot veto a fresh shorter straight probe. A
   realised contact remains protected locally during its original lease; moving
   over 0.25 m requires fresh proof rather than inheriting that refusal. The
   existing native collision and support gates still own actual movement.
   Live contact evidence cannot be overwritten by a later long forecast.
2. Changing only the local progress representation rebases its incomparable
   distance without renewing the same actual order's clock or alignment credit.
   Real order changes, arrival, genuine translation, deliberate alignment and
   commanded holds keep their existing behavior.
3. Existing motion-stall records include the last 16 refusal receipts and the
   exact evidence consulted by short probes. Pose producers distinguish yaw
   rebase, vertical guards, support rise, hard translation and post-contact
   support. Server route receipts identify pressure rebalance, lease expiry,
   loss of radio knowledge, catalog reset and wreck-stall switching. Receipt
   changes are excluded from strategic order revisions and the worker's order
   comparison. Previously the worker still treated changing `route_attempt`
   telemetry as a new command and invalidated its control cache; the two ends
   now use the same diagnostic-only contract.

Preserved: D+C / heading ordering, C and avoidance, original finite retry and
route-switch behavior, height connectivity rules, support 1-invalid-on /
5-valid-off, crush physics, HUD callbacks and independent fixture layouts.
No new slope preference, slope veto, route blacklist or collision exemption.

## Validation boundaries

The new regressions cover shorter fresh proofs, real and expired contact
leases, moved origins, forecast/contact precedence, bounded diagnostics and
alternating connector progress. Existing slow brake-and-align, ordinary
arrival, retry, support and crush regressions must remain green.

Engine-free tests cannot prove that T57's native rear exit or rotation arc is
clear, nor that IS-5's tactical route changes were inappropriate. Those require
the next Windows client report; the additional receipts preserve that evidence.
