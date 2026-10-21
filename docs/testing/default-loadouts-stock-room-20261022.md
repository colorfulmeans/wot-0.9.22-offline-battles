# Special defaults, sandbox crew and stock waiting-room controls

## Scope

This PR candidate shares one explicit fitting policy between factory sandbox
vehicles and Bot descriptors. Existing saved fittings are restored as saved;
buying a stock vehicle in a career remains stock. No navigation, collision,
ballistics, target priority, recovery or difficulty law is changed.

## Fitting and ammunition

`default_loadouts.py` contains 32 exact vehicle identities reviewed against the
Chinese HD 0.9.22.0.1 #1513 item definitions. It selects an installable turret/gun
pair before fitting the remaining top modules. This matters for Waffentrager IV:
its 128 mm L/61 requires the 128 mm platform, rather than the 150 mm platform.

| Vehicle | Factory gun | Ordered ammunition roles |
| --- | --- | --- |
| Rhm.-Borsig | 128 mm L/55 | AP, existing premium, HE |
| Waffentrager IV | 128 mm L/61 | AP, existing premium, HE |
| KV-2 | 152 mm M-10 | Silver HE, premium AP; no silver AP |
| S35 CA | 105 mm Schneider AC | AP, existing premium, HE |
| Charioteer | 105 mm L7 | Premium HESH, silver APCR; no silver HE |
| Conway | BL 5.5-inch | Premium HESH, silver AP; no silver HE |
| FV4005 / FV215b (183) | 183 mm | Premium HESH, silver AP; no silver HE |
| O-I Experimental | 12 cm short barrel | HE, HEAT; no AP |
| O-I / O-Ni / O-Ho | 15 cm Type 96 | HE, HEAT; no AP |
| Type 4 / Type 5 Heavy | 15 cm Type 41 | Premium HE only |
| T49 / Sheridan | 152 mm M81 | Premium HE, HEAT; no silver HE |
| SU-152 | 152 mm ML-20 | HE, HEAT; no AP |
| T-44 | 100 mm LB-1 | Existing ammunition rules |
| KV-85 | 100 mm S-34 | Existing ammunition rules |
| T-34-2 | 100 mm 59-100T | Existing ammunition rules |
| T-46 / A-20 | 45 mm VT-42 | Existing ammunition rules |
| T-80 | 45 mm VT-43 | Existing ammunition rules |
| Pz. IV A / Grosstraktor | 7.5 cm L/24 | HE, HEAT; no AP |
| Hetzer / StuG III B / Pz. IV H | 10.5 cm howitzer | HE, HEAT; no AP |
| Sav m/43 | 10.5 cm m/44 | HE, HEAT; no AP |
| SU-100Y / ISU-130 | Existing 130 mm gun | Premium AP, silver AP, HE |
| AT 15 | 32-pounder | Existing ammunition rules |

Roles are logical loadout slots, not currency changes or replacement shell
kinds. Native shot indices, shell IDs, penetration, damage and prices remain
unchanged. Special layouts use 3:2:1 over three roles, 3:2 over two roles and
100% over one role. Largest remainders fill the mounted gun's exact capacity.
Excluded rounds carry zero inventory. Unlisted layouts retain existing rules.

The same identity mapping drives factory garage layout, Bot inventory/initial
round, the legacy client planner and server planner. The manifest sanitizer
preserves complete descriptor names (including dots) instead of truncating
these protocol keys as player display names. This avoids silently losing the
policy in transit. A player's alternate mounted gun does not inherit a policy
for another gun. Existing shell-choice competence/armour checks are retained;
no two-failed-shots escalation is introduced.

## Saves and consumables

New sandbox saves mount large medkit, large repair kit, automatic extinguisher
in that order. Launcher New Save -> No still creates an empty unlocked slot;
its first client bootstrap generates the new defaults. Yes/career mode keeps
its stock vehicles, normal crew and empty consumable slots.

Only the 25 active skill IDs from the supplied full-skill save are retained as
a factory skill mask. Native `generateTankmen`/`generateSkills` filters it for
each seat's combined roles and generates fresh passports. A read-only audit
using the pinned native `generateSkills` reproduces all 2,535 donor members
across 581 vehicles, including combined roles.

The local default save was backed up before migration. Its existing member
identities, role qualification, rank, free XP and dossiers were retained using
the pinned `TankmanDescr` reader/writer. Only skill state was transferred.
Original extinguisher/medkit/repair triplets in `eqs` and `eqsLayout` were
reordered; other customized equipment was preserved. All unrelated JSON fields
and all non-skill descriptor bytes compare unchanged. Existing non-default
saves are not migrated or reset.

## Stock waiting-room UI

The standard/training room uses a mod-owned Scaleform movie and the client's
actual Window, ButtonNormal, ButtonBlack, ButtonRed and DropdownMenuUI
components. Their own animations, sounds, renderer and dropdown list manage
hover/focus/selection. Tier, difficulty and both team sizes use native dropdowns;
no arrow or plus/minus controls remain on this live surface. Leave uses the
stock dark Cancel button. The Window owns its normal top-right close button.

Difficulty still means the existing five presets, ordered Mixed, Rookie,
Regular, Veteran, Elite. Mixed remains the initial default; acknowledged saved
choices remain remembered. Training's existing Bot on/off semantics are kept.
Team size changes keep the existing host checks and joined-player minimum.

Positioning reads the stock BattleQueue's `modeTitle` and `exitButton` bounds
in stage coordinates, then converts into the Window parent's coordinates. It
centres the complete frame in that gap again after a resize, including UI
scaling. It does not use a stale BigWorld pixel size or a fixed vertical screen
fraction when the stock anchors exist. Fonts derive from the stock text
prototype; labels use its body size/colour. Native chrome supplies the insets.

Native callbacks are deferred to the next BigWorld tick before closing or
switching windows. Per-load tokens reject stale load completions and queued
callbacks after a close/reopen. The old template minimap/list/inputs are removed
from the movie before instantiation. The stock map picker and shared movies
are unmodified. Independent service panels retain their existing native GUI.

`tools/build_waiting_room_swf.py` builds against pinned native ABC definitions,
then removes those compile-time definitions. Its output has unique mod-owned
class names. The packaged proof pins client resources, ActionScript, builder
and output hashes; `build_wotmod.py` rejects a stale generated movie.
Rebuild with Java 17, FFDec 26.3.0 and the exact client, passing `--client`,
`--java`, `--ffdec` and `--output src/res/gui/flash/offlineWaitingRoom.swf`.
`tools/verify_default_loadouts.py` independently audits every native identity.

## Verification and acceptance boundary

- All 32 fitting/gun/shell identities verified read-only against #1513.
- All 2,535 donor skill combinations reproduced by native generation.
- Live default-save native roundtrips and unrelated-field isolation passed.
- 395 engine-free/reference test files passed; 23 launcher files passed.
- All 197 client modules compile/verify with CPython 2.7.18.
- Final changed-area and package checks are recorded with the candidate build.

The local reference harness selects the Linux/reference branch because its
modern Windows interpreter cannot load the shipping x86 CPython 2.7 extension.
That is source-level evidence, not an in-game native acceptance claim. The
Windows package build separately verifies the actual shipping native payload.
The user must still check Chinese rendering, native dropdown animation, real
resolution changes and the configured vehicles in the exact game client.
Keep this candidate on PR113; do not tag, merge or publish 0.10.2.
