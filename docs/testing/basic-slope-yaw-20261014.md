# Basic Bot slope stance during turns

Report `20261014-232355` contains 255 worker motion records and 370 basic
vertical-support records. Recorded Type 59 pivots (including Bots 9 and 22)
have `suspension=false`, zero drive speed and approximately 0.803 rad/s hull
turn speed. The basic height owner follows the centre surface; the separate
four-point stance owner is staggered across five hulls per control frame and
previously retained yaw-local pitch/roll until its next sample. It also
under-fitted the sampled grade by 10% and blended only halfway per update.
These source mechanisms explain a lagging stance during a pivot; the report
does not contain independent track-to-surface distances proving every pixel
of the reported burial.

For ordinary basic hulls, fit one exact four-point plane in the same roll-then-
pitch order as the physical YPR transform. Re-express that sampled world-space
normal in each newly committed yaw without another ground query. Submit the
combined old/new hull stance to the existing full-body pose probe; a refusal
retains the last legal yaw and invalidates the rejected movement command.
Keep centre support, falling, bridge-layer queries and navigation ownership.
Airborne hulls and the ten-spring solver do not use this stance correction;
hydraulic hulls retain their established sampling blend and pitch correction.
Cache basis yaw with the slope sample and include it in rollback snapshots.
Expose accepted/refused sample and yaw-rebase poses plus four sampled heights
through bounded `BOT SLOPE POSE` evidence and the fragmented-record reader.

Restore both offline module trial coefficients to 25: environmental impact
module HP per excess m/s and exact-contact ram track HP per excess m/s.
Keep location/weight attenuation and track-only ram nomination. Historic
30-coefficient captured cases remain explicitly pinned reference tests;
default-25 checks verify the recorded ammunition/fuel pools stay above zero
for the same two heavy-impact inputs.

Analytic plane tests check all four track-plane corners at straight,
diagonal, side-on and wrapped headings, including repeated yaw changes,
blocked full-body probes, missing samples and separate suspension ownership.
The exact #1513 Windows client must still confirm visible stance, collision
clearance and timing on the real map.
