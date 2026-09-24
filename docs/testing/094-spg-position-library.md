# Historical SPG position library and initial deployment

Baseline: `5fda392c88c0987ed110a097e3c668d0be011fa2` (PR #36).
Target: Chinese HD `0.9.22.0.1-cn-1513`, standard two-base CTF only.

## Source, attribution and limits

Hawg (PigBrains / Hawgs_Mods) describes his recommended SPG markers in:
https://koreanrandom.com/forum/topic/43190-hawgs-spg-td-passive-scout-tactical-minimaps/
The thread includes a February 15, 2018 9.22.0.1 update, but its first post
was subsequently edited. This library does NOT scrape a modern first-post
illustration or claim it is an official Wargaming artillery coordinate table.

Instead it transcribes the same author's separately preserved SPG-only file:
https://www.curseforge.com/worldoftanks/wot-mods/hawgs-tactical-arty-minimaps/files/2527609
Author download: https://mediafilez.forgecdn.net/files/2527/609/Spg_Tac_1.zip
SHA-256: `22ec2f4bf5e438237b02eb94d9cf3e0b68c76d5fd51cfb05230c7113a04b0710`.
The author listing supports 9.22.0.1. It is not asserted to be byte-identical
to the forum's later combined SPG/TD/scout archive.

The source is a GPLv2-listed image mod. No source minimap textures, WOTMOD,
images, author code, installer or game resources are redistributed here. The
committed facts are marker pixel boxes/centres and image/archive checksums,
with explicit author attribution. Newly written runtime/generator code follows
the repository licence; this is not a relicensing of the source artwork.

There are 42 source map images. Of the repository's 41 maps, 38 have a total
of 237 artillery markers. Great Wall (`59_asia_great_wall`) has no source
image. Lost City (`95_lost_city`) and D-Day (`101_dday`) have images with no
SPG markers. The tutorial/alternate Prokhorovka images are NOT silently
aliased to other arenas or used to fill those gaps.

## Reproducible conversion and graph projection

`data/spg_positions/hawg_2527609_markers.json` preserves source facts.
`tools/build_spg_positions.py --archive <Spg_Tac_1.zip> --check` verifies the
archive checksum, extracts only the yellow-bordered blue-filled SPG symbols,
and reproduces every coordinate. Pillow is needed only for DDS extraction;
the game has no Pillow/numpy/scipy dependency. Without --archive, --check
rebuilds from the committed facts and all pinned navigation graphs.

Pixel X maps left-to-right into the exact #1513 arena bounding box; pixel Y
maps top-to-bottom into decreasing world Z. Bounds are not assumed to be a
1000 m square centred at zero (Himmelsdorf is one counterexample). Side
assignment uses actual CTF spawn anchors, not "team 1 = north"; Steppes and
Ruinberg have opposite team-to-north assignments.

An icon is a suggested region, not a surveyed parking pose. Candidate nodes
are limited to 24 m from its marked centre, must be connected to their own
base by reciprocal dry graph links, and must have a dry, mutually connected
3x3 parking patch with a local grade <= 0.18. Shallow-water parking is also
excluded. Up to three distinct parking slots per marker are retained, at
least 14 m apart. These placement tolerances are local policy, not claimed
retail constants. Native hull/terrain probes still govern actual movement.

Seven markers have no admissible patch and are explicitly rejected, not
replaced with distant invented coordinates. The other 230 source regions
provide **666 graph-projected parking slots**, covering both sides on all
38 sourced maps. `docs/testing/spg-position-coverage.json` lists every map,
side, source gap and rejected marker. 666 is NOT the author's marker count.

The generated runtime module `ai/spg_positions_data.py` includes all source
facts, grid geometry, base sides, node heights, navigation SHA-256s and
projection distances. Build verification pins the unchanged 41 navgraph files.
The worker also checks the installed map/version and local dry graph patch.

## Initial deployment (actual server-to-worker path)

- The live server passes its selected `map_name` into BotPlanner.
- On first orders, each SPG reserves a legal same-side library slot. Multiple
  SPGs prefer different marked regions and respect chassis-radius-based
  separation (minimum 14 m); normal tanks and AT-SPGs are not assigned slots.
- The assignment is stable for the round, independent of changing generic
  route IDs and target leases. Death releases reservations; reset/map changes
  discard the old plan. No hidden enemy positions are read.
- The existing navigator receives that independent absolute destination. Its
  path key uses the deployment identity, not whichever enemy is targeted.
- The old 15 m "arrived" radius is NOT used for a sourced slot. Server and
  worker use the existing driver's 1.5 m terminal tolerance; worker checks its
  actual pose rather than trusting a delayed server "hold" snapshot.
- While travelling/parking, local target-facing hull aim and final shot proof
  must not freeze the drive. The worker withholds the local shot attempt and
  target from the driving command until arrival, then resumes the still-valid
  server target. Reloading and observation continue normally.
- Actual firing still requires the prior ammo/reload/aim/full-native-arc and
  friendly-fire checks. This change provides no shot receipt or hit itself.
- Explicit manual moves and base defence preempt the plan. Their orders have
  contradictory deployment metadata removed; all-or-nothing metadata and goal
  validation prevent mismatched map/side/revision/coordinate plans.

Maps with no source use the retained legacy anchor and an explicit fallback
status/log; they are not reported as fixed or forum-covered. A mismatched
installed graph safely stops the sourced plan and logs its rejection instead
of trusting stale coordinates. `SPG DEPLOY` records include the map, bot,
source marker/slot and goal; existing `SPG FIRE GATE` diagnostics remain.

## Scope not silently extended

This is a position library plus initial deployment, NOT a new omniscient
strategic artillery AI. The pre-existing evidence-triggered near-wall escape
remains as a local emergency fallback. It is not a full-library strategic
relocation/coverage optimiser, and it can still report no safe rear waypoint.

Graph reachability/parking checks do not establish full native ballistic
coverage. No complete per-gun/per-shell/precomputed firing-arc matrix has been
produced. Final in-game proofs decide whether a particular received target is
shootable. Native Ruinberg/Steppes gameplay acceptance remains necessary.

Existing driver.py, traffic.py, adapter.py, all navigation/map resources,
ram/contact changes, penetration, downhill speed, radio/spotting, and
exchange/crew fixes remain unchanged. No account reset, main merge or release
tag is requested/performed.

## Tests

The new suite checks all 41 graph hashes, every one of the 666 local patches,
base connectivity, source counts, 24 m projection limits, real spawn-side
assignment and asymmetric bounds, six-SPG spacing across all 38 sourced maps,
stable assignments, reset/manual orders, protocol rejection, stale server hold,
travel/target separation and an actual LocalDriver command inside the old
15 m stop radius. The retained SPG tracking/arc and contact regression suites
remain separate. Test success is not native Windows map acceptance.
