# Team Formation, Bot Filling and Vehicle Eligibility

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Team slots and automatic Bots

Each team supports up to fifteen vehicles. Humans consume their team's positions. Explicit launcher Bot slots are retained first; automatic Bots fill the remainder. LAN joins and team selection change the remaining Bot count.

Formation uses effective vehicle, tier and class data, not a reconstruction of a public online queue. Teams may share tier/class templates without matching every model. Fixed lineups and custom sizes affect the result.

## 2. Tier windows

| Setting | Automatic tiers relative to player reference T |
| --- | --- |
| Same tier | T |
| -1 to same | T−1, T |
| Same to +1 | T, T+1 |
| -1 to +1 | T−1, T, T+1 |
| -2 to same | T−2, T−1, T |
| Same to +2 | T, T+1, T+2 |
| Random | One legal continuous window, normally one to three tiers |

Only tiers 1–10 with actual candidates are used. Random chooses one window around known humans and eligible content, not independent five-tier rolls for every Bot. Baseline widths are 28% one-tier, 44% two-tier and 28% three-tier; human span and catalogue availability may adjust them.

At fifteen players, templates favour low/middle/top 7/5/3 or low/top 10/5. Smaller teams scale proportionally. Human reservations, fixed slots and incomplete pools can relax these counts.

## 3. Random and manual classes

Teams choose independently. Random displays all five icons checked and disabled while remembering manual choices. Switching back restores the remembered manual mask.

Manual checks guarantee one Bot of every checked class and exclude unchecked automatic classes. Humans never satisfy these Bot guarantees. Fixed launcher Bots can satisfy them and are not replaced by room selection.

Checked classes cannot exceed available Bot capacity. Shrinking removes newest checks first and reports them; growing restores none. All manual choices empty selects Random automatically.

## 4. SPG limits

| Total team size | Random automatic artillery range |
| --- | --- |
| 1–6 | 0 |
| 7–9 | 0–1 |
| 10–12 | 0–2 |
| 13–15 | 0–3 |

Automatic remainder accounts for human/fixed artillery. Manual SPG selection guarantees at least one Bot even in a small team, while legal formation limits remain. An explicit all-SPG test lineup is different from automatic filling fifteen SPGs.

An SPG-only selection needing fifteen automatic Bots is refused if the limit makes it impossible. The filler does not silently substitute an unchecked class.

## 5. Impossible selections

A tier-1 player with -2-to-same effectively has tier 1 only. Selecting only HT/TD/SPG when that pool has none refuses start with a reason. Fixed tier modes do not silently raise tiers to meet checks.

Random tier mode may seek another permitted window covering required classes. If none exists, it also refuses. Class guarantees, tier window, available vehicles and artillery quota must all be satisfiable.

## 6. Eligibility layers

1. Read the real supported-client catalogue with legal names, tiers, classes and resources.
2. Exclude missing models/collision or retired placeholder art.
3. Exclude nonstandard event, special-mode, IGR and observer entries.
4. Combine secret with specific suffixes to exclude tutorial clones, Bot/training placeholders and artillery strike emitters. Secret alone does not ban a vehicle.
5. Bots additionally exclude the five explicit retired entries below; loadable manual-player tools need not apply that Bot-only exclusion.
6. Apply room tiers, class choices and fixed assignments to the remaining pool.

Unrecoverable describes sold-item recovery, not automatic battle ineligibility. A hidden reward vehicle is not banned merely for not being sold in the shop.

### Eight resource-unusable entries

| Full vehicle ID | Reason |
| --- | --- |
| germany:G138_VK168_02_Mauerbrecher | Missing required model/collision resources |
| germany:G79_Pz_IV_AusfGH | Retired placeholder art |
| uk:GB70_FV4202_105 | Retired placeholder art |
| usa:A08_T23 | Retired placeholder art |
| usa:A15_T57 | Retired placeholder art |
| usa:A26_T18 | Retired placeholder art |
| ussr:R05_KV | Retired placeholder art |
| ussr:R70_T_50_2 | Retired placeholder art |

### Five Bot-only retired exclusions

germany:G85_Auf_Panther, germany:G98_Waffentrager_E100, ussr:R75_SU122_54, ussr:R93_Object263B and ussr:R96_Object_430B.

Unlike missing-resource entries, these loadable retired vehicles remain available for manual player use but do not populate automatic/fixed Bot lineups.

## 7. Garage additions and crew choices

Garage acquisition and crew-trained vehicle choices share standard-vehicle/resource checks, preventing invalid retired FV4202 105 entries. Crew choices also require matching real seats.

Crew selection does not blindly copy the Bot-only retired list: a manually usable player vehicle still needs recruits. Missing interior module geometry is another issue, not automatic inability to render or enter a battle; see Guide 9.

Source checks: team_class_policy.py, ai/planner.py, vehicle_configuration.py, vehicle_blacklist.py, bot_lineup_profiles.py, retired_vehicles.py, crew_store.py and lan_battle_server.py.
