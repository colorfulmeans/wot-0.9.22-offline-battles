# Special defaults, sandbox crew and stock waiting-room controls

## Current follow-up: equipment effects and crew consumers (2026-11-02)

This section supersedes the original scope's collision/ballistics exclusion for
the new equipment-consumer fixes only. Original fitting/ammunition decisions and
player native ammunition are unchanged. Runtime changes are detailed in
`COMPATIBILITY_REVIEW.md`, "Equipment effects and living Bot crew audit".

Acceptance must distinguish native item availability, successful installation,
factor donation, actual damage/perception and final-package Windows behavior.
The 49 device / 15 directive resource definitions are the inventory baseline;
modern Equipment 2.0 or changed crew skills are not substituted for #1513 data.

New regression coverage checks all four native liner protection coefficients at
the real crew-roll entry, direct and explosion paths, player protection handoff,
invalid protection values, confirmed track-support suspension reduction, missing/
roof/wall contact exclusion, server damage exactly once, reliable contact-normal
queue handoff, Recon healthy/yellow/destroyed states, physical Bot crew roles and
injuries, native perception flags, Controlled Impact, Deadeye shot projection and
Intuition inventory/reload/one-decision gates. Fire diagnostics are tested to
report the native directive factor and explicitly disclose its unapplied status.

`build/equipment-effects-final-local/summary.json`: 17 files, 567 tests passed.
All 224 client files passed CPython 2.7 compilation. Cloud results and exact-package
Windows observations are pending; do not reuse the earlier package's acceptance.
Firefighting and full native fire/ram calibration are not claimed fixed.

## Scope

This PR candidate shares one explicit fitting policy between factory sandbox
vehicles and Bot descriptors. Existing saved fittings are restored as saved;
buying a stock vehicle in a career remains stock. No navigation, collision,
ballistics, target priority, recovery or difficulty law is changed.

## Fitting and ammunition

`default_loadouts.py` contains 33 exact vehicle identities reviewed against the
Chinese HD 0.9.22.0.1 #1513 item definitions. It selects an installable turret/gun
pair before fitting the remaining top modules. This matters for Waffentrager IV:
its 128 mm L/61 requires the 128 mm platform, rather than the 150 mm platform.

| Vehicle | Factory gun | Bot ammunition roles |
| --- | --- | --- |
| Rhm.-Borsig | 128 mm L/55 | AP, existing premium, HE |
| Waffentrager IV | 128 mm L/61 | AP, existing premium, HE |
| KV-2 | 152 mm M-10 | Silver HE, premium AP; no silver AP |
| S35 CA | 105 mm Schneider AC | AP, existing premium, HE |
| Centurion 7/1 | 105 mm L7 | Premium HESH, silver APCR; no silver HE |
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

Gun overrides apply to factory garages and Bots. Player garage ammunition
always uses native getDefaultAmmoForGun; special shell roles apply only to Bot
inventory/initial round, the legacy client planner and server planner. The manifest sanitizer
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

## Package 451 regressions and follow-up

The 06:02 report confirms a worker startup failure at native_weapons._ammo_row:
excluded native shot index 0 has no Bot role, but serialization indexed that
sparse role map as dense. The native ABI requires one category per physical
shot. The adapter now serializes excluded slots with zero inventory and an
inert valid category; native availability checks already skip zero inventory.
Nonzero inventory for an excluded slot is rejected. No native ammunition IDs,
physical kinds or availability rules are changed.

The stock CLIK producer initializes dynamic fields in configUI, which runs on
first validation; Python population may publish earlier. The room now validates
before applying the first model, initializes stock controls before setting their
labels, then invalidates Window.INVALID_SRC_VIEW so native updateSource measures
620x244 content rather than the retained prototype. A bounded initialization
message records content/frame dimensions and text lengths. This lifecycle fix
is compiled against the pinned native implementation, but exact-client visual
rendering and real mouse-state behavior still require the next user test.

Player garage shell overrides have been removed at the user's clarification;
factory gun overrides, consumable order and full-skill sandbox defaults remain.
Centurion 7/1 uses its native 105 mm L7 with HESH/APCR for Bots only.

## Package 452 native-control and performance follow-up

The user's 06:36 report and screenshot show that first-population ordering was
only part of the room problem. The title/content now appear, but menu labels
are compressed, dropdowns do not open, and the BlackButton face exceeds its slot.

The pinned settingsWindow producer references DropDownListItemRendererSound;
DropDownListItemRendererSoundUI is only an inferred authoring name and has no
stock SymbolClass. The runtime string is corrected. Menu configuration now
uses the native rowCount setter (which owns _maxRowCount), menuRowsFixed,
Padding and finite thumb offsets. Stock dropdown/button heights are retained;
only the explicitly compact red battle button changes height. BlackButton
must use its width setter: setSize bypasses rescaleItems and leaves the internal
160-pixel state clips unchanged. Components use the native class factory.

The dynamic room establishes _originalWidth/_originalHeight before the Window
captures content constraints. Replacing only graphics and logical setSize in
configUI leaves the text prototype as the virtual scale denominator. Native
constraint counter-scaling can then distort children despite correct logical
620x244 dimensions. Initialization now establishes the correct scale baseline.
Centering measures the stock frame background, so a popup or hover glow
cannot enlarge the positioning rectangle. One-time diagnostics include actual
scale and each control's logical/bounded size. The builder validates runtime linkage strings against the pinned shared
movies' SymbolClass tables before compilation.

Performance evidence is independent of the UI: round 4's worst worker callback
was 2696.619 ms, including 2439.587 ms in Bot updates and 250.743 ms in Bot events.
It consumed 13 physical slices and 2.591 seconds of elapsed simulation time;
the previous expensive callbacks caused additional catch-up work. At the same
time the visible client did not exhibit a comparable multi-second main callback.
This establishes worker CPU work rather than an Internet explanation, but does
not identify every expensive collision path as redundant.

The native frontier records repeat exact ray geometry. A read-only rotation
sweep now allows its commit-disabled world sub-solves to share exact unfiltered
raw rays. Filters, changed endpoints, ground/ordinary ray kinds, spatial
revisions, effect invalidation, other owners and nested sweep lifetimes retain
their boundaries. The batch is bounded by the existing 256-entry cache cap and
is discarded in finally; ordinary driving cannot borrow it. Rotation and
translation physics also have separate timing stages for the next report.
No timestep is dropped or enlarged, and catch-up scheduling is unchanged.
Tests demonstrate 16 identical read-only ray requests across eight sub-solves
use one native call, then require a fresh call in the next sweep. This is a
query-count proof, not a measured claim that the live 999ms spike is eliminated.

No further save reset, ammunition change, navigation, collision/LOS policy or
support-rule change is included in this follow-up. Exact-client UI interaction,
resolution changes and live worker latency remain user acceptance checks.

## 2026-11-01 reviewed guns and elite premium defaults

The current exception table contains 37 vehicles. Four new full-development
choices are shared by unlocked player creation and veteran/elite Bot plans:
M3G FT 57 mm, Pz.38(t) 47 mm, Stuart I-IV QF 2-pdr and Chi-He 57 mm. M3G
uses its compatible first platform. Stock/intermediate modules and AT15's
32-pdr are retained. Existing custom player fittings are not forcibly rewritten.

Elite difficulty transfers silver non-HE quotas to native premium non-HE rounds,
retaining the existing HE identities and primary order. Manual ratios win;
guns without a premium counterpart retain their previous ammunition. Difficulty
is propagated in tactical profiles, independently of development and crew
overrides. Default seed revision 4 replaces the disposable default once.

Validation before packaging:
- Exact client inspected: Chinese HD 0.9.22.0.1 #1513, x86.
- `verify_bot_fittings.py`: 576 vehicles / 9,216 records passed, including
  elite premium-round exclusion, HE preservation, capacity and whole magazines.
- Focused gun/ammunition, worker/server wire, late-result and save-revision
  regressions passed locally.
- A broader local combat-lineage run requires the matching native simulation;
  the bundled local interpreter also lacks `imp`. This is not reported as a
  passing native integration check. The Python 3.11 CI/native job and final
  Windows package/runtime acceptance remain separate evidence boundaries.
- Diagnostic `bot_ammunition_initialized` records fitted gun, shell identities,
  tier, manual override status, counts and initial loaded index.

Package, CI and live-client results are recorded below after those stages.

Cloud/package acceptance for source `383c065`:
- PR #119 Tests run 41286763384 passed, including the Python 2.7 compile,
  gameplay/native regressions, full client suite and Windows editor/server jobs.
- Build Windows launcher run 41286762316 passed. Its actual downloaded artifact
  passed frozen-source/native-payload, extracted-root install and bundled-server
  checks on Windows.
- Independent local ZIP inspection passed: x64 launcher, x86 native payloads,
  Python 2.7 client bytecode, one normal EXE and one diagnostic BAT, and exact
  changed server-side source bytes. Build identity is
  `colorfulmeans-41286762316-1`; semantic version remains 1.1.1 for this test build.
- Local default seed was reset to revision 4 and a clean unlocked save with
  slot ID `save` was created. Both have no restored garage fitting state.
- The user accepted the original client EULA. The final extracted package was
  then exercised through its diagnostic entry on the exact #1513 Windows client.

Native acceptance on 2026-11-01, using the packaged source above:
- Two standard 15-versus-15 Mittengard battles completed and returned to native
  results/garage: a low-tier reviewed-gun lineup and a high-tier special-ammo
  lineup. The player was idle; these are installation, Bot weapons and lifecycle
  checks, not player gunnery-performance measurements.
- Low-tier native fitting records confirmed all four new guns and M3G's first
  platform. The player's Chi-He gun menu independently showed the 57 mm gun
  installed. All 29 Bots initialized elite ammunition; the four native counts
  were M3G [0,47,5], Pz.38(t) [0,50,6], Stuart [0,88,10], Chi-He [0,72,8].
  The server accepted 210 Bot shot results, all using shell index 1.
- The high-tier player's AT15 gun menu showed the retained 32-pdr installed.
  All 29 Bots initialized successfully. Representative native inventories:
  AT15 [0,45,5], Rhm.-B. WT 128 mm [0,27,3], T49 [0,4,18], Type 4 [0,40],
  Centurion Mk.7/1 [14,58,0]. The Centurion intentionally retains its APCR/HESH
  policy because this gun has no premium non-HE replacement.
- The high-tier server accepted 151 Bot shot results (129 index 1, 17 index 2,
  five index 0). Bot 26's actual sequence included 1,2,2,1: premium penetration
  ammunition, two HE shots, then premium penetration ammunition again. Index 0
  shots belong to the retained Centurion exception; shell indices alone are not
  a price/type classification across different guns.
- These checks preserve the previous HE policy, including artillery's normal
  80/20 HE split (75/25 for clips). They do not claim artillery now uses only
  premium HE. Manual-ratio and whole-magazine coverage remains automated;
  neither was exercised through a live manual override in these two battles.
- Reports `wot-error-report-20261101-173552-67733aad5622.zip` and
  `wot-error-report-20261101-175713-52b6d461b3e3.zip` were generated through the
  launcher after each battle. Both archives passed integrity checks. Their
  hidden-worker, visible-client and server logs contained no ERROR entries or
  Python tracebacks. This is scoped runtime evidence, not a claim that every
  map or unrelated gameplay subsystem is defect-free.
- After normal client/worker shutdown, the two disposable acceptance saves were
  reset again. `default` (revision 4) and unlocked slot `save` each contain only
  their seed metadata; test battle progress/fittings were not retained. The
  launcher was restored to Automatic lineup and the default slot.

## 2026-11-01 refined elite HE and penetration exceptions

This follow-up supersedes the earlier elite-ammunition baseline. RHM B WT
uses its native 150 mm full gun; WT auf Pz. IV remains on 128 mm L/61. The
shared override table has 36 entries. SU-5's model 1930 122 mm gun uses only
the native 420-damage OF420SO at every default difficulty. This does not
change the SU-5 stock 76 mm or full 152 mm gun.

Elite defaults upgrade silver penetration rounds except on HE-primary guns
and the exact SU-100Y/B-13-S2 and ISU-130/S-26A pairs. Those keep their
original penetration backups, proportions and shot-result switching. Ikv 103
has no exception. Silver HE upgrades to a real premium HE on the same gun,
with quotas merged before whole-magazine allocation. Native HE remains when
there is no premium HE. The existing Sexton I/leFH18B2 HE-only restrictions
remain authoritative. Manual ratios, including all-zero, still win. Default
seed revision 5 rebuilds the disposable default once.

The test baseline now distinguishes native shell price from logical primary
and backup roles. Two silver HE rounds must not be misclassified as a
silver/premium pair; two premium-role labels do not imply premium currency.
The resource audit checks elite ammunition on every development/equipment
combination, rather than only the default full-development elite preset.

Pre-package validation:
- Exact #1513 audit passed for all 576 vehicles / 9,216 fitting records,
  including native modules, compatible turrets, legal equipment/load,
  penetration-backup identities/quotas, premium HE substitution, full capacity
  and whole magazines. Guns without a premium HE retain the original HE.
- All 36 special gun identities and gun-keyed ammunition policies passed the
  independent packed-resource identity audit.
- Focused fitting, special-loadout, elite-ammunition, shot-policy, late-result,
  worker-ammunition and garage suites passed. Save-slot/customization suites
  passed. All 224 client source files compiled with CPython 2.7.
- The dedicated CI step "Check Bot fitting presets and elite ammunition
  switching" runs fitting, special-default and elite-ammunition regressions.
  It covers premium-to-HE/two-shot return, HE-primary one-shot penetration
  probes, both 130 mm silver-AP fallbacks, HE-only legacy artillery, SU-5,
  manual overrides, clip allocation, Ikv 103 and RHM/full-development choices.

Cloud/package validation for runtime `096cf610a9dd000f36bf23237e97fdc98bd94d50`:
- [Tests run 41302257329](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/41302257329): all eight jobs passed, including the dedicated fitting/ammunition step.
- [Windows build 41302253472](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/41302253472): server, client payload and launcher jobs passed.
- Downloaded final artifact 13081704896 (`windows-561`); archive and nested
  payload CRC checks passed. Launcher is x64, native extensions are x86,
  Python bytecode is 2.7, and packaged server policy/fitting sources match
  the committed runtime. Only the normal EXE and diagnostic BAT are exposed.
- Package identity: `colorfulmeans-41302253472-1`, semantic version 1.1.1.
  Extracted to `D:/Games/wot-mod/9.22/PR119-096cf61`.
- The user accepted the client EULA. Final native acceptance below was
  performed on this exact package and #1513 client.

The earlier 383c065 package evidence does not validate this new runtime.

### Final refined-ammunition Windows acceptance

Two diagnostic sessions on Mittengard completed and returned to native battle
results. The first used the default save and `QA HE low`; the second used a
fresh unlocked `save` slot and `QA HE exceptions`. Each initialized 29 Bots.
The launcher's selected profile was visibly checked before starting.

- Low-tier actual inventories: SU-5 regular/model-1930 122 mm `[0,18]`,
  loaded 1 (420-damage HE); elite Sexton I `[112,0,0]`; elite leFH18B2
  `[42,0,0]`; elite Hetzer 105 mm `[0,4,16]`, loaded HE index 2; elite
  Ikv 103 full gun `[0,24]`, loaded premium HEAT index 1. The server accepted
  48 Bot shot results. Hetzer's sequence included `2,1,2`, exercising its
  one-shot penetration probe and HE return in the real client.
- High-tier actual inventories: elite RHM `_150mm_Rohr_L29_5` `[0,27,3]`;
  SU-100Y `[9,18,3]`; ISU-130 `[8,15,2]`; SU-14 `_203mm_B-4` `[0,16]`.
  All loaded index 1. The two 130 mm vehicles retained their actual silver
  AP backup identities and quotas. All 49 accepted Bot shot results used
  index 1. This battle did **not** exercise their silver-AP fallback or an
  ordinary-gun two-shot HE return; those transitions are covered by the
  explicit automated shot-result tests, not claimed as native observations.
- The player's RHM was checked before battle in the fresh unlocked save:
  native installation menu showed a green check on `15 cm Pak L/29.5`,
  while the rack remained native default `[18 AP,0 HEAT,12 HE]`. Reviewed
  player module defaults therefore applied without importing Bot premium
  ammunition. Vehicle creation and gun changes still use native
  `getDefaultAmmoForGun`; the Bot shell restrictions are not player policies.
- Reports `wot-error-report-20261101-203203-0f29114ea332.zip` and
  `wot-error-report-20261101-204928-e13a4e1747cf.zip` were generated through
  the launcher after the respective results screen. Both passed archive
  integrity checks. Hidden-worker, visible-client and server logs contained
  no ERROR entries or Python tracebacks.
- The desktop host's app-data virtualization initially kept prepared QA
  settings separate from the launcher's physical user settings. That setup
  mismatch was resolved before either accepted battle; observations from the
  earlier no-battle launches are not used as ammunition acceptance evidence.
- After normal shutdown, the physical default and full-unlock test saves were
  rebuilt again. Both contain only `save.json`; the default seed is revision 5.
  Launcher selection is restored to Automatic lineup/default with a blank
  player name. Reports remain available for review.
