# Bot Movement, Attack and Base Defense

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Task priority

For normally armed vehicles: automatic base defense → combat → recovery → front-line redistribution → player commands → ordinary route travel.

Combat means encounter-related aiming, approach and firing, not ordinary route travel towards the enemy base. Automatic defense owns hull travel while the turret may fire opportunistically. Recovery remains a way to complete a blocked task and does not automatically cancel defense.

Confirmed-empty ammunition is an independent state: external defense, redistribution and player orders do not call it away from capturing the enemy base. Its own recovery and route switching remain available.

## 2. Ordinary travel and assignment

Occupancy is shared by a same-team route family across classes. Empty primary routes are preferred, followed by less occupied primary routes below three vehicles; reserve routes are used when primary capacity is insufficient. Ties are random. Legal authored routes remain preferred even when all are occupied.

Initial travel joins the second waypoint from spawn. The first point is used for reverse return and switching. Ordinary points use a six-metre arrival disk and passage checks; the terminal objective is the enemy capture circle. Navigation and collision still find a legal connection between points rather than forcing a straight line through objects.

After combat or temporary orders, choose a reachable, low-travel-cost point on the original route. Forward travel may execute waits; return travel, defense and empty-ammunition capture skip waits.

## 3. Blockage, skipping and return cycles

For ordered points A/B/C/D, a Bot approaching C from B first uses local avoidance, reverse, turns or pushing. Around twenty seconds without sufficient progress at the macro leg leads to trying D. If D also fails, return through B, A and the remaining original points to the route start.

Returning is still recovery. Reaching B does not end it. Connect the old start to the next route's start, then end the transfer only when the new route begins. Failed cycles can retry without a permanent exhausted-attempt stop.

Combat pauses recovery timing and retains progress. If combat moved the vehicle, reconnect from its actual position. Walls, deep water, boundaries and hull clearance remain authoritative; skipping is not permission to pass through a wall.

## 4. Front-line redistribution

Evaluate every 180 seconds to address long periods without useful contact. Return along the old route to its start, then join the assigned route. Do not cut directly across the map from one route's middle to another.

Expiry before transfer completes rejoins a passed point of the old route; a completed transfer retains the new route. Recovery, existing transfers, actual capture and empty-ammunition capture exclude repeated dispatch. Reservations and arrived support are distinct; empty vehicles still occupy roads.

## 5. Automatic base defense

Select eligible armed responders when enemies occupy the home base. The default maximum is three, adjusted for invaders and existing defenders. With multiple eligible vehicles, retain front-line strength; a sole eligible vehicle may defend. Mobility, return distance and ability to interrupt capture matter, not simply sending everyone home.

Reverse along the original route. Use an authored defense branch when its junction is reachable along that return. If already past the junction in reverse, continue to the start rather than turning back to chase it. Without a branch, return to the start and then the base. A start inside the circle is reached on circle entry.

Blocked returns retain local recovery and point skipping. Repeated failures allow the direct-base fallback, still subject to actual collision and impassability.

Release automatic defense after thirty continuous seconds without enemy occupiers. An enemy inside with zero accumulated capture points still interrupts the safe interval. Clear the defense fallback state and rejoin the original route afterwards.

Inside the base, legally shootable occupiers rank by capture points; equal points use normal target scoring. Consider enemies outside only when inside targets cannot be effectively attacked. Normal targeting resumes after defense.

## 6. Player commands

Only currently eligible Bots receive commands. Nearby vehicles within roughly 300 metres are preferred, normally up to three recipients; command-specific rules and distant fallback selection still apply.

| Command | Action |
| --- | --- |
| Attack | Advance on the current route |
| Turn back | Go to the fixed previous waypoint, then resume normal action |
| Back to base | Reverse along the route and guard, subject to automatic priority |
| Attention to area | Go to the indicated area, then rejoin the original route |
| Help/follow | Follow a position near the moving player; rejoin when the player dies/leaves or the task ends |
| Stop | Hold temporarily, then resume route travel |

Movement commands generally last 120 seconds; short tactical commands usually last fifteen. Back to base has ninety seconds from issue to arrival. Its first base arrival switches once to thirty continuous safe seconds, never back to ninety. Combat does not pause this player-guard clock.

Each issuer has one shared ten-second cooldown. At least one Bot must really accept before cooldown starts; actual recipients acknowledge positively. During cooldown, eligible responders give a negative response only on the first rejection, without repeated spam. The command is invalid and is not queued. No eligible recipient means no cooldown consumption and no response.

A new legal command replaces that Bot's old player command. Combat and higher-priority automatic tasks can invalidate player commands; invalidated requests do not resume afterwards.

## 7. Enemy-base capture

The capture circle is the terminal arrival area: entering it begins capture instead of chasing an exact last waypoint. There is no separate three-capturer assignment or outer capture-guard task. More than three may remain inside; the native capture-rate contribution limit is separate from entry permission.

Capture protection constrains tactical destinations so chasing, reload adjustment or redistribution does not unnecessarily pull vehicles out. A shoved vehicle attempts to re-enter. Protection does not freeze physical collisions or displacement.

## 8. Artillery deployment

Artillery has deployment, endgame sortie and empty-ammunition sortie states. Deployment includes assigned parking and automatic deployment; sortie retains return-home, defense and route-switch subtasks.

At most three parking assignments are made, one per position, reserved while travelling. Unassigned artillery navigates and fires automatically without ordinary-route occupancy. A dead owner's position may receive a free replacement; a failed replacement disables further replacement of that position for the round.

Deployment, relocation and return to parking use automatic navigation. Fixed base-to-parking and parking-to-parking connections are not edited. Parking is a deployment goal, not a requirement to remain immobile before every shot.

## 9. Endgame sorties and alternative roads

When all surviving Bots on a team are SPGs, admit up to three armed sortie participants. Human players do not affect this Bot-only test. Prefer freely moving artillery, then randomly select parked artillery. Homeward travel, combat and recovery retain the slot; stopping to reload does not admit a fourth. Fill real vacancies; remaining armed SPGs wait and may fire. Parking replacement stops in the endgame.

A sortie returns to the home capture circle, then follows the independent red attack route. It retains SPG ballistics, yaw/pitch limits and reload checks and may engage along the way. Automatic defense preserves sortie identity and resumes the sortie afterwards rather than restoring deployment.

The C→D→B/A→home recovery cycle also applies. Alternative candidates include ordinary primary and reserve roads, excluding disabled and clearly unreachable choices. Prefer lower occupancy, randomize ties, avoid the failed road when alternatives exist, and retry the original only when necessary.

To borrow a road, leave base along its defense branch in reverse, then advance from its junction. Without a branch, join its actual start. Missing SPG attack data uses the same home-first ordinary-road selection; automatic navigation is the final fallback if no valid authored road exists.

## 10. Confirmed-empty ammunition

Trigger only when all known valid shell stocks are zero. Missing/unknown inventory, reloading, an empty magazine or only the current shell type being empty cannot trigger it. Initial zero stock and genuinely firing the last round both qualify.

On first entry, retire old combat, player, redistribution, defense, parking and paused-recovery ownership once. Do not reinitialize every update. Travel to the enemy base and skip waits; taking fire does not restart stationary combat. Opportunistic aiming remains possible under normal weapon checks; no rounds are invented and an already launched last shot settles normally.

Exclude empty vehicles from external player, defense and redistribution calls, while counting physical road use. Retain their own recovery, reverse return and switching. Stay capturing after arrival and re-enter if pushed out.

Empty SPGs bypass the Bot-only-endgame and three-armed-sortie eligibility limits. All may leave, returning home first. Prefer the artillery attack road; after three users, select lower-occupancy ordinary primary/reserve roads. Borrowed-road connectors and blockage recovery follow the same sortie rules.

Source checks: server_bot_ai.py, server_route_tasks.py, server_route_recovery.py, server_empty_ammo.py, lan_battle_server.py, spg_modes.py, spg_route_travel.py, spg_route_recovery.py, empty_ammo.py and capture_orders.py.
