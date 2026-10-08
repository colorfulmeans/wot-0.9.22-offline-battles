# Fjords stalled route continuation

Report: `wot-error-report-20261009-030048-1006339f1522.zip`, local test144
(`6090bd6dfe53`). The affected planner/runtime source is unchanged in v0.10.0.

Observed evidence:

- Team 2 E100 stays at approximately (324.861, 45.819) from 02:58:02 to
  03:00:46, alternating route/capture instructions and repeated local recovery.
- Team 2 121 stays at approximately (319.521, 41.814) from 02:56:51 to
  03:00:45. Route names change without actual departure.
- 705A, IS-7 and Foch155 also change routes; native geometry refusals,
  pending searches and temporary fallback targets recur.
- Artillery has no received target late in the report. The report ends with
  worker disconnection, not an observed natural time-limit draw.

The old macro retry gate requires a wreck/occupied-waypoint receipt and
excludes base_capture. Native geometry failure alone cannot trigger it, and
route/capture transitions clear the attempt. Artillery is already eligible
for the capture squad when no regular Bots remain, but cannot consume the
front-line staging cursor while deployed at its stationary anchor.

Changes:

- Observe owned, mobile travel poses even without a wreck receipt, including
  capture travel. Keep a gate's 20-second attempt across changes to capture
  destination and adjacent travel modes. Intentional holds, arrival, combat,
  explicit team commands and destroyed mobility components remain excluded.
- Refresh a generic progress attempt only after at least 6 m net movement
  and 4 m reduction toward the current destination. Turning and sideways
  orbits do not constitute progress. Explicit wreck attempts retain their
  existing bounded budget and reset when the blocker clears.
- Skip one failed gate, then change route after the successor also fails.
  Reject route aliases whose evaluated next gate is within 16 m of the failed
  goal. Join the evaluated entry from the current pose rather than restoring
  an old failed cursor; preserve completed/skipped parking records.
- Allow selected, unengaged artillery capturers to bypass the impossible
  staging cursor when the remaining friendly Bot roster consists of SPGs.
  Regular-roster artillery deployment and explicit team commands are retained.

Regression coverage is in `tests/test_port_0922_wreck_route_switch.py`:
native stalls without wrecks, capture transitions, forward progress versus
orbits, intentional capture holds, shared failed exits, stale route cursors
and artillery-only capture deployment. Existing collision, waiting, capture,
allocation and team-command suites remain part of validation.

This proves planner decisions under the reproduced state conditions, not
native passage through the report's geometry. No slope threshold, collision
filter, suspension solver or per-frame native probe budget is relaxed.
