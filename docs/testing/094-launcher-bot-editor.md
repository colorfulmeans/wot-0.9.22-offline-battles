# v0.9.4 launcher Bot tactics editor

Baseline: `5fda392c88c0987ed110a097e3c668d0be011fa2` (PR #36).
This branch also integrates the previously supplied, unpublished initial-SPG
library patch. It does not contain a new native driving or collision policy.

## Launcher entry and ownership

Open Tools -> Bot tactics -> Edit behavior, routes and artillery positions.
The existing exact-lineup editor remains separate and unchanged. The new
Tk editor has behavior and map tabs. It uses Pillow 12.3.0 to read original
minimap DDS artwork from the selected #1513 game installation; no original
artwork is redistributed. A clearly labelled navigation raster is used when
that artwork cannot be read. A user may import a north-up, full-boundary image
as the current editing background; background images are not part of exports.

Profiles live below `%LOCALAPPDATA%/WoTOfflineBattles/bot_tactics`, outside the
application and game folders. Profile names are hashed into safe filenames.
Save writes a named draft. Apply also atomically replaces `active.json` with a
validated copy. The previous version is retained as `.bak`. Invalid input does
not replace the current active configuration. Import/default/new actions are
only drafts until Apply. Export is plain, versioned JSON, never executable code.

A launcher-owned server receives the active file path through
`WOT_0922_BOT_TACTICS_PATH`. Only the host reads it when accepting a new battle.
The round gets one immutable, map-scoped copy, transmitted through every real
battle-start/restart/current-message path. Mid-battle edits cannot change the
current round. A following round reads the next active version without another
EXE build. Joining another host does not override its configuration. Custom
configuration is refused for a separately running server rather than falsely
claiming that it was applied there.

## Behavior controls

Rules support all Bots, either team, one vehicle class, or one team/slot.
More specific rules override inherited fields; blank fields inherit. The
editor previews resolved values. Explicitly add/update a rule to keep it.

The first version exposes the actual connected gunnery controls: skill preset,
crew level (75/90/100), reaction delay, aiming patience, convergence threshold,
aim-point bias, and lead error. Skill and crew can be set separately. These
are fed into real Bot initialization and gunnery functions. No fake sliders
for unused tactical capabilities are offered, and no hidden change to damage,
penetration, native dispersion, spotting or reload formulas is introduced.

## Map authoring

All 41 pinned maps have exact arena bounds, real team base coordinates and the
SHA-256 of their original navigation resource. Team numbers are accompanied by
actual map-side coordinates; team 1 is not assumed always north. Only the
currently supported regular battle mode is authored. Window zoom/pan/resize
never changes stored world X/Z coordinates. Himmelsdorf's non-centred bounds
are covered explicitly.

Original routes can be edited directly: select a built-in route, drag points,
click to append, Shift-click to insert, or Delete to remove a point. The existing
16-point communication limit still applies. Edits are saved per map, team and
route and vehicle class in the profile, and applied on the next round without rewriting installed
navigation resources. Reset route restores the selected original geometry;
undo/redo covers these edits. Built-in identities and allocation metadata remain
unchanged, so normal route assignment and emergency lane changes use the edited
geometry. A disconnected or unusable edit falls back to its original route and
is logged; Check map reports its baked validation result before a match.

The class selector chooses the geometry being edited, not just its display.
All classes supplies shared geometry; a class-specific default edit overrides
only that class on its original allocated lane. The legend and route lines use
light green, medium yellow, heavy grey, TD blue and SPG red. The list shows the
current scope and marks saved edits. In All classes view, scoped overrides are
also drawn in their class colours.

Enable Route symmetry to share exactly the same coordinates with the opposite
team in reverse order. Dragging, inserting and deleting route nodes synchronize
from either side. Turning symmetry off retains both versions for independent
editing. It reverses traversal, not map coordinates. Resetting a symmetric
default resets both teams for that class; copying creates an independent route.

Select or double-click a default or custom node, then enable the waiting-place
editor below the route-point actions. Click the map to add up to three independent
parking places, drag them to adjust positions, and set each duration separately:
0 continues, up to 3600 seconds waits, and -1 holds permanently. Delete removes
the selected parking place without deleting its parent route node. Unselected
groups appear as one large circle; only the selected parent expands its places.
Entering the waiting-place editor unchecks and disables Route symmetry, keeping
the opposite team's current geometry and waits. Leaving this editor enables the
checkbox again; it remains unchecked until explicitly enabled. Normal route-node
editing still supports symmetry. Artillery parking also displays Route symmetry
disabled and unchecked. Existing single-point waits retain their position and
duration. The host leases one place per Bot,
starts its timer within 1 m, and retains occupancy until the departing hull is
clear. Extra Bots wait for an available place instead of converging on it.
Place parking positions far enough apart for the intended vehicle hulls; nearby
reservations cannot be occupied concurrently. A waiting Bot can still rotate its
hull, aim and fire, but contact escape and friendly repositioning cannot translate
it out of its place. Automatic route reinforcement cannot cancel an active wait.
Temporary route reassignment joins a new lane near the current position instead
of replaying deployment from point zero. Returning to a scripted route restores
progress and completed waits; an interrupted unfinished wait reacquires its place
and starts a new arrival clock. Round reset and vehicle removal clear this history.
Check map reports each invalid waiting place by route, parent node, place number
and coordinates. It checks usable positions, entry from the parent and directed
exit to the following route node. These editor checks do not measure firing lanes
or change runtime route admission or navigation-grid display settings.

Copy a route or create an empty custom route for separate allocation rules.
Custom route attributes include allowed
classes, optional 1-based UI slots, capacity, sampling weight, and preferred or
fixed policy. SPGs only use parking regions; custom/default scripted SPG
routes are not available. Ordinary deployment still uses the position library.

Route points are macro intent, not a request to bypass terrain. Initial route
selection checks baked connectivity and uses a deterministic weighted draw.
Fixed routes suppress autonomous lane rebalancing; emergency/combat orders and
real obstacle avoidance still take precedence. The existing navigator and
driver execute the route. An unavailable custom route is logged and does not
invent a passage through a wall.

Create an SPG position by clicking a centre, then set an allowed parking radius,
initial heading (0 degrees north) and priority. The circle is a deployment
region, not shell splash or range. Actual vehicle-sized candidates are selected
inside that circle from the pinned baked grid, with ground/clearance/reachability
checks and team reservations. No spawn is teleported. The final selected plan
has a two-metre arrival radius and cannot be replaced by the old arbitrary rear
route-waypoint heuristic. Its identity is stable across target changes and
worker restoration.

Manual positions take priority over the integrated community source for that
team. An unusable manual set is explicitly logged as
`manual_no_reachable_parking_space`; no distant invented parking coordinate is
substituted. Uncovered maps/teams retain the old fallback. The community source
itself still covers only Ruinberg and Steppes (10 zones, 15 cells); editable map
coverage must not be confused with 41 validated community recommendation sets.

## Validation is not native acceptance

The map validation window is scrollable and reports every unusable node with
its one-based index and X/Z coordinates, and both node numbers for disconnected
adjacent segments. It includes team, route and class labels. Missing ground,
water/boundary hazards and out-of-grid coordinates have separate explanations.
These are baked-grid facts, not proof that a native ground surface is impassable.

Route symmetry is always visible immediately to the right of the own-base
coordinates, on a separate toolbar row that fits the minimum window width.
Select a regular route to enable it. Parking regions remain team-specific.

Selecting SPG shows default parking points instead of regular lane polylines.
Ruinberg/Steppes use the sourced parking regions; other maps preview the exact
host rear-route anchor selection, including admitted global route edits. An
untouched preview does not create a manual override. Editing a default parking
point creates a manual region override; reset/undo restore the untouched preview.
The circle represents the parking region, not a promise to place every gun at
its centre. The worker still resolves distinct vehicle-sized initial reservations.

The editor opens with All classes selected and Route symmetry checked.
Unedited ordinary routes adopt symmetry when first edited; an explicitly
disabled saved setting remains independent. SPG regions are team-specific.
The legend uses red squares for SPG parking regions. Click or drag to reposition
the region, then edit its radius, heading and priority. SPG movement points,
itineraries, arrival waits and route class selection are removed. The position
schema contains only a centre and region properties. Tank route waits remain.

The editor's map check proves only baked connectivity and existence of generic
parking space. Vehicle-sized parking is checked by the actual worker at round
preparation. Full per-gun ballistic coverage is not certified by either check.
Every shot still goes through the existing aiming, ammunition, exact native
trajectory and friendly-obstruction gates. A library-position obstruction is
logged; automatic switching between library positions is not implemented in
this phase. The prior no-target/proof-loop fix remains intact.

The config contract rejects unknown versions/fields, stale map fingerprints,
out-of-bounds coordinates, NaN/infinity/Boolean numerics, invalid class/slot
selectors, duplicates, overlarge files and overlarge map-scoped wire documents.
Only current-map data is sent at battle start; complete 41-map profiles do not
enlarge every snapshot. Server logs record both profile and round hashes, plus
the bounded round document, for reproducibility.

Tests cover the real launcher button, actual Tk Canvas events, dirty/default
semantics, named save/import/export, invalid form protection, effective behavior,
route assignment, manual-plan validation, server roster admission, restored
worker plans, fixed-route policy, real host battle-start freezing, and the
next-round reload. The packaged EXE additionally runs
`--verify-bot-editor <receipt.json>` in an isolated temporary profile: it opens
Tk, draws route/position edits, applies them, and has the real plan builder read
them. A separate EXE server-readiness check is required. Neither is native WoT
map/gameplay acceptance.

No main merge, tag, account/save reset or official release is performed.
