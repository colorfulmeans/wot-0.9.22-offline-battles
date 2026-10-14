# Queue promotion, contact tracks and repeated-probe cadence

Report 20261014-163454 records multiple 7-9 FPS worker windows with callbacks
around 120-133 ms, while the waiting options remain over the garage. The user
requires the stock waiting background before the existing options, and ramming
module damage only on the actual contacted track, never on internal modules.

## Waiting background

A connection form may already be open when welcome arrives. The old open flag
skips the stock queue acquisition. Promote that already-open connection form to
the stock waiting background on welcome; retain one queue acquisition receipt
and clear it on leave. Training modifies LAN rules, not the waiting background.
A refused queue acquisition retries the existing lobby callback. No fullscreen
substitute, stock view patch or resource changes are introduced.

## Vehicle ram track damage

Retain the existing frozen contact/structural armour probe. Only its first native
skin within 0.15 m of the actual contact witness can nominate left/right track
material. Hull/gun contact in front of a track does not nominate the track.
The offline tolerance is conservative and still needs native client acceptance.
Metadata travels with the immutable player receipt or authority contact armour
pair, including side reversal and human-human probe responses. Body armour and
kinetic HP laws remain unchanged; missing geometry never fabricates a track.

Trial module loss is max(0, closing_speed - 2) * 25 HP, once per contacted side
per existing admitted ram operation. This is not a recovered retail coefficient.
Canonical actor pools own depletion; unrelated modules and crew are preserved.
Preserve ram operation fingerprints, duplicate/conflict handling, friendly
ram policy, combat revisions, owner repair and all frozen-pose authority gates.
RAM TRACK CONTACT and RAM TRACK DAMAGE evidence describe nominations/commits.
Fall geometry and coefficient 25, fire and projectile damage are unchanged.

## Work cadence

After an entire short escape fan fails, wait 0.25 seconds before another fan.
No successful/failed physical result is cached. A retained successful exit still
rechecks current terrain and vehicles every decision; a hold releases the retry
clock. Publish defer/retry evidence. This bounds repeated failed-probe work,
not the whole worker collision/navigation cost. The recorded stuttering cannot
be claimed eliminated until another supported-client run measures it.

Validation: 1,433 focused tests across 12 suites pass against frozen source;
182 client source files compile under CPython 2.7. Native contact gating,
left/right isolation, internal-module refusal, player-pair and Bot/player
canonical commits, duplicate/conflicting packets, queue promotion and finite
proof retry are exercised. Full Bot-runtime sweep and Windows packaging follow.


## Windows254 follow-up (17:34 report)

The user reports visible Bot motion discontinuities and a second room visit over
Hangar. Worker probe cost is not proof of the visual defect. Withdraw the failed
short-escape fan throttle entirely and restore per-decision live probes.

The queue adapter was uninstalled on session stop but retained for reuse;
its subsequent open returns false. Discard it after successful uninstall.
Remove the session-wide acquisition latch, which survives Account/view changes.
Require the current Account queue flag AND a populated #1513 BattleQueue view
in the LOBBY_SUB container before opening LAN options. Dispatcher acceptance is
only an asynchronous request, not completed view loading. Coalesce the pending
request by Account identity and retain the explicit join intent during connection
form promotion. No opaque replacement screen is introduced.

Add bounded nearby Bot presentation observations: confirmed source age/revision,
presentation cursor hold counts, render gaps, interpolated pose and final native
model translation. These observations do not modify motion/planning laws or the
jitter buffer. Actual visible stutter remains unverified until client evidence.

The report has no new Python exception. Worker live callback rates fall to
7.60-10.20 Hz with mean execution 93-128 ms. Bot fire presentation delay across
185 samples has a median of 285 ms and maximum of 582 ms; that is shot playback
latency, not a measurement of per-frame vehicle smoothness.
