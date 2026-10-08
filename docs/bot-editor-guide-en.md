# Bot Map Tactics Editor — v0.10.0

## Opening and saving

Open **Bot configuration and map tactics** in the launcher. Select the attack-route/artillery-position tab, then choose a map, spawn team and vehicle-class view.

**Save draft** stores the profile without activating it. **Save and apply (next battle)** saves and activates it for subsequent battles; a running battle is unchanged. Use Open to load a profile and Import/Export to share or back it up.

## Views and shared editing

The default **Total routes** view shows light-tank, medium-tank, heavy-tank and tank-destroyer routes together with artillery positions. It omits the shared All vehicle classes template. Select a colored route to edit it or adjust its priority within its own class. To create a route, first select a specific class or All vehicle classes.

| View | Color |
| --- | --- |
| Light tanks | Green |
| Medium tanks | Yellow |
| Heavy tanks | Gray |
| Tank destroyers | Blue |
| Artillery positions | Red |
| All vehicle classes template | Black |

The shared template is a shortcut for editing common travel geometry. Editing a class variant makes that variant take precedence. Editing the shared template again replaces its class variants' travel geometry and clears their independent waiting places and durations. Use individual class views when preserving different tactics. Shared templates have no small waiting places.

## Travel routes

Select a route, then drag its waypoints. The point list helps select a particular node. **Delete point** removes the selected node; **Insert point** inserts a node immediately after it. After creating a route, click the map in travel order to add up to 16 points. Edit its name and apply the properties to the draft.

You may delete complete routes, including default routes. Deleted routes are no longer allocated to that team/class. Undo and Redo operate on draft edits.

Waypoints are navigation goals. Vehicles still avoid terrain, buildings, other vehicles and wrecks; they do not necessarily follow every connecting line exactly.

## Priorities and capacity

Priority ranges from 0 to 9 and defaults to 5. Comparison is within a team and vehicle class, never between classes. For priorities 9 and 5, usable capacity on priority 9 is selected first; priority 5 becomes available when higher choices are exhausted or unusable. Equal-priority choices are randomized, so several vehicles may select the same route.

Each route supports up to three vehicles **per class, per team**; smaller capacities can be configured for custom routes. Class variants do not share those three places. The shared template is not an extra runtime allocation pool. When all routes are full or unusable, vehicles use automatic navigation.

## Symmetry and endpoints

**Route symmetry** copies the same waypoint coordinates to the other team in reverse order. It does not rotate or geometrically mirror the route. Disable it when the teams need different paths.

Maps where spawn areas and capture bases are separate default to symmetry off, but you may enable and save it. Saved choices are retained. Corresponding symmetric routes receive matching random allocations when availability and capacity permit; independent routes need not match.

**Move route endpoints to spawn centers** is a one-shot command. For a selected route, its first point moves to the friendly spawn center and its last point to the opposing spawn center. A single-point route moves only its first point. Nothing happens without a selected nonempty route. Spawn centers are displayed separately from capture circles: this command does not guarantee an endpoint inside a capture circle.

## Small waiting places

Choose a specific class, route and waypoint. Click **Add waiting place**, or double-click the waypoint, to open the waiting-place panel. Enable waiting-place editing and click to add or drag places. Each waypoint supports at most three small places.

Select a place, enter its duration and heading, and apply both. Durations may differ. The default is **60 seconds**; **-1** means no timed departure. The timer starts when the vehicle arrives, not at battle start.

The large waypoint remains an ordinary travel point. A vehicle assigned a small place uses that place instead of the large point for arrival and waiting. Without small places, travel proceeds normally. If every place is occupied or unusable, vehicles use the ordinary waypoint without waiting or queuing.

Each small place holds one vehicle. Waiting vehicles can acquire targets, turn their hull and turret, aim and fire. Reloading, gun limits and obstructions still apply. Waiting is not a hull-direction lock.

The **6 m radius / 12 m diameter ring** is a large-vehicle parking reference. Avoid overlap and map boundaries, and allow room for arrival, departure and rotation. A clear-looking ring is not a guarantee of native collision clearance.

A blank heading automatically prefers the next waypoint and displays an angle preview. Zero degrees is north, 90 east and -90 west. This preference applies on arrival; combat can turn the vehicle elsewhere.

Waiting-place editing disables and clears route symmetry for the edited route. Select a small place and press Delete or use the deletion button to remove it. Removing the final place clears the waypoint's waiting state completely. Unselected groups show one larger waypoint; selecting/editing a group expands its places, rings and arrows.

## Artillery deployment zones

Choose Artillery, select an existing position or create a new one, and place it on the map. Edit its name, radius, preferred heading and priority. Artillery has deployment zones, not ordinary attack routes or small waiting-place timers.

The red circle defaults to a **16 m radius**. It defines a region in which a parking location may be selected, not a hull-size guide or a free-roaming radius. Candidate selection keeps a 2 m inward margin and evaluates actual vehicle size, occupancy and reachability. The selected location need not be at the center.

After deployment, artillery aims and fires normally. Obstruction, occupancy or prolonged inability to obtain a usable shot can cause relocation. Higher-priority zones are selected first; equal-priority usable zones are randomized. You do not need exactly three zones.

Artillery editing shows symmetry disabled and unchecked. Positions are edited independently for each team. Default positions can be deleted. Without usable authored positions, automatic deployment remains available, subject to map geometry and vehicle limitations.

## Map checks and navigation overlay

**Check this map** checks route points and connections, small waiting places and their entry/exit connections, and basic artillery-position availability. Results identify the affected locations.

A successful static check is not a complete gameplay test or proof that every hull can turn anywhere along a route. **Show navigation grid** displays existing navigation data. Missing-height cells may represent buildings, destructible objects or incomplete map data; their color alone does not prove an impassable physical wall.

Check a draft, then test representative vehicle classes in game. Export an error report if a vehicle stops or circles unexpectedly so its position, commands and collision evidence can be examined together.

## Defaults, language and behavior parameters

**Restore default draft** loads the complete revised 41-map baseline, including routes, waiting places and artillery positions. Save and apply it to activate it. Individual restoration commands restore the selected baseline item; restoring a shared route also restores its baseline class settings. New profiles start from this baseline. Upgrading does not automatically overwrite saved profiles.

Built-in route and position names follow the launcher language. Newly entered custom names retain their original text and are not automatically translated.

Behavior rules can override global, team, vehicle-class and slot settings. Blank values inherit. Difficulty and crew level are separate. Reaction time, first-shot aiming patience, convergence factor, aiming bias and moving-target prediction error affect Bot decisions; they do not directly rewrite armor, penetration, reload speed or the physical dispersion rules.

Configuration storage: `%LOCALAPPDATA%\WoTOfflineBattles\bot_tactics`. `active.json` is the applied profile; `profiles` contains named profiles. Prefer Export for backups instead of editing these files manually.
