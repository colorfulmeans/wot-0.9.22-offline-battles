# Worker spike timing test

Launch the extracted Windows test package with `START_SPIKE_PROFILE.bat`.
The inherited `WOT_OFFLINE_SPIKE_PROFILE=1` flag enables only the hidden
worker's detailed observer. Opening the executable normally keeps the ordinary
profiling policy. Close an existing launcher before selecting either mode.

The observer measures every control callback, including catch-up slices, for
up to 64 consecutive 30-second capture windows (32 minutes). Each capture
retains all tracked Bot actor summaries; slow-frame traces retain the six
most expensive actor slices and their eight most expensive stages. Global
stage totals, explicit actor phases, native calls/callbacks, and queue waits
reuse the existing bounded ledgers. Shared asynchronous navigation servicing
has its own `bot.navigation_service` scope outside the actor loops.

Driving preparation, commands, target refresh, weapon preparation, motion
planning, integration, aim/fire, and cover preparation have separate actor
phases. Nested timings are inclusive; use self time to avoid double counting.
The observer does not change Bot decisions, stepping, or work budgets.
Detailed timings and periodic JSON emission add overhead: use this package
to identify causes, not to establish an uninstrumented performance baseline.

After a representative battle, export the launcher's report ZIP. The hidden
worker log's `combat_trace`, `combat_summary`, and `combat_checkpoint` records
contain the per-frame and per-Bot timing evidence. A checkpoint overlaps its
capture summary and must not be added to it.
