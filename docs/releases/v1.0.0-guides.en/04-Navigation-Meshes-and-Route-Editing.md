# Navigation, Meshes and Route Editing

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Waypoints versus navigation meshes

Numbered route points describe an authored travel corridor. The underlying mesh contains ground nodes and links used to find the actual path. Bots choose macro points in order, then navigate between them.

Densifying yellow mesh samples is not adding numbered waypoints. Refinement can recover a narrow street or a corner whose coarse cell centre intersects a wall. It cannot turn real buildings, mountains or deep water into roads.

## 2. Path finding and passage checks

Cost-aware graph search considers ground height, directed links, hull clearance, slope, water and arena bounds. Smoothing, local avoidance and final motion checks still apply. Vehicles, wrecks, destructibles and narrow passages need runtime handling.

A connection may be directional. A bridge and its underpass are not connected merely because their two-dimensional lines intersect. Clearly unreachable acquisitions may be excluded; pending asynchronous evidence is not automatically a proved obstacle.

At bridge locations, height is always taken from the bridge deck. When editing routes, avoid crossing beneath bridges.

The current water policy uses a 1.2-metre limit with shore support and fall protection. Shallow water can be a high-cost alternative, not permission to open all deep water.

## 3. Local refinement

Retain the broad base mesh and add bounded patches at useful narrow passages, corners and bridge entrances. Fine cells use their own height and hazard flags; checking only the parent coarse layer is insufficient.

| Map | Current approach |
| --- | --- |
| Himmelsdorf and winter version | Base graph plus narrow-passage local layers |
| Windstorm | Bridge deck, entrances and reviewed shallow-shore links |
| Stalingrad | Fourteen bounded two-metre patches, authored waypoints unchanged |
| Siegfried Line | Four two-metre town patches and one 16×18-metre one-metre corner pocket |

For equal area, changing four-metre sampling to two metres roughly quadruples samples; one metre is roughly sixteen times the original. Actual cost depends on boundaries and closed cells. Prefer local patches and measured positions over globally densifying a map.

Clearance, collision, slope, water and diagonal-link checks remain. The editor displays/checks shipped meshes. Import map imports an editing background; it does not bake a new navigation mesh.

## 4. Profiles, teams and views

Open Bot tactics and Routes/artillery positions. Default is read-only; create an editable profile, save a draft or apply for the next match.

All class routes is the overview; selecting an object still addresses one route. All vehicle classes is the black common-edit scope. It replaces the current map/team/family's ordinary-class geometry, ordering and defense junctions, excluding the independent SPG attack. Individual edits can diverge afterwards; the next common edit replaces them again.

Only enabled and valid symmetry updates the other team. Asymmetric maps disable it. Changing teams shows that team's defense connections.

## 5. Editing ordinary routes

- New routes contain fixed endpoints and initially select the first point. Insert between endpoints, never after the fixed destination.
- Left-click selects/drags an existing point; empty-space clicks do not create ordinary waypoints.
- Shift-click inserts after the selected point, subject to the fixed destination. A two-endpoint route gains its new point between them.
- Overview selection first resolves the specific route; use the list for overlapping roads.
- Selecting/double-clicking a legal major point opens waiting-place editing. Empty-space clicks in wait mode add a waiting place with a sixty-second default.
- With an artillery position selected, clicking the map directly relocates it, unlike ordinary waypoint dragging.
- Copy, delete, undo/redo and restore are supported. Ordinary routes permit up to sixteen points with at least one metre between consecutive points.

Ordinary starts are own spawn points. On symmetric maps where both spawns lie inside their bases, fixed endpoints are the two spawns. On asymmetric maps with offset spawns, the route runs from own spawn to the enemy base. SPG attacks always run from own base to enemy base.

Ordinary arrival uses a six-metre disk and bounded crossing/passage conditions. Selection draws the actual range. Terminal base arrival uses the real capture circle rather than a single point.

## 6. Primary, reserve, disabled and deleted

Primary roads are solid class-colour lines; reserves are dashed in the same colour. Empty primary roads and their initial three-vehicle capacities are preferred before reserves. Family occupancy is shared across class variants.

Delete routes only from All vehicle classes. Deleting a built-in road disables it for restoration; deleting a user-created road removes objects and references. Older hidden per-class deletion records have become visible reserves, which are not disabled.

Convert to primary/reserve changes the current scope; the already active state is disabled. Restore default routes restores built-in points, waits, tiers and defense branches while retaining user-created roads.

## 7. Waiting places and defense branches

Waits apply to forward route tasks, not reverse return, defense or empty-stock travel. A newly entered route has its normal fresh wait state.

A defense branch connects a legal ordinary intermediate node to own base. Waiting points, parking positions and endpoints cannot be junctions; a junction cannot become a waiting point. Stable node identity prevents insertion from moving a branch to an unrelated index.

Endpoints are fixed; intermediate branch points are editable. The dashed connection is labelled Defense, with its own exclusive editing mode. Moving/deleting nodes, common replacement, copy/import and undo/redo maintain references.

Default ordinary defense branches are authored for Mittengard, Tundra and Ghost Town. An unconfigured branch on another map is not automatically an error: reverse to the ordinary start, then base. Guide 3 explains runtime behavior.

## 8. Artillery editing

Parking and ordinary defense are separate. A parking position defines an automatically navigated location and heading. Fixed base-to-parking or inter-parking links are not edited.

The independent red dashed endgame attack appears after artillery positions in the left list. It does not join ordinary primary/reserve common edits; endpoints are the two bases. Up to three armed SPGs use it in the Bot-only artillery endgame, with separate empty-stock admission and borrowing rules.

## 9. Check this map and danger display

Check this map expands effective configurations across both teams, classes, primary/reserve routes, waits, parking, SPG attacks and defense. It separates Configured and correct, Configured but incorrect, and Not configured, with disabled entries separate. Results locate objects, nodes and links; editing invalidates old results.

Show navigation grid displays actual base/fine nodes. Show danger grid displays hazard flags with hover details. Red does not universally mean forbidden: deep water, shore protection and reviewed fords differ. Missing ground and missing links are separate diagnoses.

A pass means navigation-data checks passed, not guaranteed native clearance under every wreck, congestion and vehicle size. Report map, team, class, route, specific point numbers and preferably coordinates/screenshots.

Source checks: bot_tactics.py, route_network.py, bot_tactics_runtime.py, bot_tactics_ui.py, bot_tactics_navigation.py, bot_tactics_artillery.py, prebaked_navigation.py and current navgraphs.
