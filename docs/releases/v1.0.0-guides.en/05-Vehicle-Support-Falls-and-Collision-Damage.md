# Vehicle Support, Falls and Collision Damage

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Five-point support detection

Sample the actual support under the hull centre, front, rear, left and right, transformed by current yaw, pitch and roll. These five samples choose support mode; they are not the total number of suspension contacts used by detailed physics.

## 2. Switching modes

| Condition | Action |
| --- | --- |
| Normal complete ground support | Basic support |
| At least one invalid support point | Detailed support |
| Still airborne or any invalid point remains | Retain detailed support |
| All five restored, grounded, admitted landing/contact settlement finished | Return to basic support |

Handoff retains accepted height, attitude and velocity, retires stale slope targets and revalidates support on subsequent motion. Do not discard landing damage merely because all samples become valid or rotate the hull back to an old target after release.

Support uses height layers and continuous-ground evidence. An overhead bridge or roof is not ground beneath the hull. A genuine uphill surface is not automatically a void because one sample exceeds a clipped probe range.

Basic support avoids sustained detailed-solving work on fully supported ground, while detailed contact remains available at edges and during falls.

## 3. Fall HP damage

Actual landing impact speed determines damage, not an unconditional map-height threshold. The default safe speed is ten metres/second. Each additional metre/second costs three percent of maximum HP, rounded down.

For example, 1000 maximum HP and a fifteen-metre/second accepted impact give 150 base fall damage. Real contact, other simultaneous damage and remaining health still govern settlement. Invalid support alone is not a damage event; an actual impact/landing must be established.

Use the motion/contact direction of the surface; ordinary slope travel is not repeated falling. Passive motion after being pushed off a bridge or support remains physical.

## 4. Fall module and crew damage

An impact may also damage contacted exterior components, internal modules and crew positions. Real contact samples and the impact direction query native external materials and the adopted interior layout. Unreached modules do not receive random global damage.

Merge repeated witnesses for the same module and deduplicate the same impact publication. The current offline module coefficient is twenty-five module HP per metre/second over safe speed, multiplied by contact weighting. Crew injury uses its corresponding shock threshold. These are project offline trial laws, not recovered retail server constants.

Safe landings add no module damage. Missing interior geometry does not receive fabricated contacts. Destroying fuel can ignite it; destroying the ammo rack can detonate it; total crew knockout can terminate a vehicle. See Guide 9 for layout coverage.

## 5. Fire HP and internal modules

The current baseline burns five percent of maximum HP per second for ten seconds, unless extinguished or ended earlier. Elapsed burning time accumulates whole-second ticks; a delayed update does not lose intervening ticks.

| Target | Ongoing fire treatment |
| --- | --- |
| Engine, fuel tank, ammo rack, radio, turret rotator | Ten module HP per burn second for valid HP pools |
| Tracks, gun and other exterior devices | Not added to this internal-fire list |
| Crew | Not directly injured by this module-burning mechanism |

Damaged modules can deteriorate to destruction and a depleted rack can explode. Damage stops after death or fire end. Extinguishing restores the fuel tank to its descriptor regeneration cap, not every module to full health, with repair notification for the improvement.

Maximum/regeneration HP use the actual fitting and factors. Ignition, equipment, crew and consumables still apply; the ten-second baseline does not disable extinguishers.

## 6. Stacking, wrecks and cause

Separate first landing impact from continued pressure so one contact is not double charged. Pressure from a dead upper vehicle becomes wreck/environment damage instead of continuing the former driver's output. A live vehicle above a wreck is not automatically injured by reverse pressure merely for that pose.

Preserve impact, fall, fire and wreck-pressure causes. Fire ammo-rack explosion and fall destruction have their corresponding messages rather than pretending all environmental damage is a shell hit.

Player and Bot authority paths apply corresponding shared laws; model/HUD/module state follows accepted settlement.

## 7. Fixtures

START_ROOF_CRUSH_TEST.bat is the bridge push/drop fixture. START_ROOF_SHOT_DROP_TEST.bat releases falling Bots after player shots from below. Guide 8 explains entrances and reports.

Source checks: bot_runtime.py support ownership, vehicle_physics.py, environment_modules.py, critical_damage.py, device_damage.py and server landing/contact settlement.
