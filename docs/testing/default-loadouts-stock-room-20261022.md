# Special defaults, sandbox crew and stock waiting-room controls

## November 3 foreground-only player replacement baseline

The b2cf35b7 implementation is withdrawn, not an accepted baseline. Its source
was removed in ffa14996 and BattleRuntime restored to pre-control 0e4146f7 before
replacement. The new player_control package owns its own driving, recovery,
weapon/aiming, shell-result state and consumable choices in the visible client.
It imports no BotRuntime, BotAdapter, LocalDriver, Bot gunner or Bot ammo policy.
Shared services are immutable map/fitting data, terrain search, native geometry,
normal human physics/projectiles and the existing trusted-LAN authority.

| Case | Required observation |
| --- | --- |
| Foreground fence | No controller in hidden worker or replay. No Bot actor/allocation registration. Bot control sources unchanged from the rollback boundary, except unrelated earlier governor-wear correction retained. |
| All feature masks | Each of eight drive/fire/consumables combinations claims only its channels. Overall off attaches no controller. |
| Aim | Native shotPointSourceFunctor owns the target point with clientMode true. Mouse may move camera, never the automatic barrel. Disable restores the previous source/mode. |
| Native shot | Trigger through Avatar.shoot, then its normal mailbox/wait/muzzle path. Actual ammo, visible muzzle and damage must settle; sound requires native observation. |
| Results | Projectile impact is published before combat effects. Vehicle contact without effect is pending, then unknown if no receipt arrives; never synthesize a failed penetration. Repeated real penetrations cannot switch to HE. |
| Travel | Behind-tank targets pivot before forward travel. Near local tips are not reverse goals. Rear recovery requires measured nonprogress and a clear rear corridor, stays latched for one bounded maneuver. Reject mountain/water/cliff receipts. |
| Rejoin | Rank main and reserve routes in 3D, then prove connected support. Overhead bridge snapping and disconnected nearest nodes cannot win. |
| Handover | No discarded accepted shot or burst; restore manual fire/aim. Repeated toggle, countdown press, death and battle change tested separately. |
| Player traffic | Real friendly hulls and corpses block swept travel; adjacent clear directions remain usable; an overhead hull cannot block a lower road. Record blocker identities and actual pose. |
| Player strategy | Own-base capture preempts travel; distant incidental targets cannot pin the defender. Clearing alarm rejoins routes. Only stable observed front pressure can redirect this human; no Bot orders change. |
| Forward barrel | With automatic fire enabled but no selected enemy, gun follows hull heading; disabling fire takeover restores manual aim. |
| Three-shell test | Carry positive standard/premium/HE stock. Two confirmed ineffective hits switch to next available shell; positive HP damage resets failure count; HE returns on its bounded probe. |
| Panel | Click Toggle, Stop, Fire and each timed direction; verify actual pose/ammo, not command append alone. |

Automated replacement cases: test_player_control. Native acceptance must record
exact package identity and individual passes/failures below COMPATIBILITY_REVIEW.
Earlier Bot-adapter force-balance expectations are historical and superseded.

## November 3 integrated test-page baseline

Scene entry is now **Testing -> Test scene -> regular Start**, in either normal
or diagnostic launcher mode. The previous Repair-page scene buttons are obsolete.
Logs, scene selection and player control are independent remembered choices.
Do not validate this build against screenshots expecting those old Repair buttons.

| Case | Required observation |
| --- | --- |
| Real desktop, Chinese/English | Three inside-title sections, shared margins/buttons and help text; page scrolls at the normal window height and the mouse-panel button is reachable. |
| Fixture transitions | Equipment/drop/governor/baseline/matrix/rewards select existing current fixtures; returning to Normal clears every prior scene flag. Network/replay never loads a single-player fixture. |
| Ammo warning cancellation | Empty ammo -> Join -> Cancel -> supply ammo or retry: native validation opens again and successful confirmation reaches waiting room. No restart needed. |
| Player control off | No input wrapper or automatic vehicle changes. |
| Player control enabled | Each battle begins manually; grave key toggles once per physical press in arcade, sniper and strategic mode. Chat/input/menu focus does not toggle. Native local message only; no player chat packet. |
| Countdown key | Press during countdown, release, then press after battle begins; the live toggle still works. A missed countdown release must not latch a later live press. |
| Automatic planning | The player owns no Bot force-balance actor; hidden enemies do not become contacts. A nonempty blocked probe receipt is rejected for collision/water/grade. Movement alone or repeated pivoting is not acceptance. |
| Mouse/script | Toggle/Stop/Fire and bounded timed driving use the same controller. Driving replaces the automatic writer. Stop clears movement and its aim source, while admitted shots/bursts settle; next round ignores old journal commands. |
| Loadout/physics ownership | Actual player modules, rounds, equipment and crew remain intact; the visible player still owns normal physics and shots. No second Bot simulated vehicle is created. |
| Lifecycle | Death/results/cleanup stop inputs; current handler wrapper is removed without replacing a later third-party wrapper. Rejoin starts manual. |
| Credits | Preserve all 375 measured workbook coefficients; derive premium estimate cohort from gold-price eligibility, not incomplete raw roster tags. Type 59 remains 1.5750. |
| XP | Gold Type 59 / Type 62 / WZ111T base XP x2 precedes scoreboard/mission/account bonuses exactly once; ordinary premium IX/X has +5% settlement XP. Unresolved Churchill III / ordinary WZ111 base coefficients are labelled in diagnostics. |
| Governor wear | Whole seconds below half base forward speed; split frames equal a slow frame. Disabled/half-speed periods clear the partial wear clock for both owners. |

Automated evidence is in test_player_control, test_testing_panel,
test_launcher_layout, test_governor_wear_clock and the existing queue/rewards
consumer suites. Installation/decision logs alone are not proof of successful
movement, damage, give-up or every consumable effect. Candidate cloud and native
acceptance remain separately identified in COMPATIBILITY_REVIEW.md.

## November 2 repair/directive acceptance baseline

Repair expectations now use physical workforce, not one time for every crew:
four conscious members without Repair: tracks 12 s, other modules 21.6 s;
two members: 24/43.2 s; six: 8/14.4 s. Native full-Repair factor 1.0 multiplies
those times by 0.57; a four-person crew with one 80% carrier uses the native
20% average. Injuries reduce physical workforce and remove that carrier's
skill contribution. Equipment/directive and available-kit bonuses apply once.
These absolute references are authorized offline calibration, not retail data.
Check both owner-CAS tracks and authority-side modules, healing, re-injury,
split/slow frames, interrupted repair and no work after all crew are unconscious.

The Testing tab's scene selector has two matched matrix scenes. Baseline has no devices,
no directive and no learned secondary skills; varied fittings use the same modules
and crew level with one independently named item/skill case per vehicle. Compare
the matching vehicle between scenes, not two unrelated tanks. Installed fitting
logs establish installation only; actual repair/fire boundaries and their factors
must be read from consumer logs. Fire parameters still require external calibration.

Crew XP acceptance requires 600 -> 540 for an injured member while their healthy
colleague keeps 600; healed crews keep full XP. Duplicate delivery and restart
must not pay or penalize twice. Preserve named double-loader identities and an
early leaver's final accepted injuries. A different passport in the same seat must
not inherit the injury penalty. Existing receipts without injury facts stay neutral.

Local automated regression and native resource audit results are recorded below
after final validation. Windows installation/consumer results must be identified
separately; the scenes do not by themselves prove all 49 devices/25 skills/15
directives/21 consumables independently.

Pre-package local checks: 22 isolated affected test files / 1,930 tests passed;
the two diagnostic/layout launcher files passed seven tests. Exact #1513 resource
audit passed 576 vehicles / 9,231 fittings including all fifteen matrix cases.
All 228 client Python source modules compiled under CPython 2.7.18. Three old
repair lifecycle assertions were updated to the explicit three-person 16 s
reference; their regen-cap, yellow-state and second-destruction checks remain.

Native iteration evidence (not final-package acceptance): runtime 40936163,
build colorfulmeans-41398643599-1, session 20261102T065544Z-7312209835cb,
report wot-error-report-20261102-151042-7312209835cb.zip. Both processes admitted
all fifteen fitting cases; the worker recorded a real track-repair start with
four conscious physical members, repairSpeed 0.6270000008493661 and calculated
10.9090908943 seconds. The frame advanced 0 -> 0.8827056897 HP over 0.1069946 s.
This is a real consumer start, not a completed repair or a per-vehicle retail
calibration. One player shot intent reached both visible client and worker.
No fire consumer was triggered. The round's waiting roster was rejected, so
this session is a failed full-lifecycle acceptance, despite successful fitting
and repair observations. Its explicitly requested shutdown had no crash roles.

Build colorfulmeans-41404212831-1, baseline session
20261102T072548Z-b80fe25a7137, installed no devices/directives for all fifteen
cases and reported native repairSpeed=0.57 throughout. Its new roster-rejection
diagnostic showed all static/equipment/assignment gates valid; source review
identified invalid diagnostic room vocabulary (`elite` in both room-mode fields).
The repair uses same/brutal and preserves per-slot elite skills. All four scenes
now pass an actual server-reset -> shipping-client roster round trip. The four
affected protocol/equipment files passed after that correction. Earlier fdb2b7e6
cloud failure was a packaged Tk smoke adapter missing `_t`; 4006096c's failure
was the rejection logger's relative import in the standalone test adapter.
Both adapters were corrected; final cloud/native results must supersede these
intermediate failures before calling the package accepted.

### Final November 2 afternoon package acceptance

Runtime f53ed00acc992942e378d2593bc35ef1053b132a, build identity
colorfulmeans-41407829058-1. Cloud Tests 41407834004 passed all eight jobs;
Windows package build 41407829058 passed all three jobs. Artifact 13124064708
is 124,908,088 bytes; downloaded SHA-256:
c5cae3ecf66f37d1515eae688922e079c8d316016cce951cab9e4485ca3607ce.
Independent extraction verified CRC, path/symlink safety, x64 EXE, x86 native
module, both outer launch entries, bundled server sources and all 228 shipping
Python-2.7 module signatures against the final source. Package location:
D:/Games/wot-mod/9.22/PR119-f53ed00a; download PR119-f53ed00a-Windows-x64.zip.
The final four isolated equipment/protocol files passed 291 tests, including
the actual room-reset round trip for all four diagnostic modes. The complete
1930-test affected suite preceded that one added regression; final cloud runs
cover the corrected files, rather than reusing the intermediate suite as a
claim about the final SHA. Packaged diagnostic labels were checked in Chinese,
switched to English and back; all five labels refreshed without clipping.

Actual final Windows session: 20261102T075947Z-cd41af7e6bf2, SU-152 player,
Mittengard 15:15 varied-fitting diagnostic scene. Visible and worker logs each
accepted all fifteen named fitting cases. Both recorded player shot
1:p:1:1 / input 4479 / launch_ms 157340. Two worker track-repair starts recorded
four conscious members, native factor 0.6270000008493661 and reconstructed
10.9090908943-second repair time. The round ended by capture, displayed the native
victory result and restored the garage. Opening the next waiting room succeeded;
the server retained its player connection until the explicit launcher stop.
No roster rejection, transport failure, Python traceback, assertion, worker
failure or fatal error was found in any of the four session logs.

Report generated through the final package:
wot-error-report-20261102-161331-cd41af7e6bf2.zip (11,275,371 bytes), under the
isolated PR119-40936163-QA/Local/WoTOfflineBattles/reports directory. Report CRC
passed and all four complete log members were present. The session ended at
2026-11-02T08:12:03.184231+00:00 with no crash roles or crash dumps. Local audit
record: build/equipment-repair-final-native-audit.json (not shipped source).

Limits remain explicit: native repair observations are consumer starts, not a
timed completed repair for every vehicle. This session did not trigger a fire
consumer or terminal wounded-member XP case; those transitions have automated
coverage, not new manual gameplay proof. Absolute repair/fire/module parameters
remain documented offline reconstruction. The 790 packed vehicle/common
definitions contain no healthRegenPerSec, healthBurnPerSec or hysteresisHealth
fields; their absence is not replaced with a claimed native numerical table.
Documentation-only acceptance commits after this runtime do not alter the
validated binary identity.


## Current follow-up: fire, consumables, priorities and diagnostic scenes

Acceptance baseline is the user-approved official-first/community-second source
order. Known ineffective behavior is not preserved merely because server data is
stripped from the client. Fire shape follows the linked community experiment;
absolute five-percent initial rate and ten-second bare-crew duration are labelled
offline calibration. Expected 1000-HP bare-crew fire integral is 250 HP, full
native factor 1.0 is 142 HP after integer integration (5.7 s); native directive
factors accelerate decay further. Check interval splitting, injury continuity,
slow-frame cutoff, reignition, server receipt/handoff and module ownership.

Equipment baseline is the new five-class priority table in equipment_policy,
with separate Bot table and player default installation verification. Existing
explicitly unlocked saves reset once; zero-start metadata and state must remain
byte-identical. Mouse-fire equipment targets and shot-triggered bridge drops are
selected inside the diagnostic Repair tab. No third external launcher entry.

Local evidence: 18 isolated core files / 566 tests passed; 57 launcher tests
passed, including unlocked-reset idempotence and zero-start preservation. All
227 client modules compile with CPython 2.7.18. Static native-resource audit
passed 576 vehicles / 9,216 fittings. The full battle runtime file passed 1,016
tests. Restored drop fixtures passed 25 tests. Bot lineage fire expectations were
updated to the new integral; full final/cloud acceptance remains pending.
Do not reuse the previous runtime/package hash or its
Mittengard session as acceptance for this candidate. First local iteration found
old fixed-fire numeric expectations and a synthetic Bot factor-cache identity
that omitted consumables; their explicit fixture contracts were updated, without
relaxing receipt deduplication, injury eligibility or geometry validation.

Additional governor baseline: ordinary Bot kits are unchanged. Diagnostic Repair
also exposes a governor driving scene with native removedRpmLimiter installed.
Uphill requires two uninterrupted simulation seconds; stop/level/downhill/airborne
or engine damage cancels. Reverse travel uses signed terrain grade, not suspension
rocking. Actual admitted wreck contact enables immediately; two seconds without
0.1 m wreck translation cancels without immediate retry. Wreck rotation alone is
not progress. Real displacement or a new contact can renew the attempt. No vehicle
movement/recovery law is replaced by the governor controller.

Local review caught and repaired an invalidation that removed installed Bot physics
when its consumable ledger refreshed. The full 550-test Bot file passed afterward;
contact/mass/wreck assertions were retained. Windows editor smoke fixtures now
supply their language and diagnostic callback explicitly. The separate real native
acceptance and cloud checks below still need to be completed for the final SHA.

Candidate 3f26bacf cloud Tests 41348518035 passed all eight jobs; build
41348512207 passed all three jobs. Downloaded artifact 13100886205, 124887659
bytes, CRC/x64 launcher/x86 native/two outer entries/227 Python-2.7 module code
signatures all passed. Its actual Windows governor launch was rejected at Bot
startup: bot_consumable_contracts still only admitted the ordinary three kits.
This is a failed native acceptance, not a passed round. The default save revision
advanced 5 -> 6 and both existing unlocked saves reset to equipment revision 6.

The repair adds exactly the diagnostic large-extinguisher/large-medkit/governor
contract to the same canonical snapshot validator, gated by diagnostic governor
mode. The regression now drives native-item projection through the real validator
and snapshot restore, and verifies rejection when diagnostic mode is off. A fresh
final build and native round remain required after this change.

The restored bridge fixture also exposed a saved-room interaction in the actual
client: remembered 15:15 controls overwrote the fixture's one-player first team,
and the old queue admitted friendly Bot IDs. Native log confirmed the first shot
released friendly Bot 2. The fixture now reasserts 1:15 at request_start and its
queue excludes team 1; both regression tests pass (27 total bridge tests). This
observation is not accepted as a successful falling/contact test. Final-package
native acceptance must be repeated after both diagnostic repairs.

Candidate 31e63597 repeated the native governor startup failure. Its actual
BOT FITTING records revealed mixed rookie/regular/veteran/elite levels despite
the scene constructor requesting elite: saved room options replayed later, and
explicit lineups themselves reset the room's initial difficulty. The restricted
governor validator correctly rejected small-kit or empty rookie loadouts. The
fixture now pins skill on every lineup assignment, reasserts elite skill/tier at
request_start, and resolves diagnostic consumables from the elite native cache
for every incoming skill. The regression covers all four incoming ratings through
the actual BattleRuntime resolver and canonical consumable validator. Contract
errors include the rejected names. Ordinary game skill/loadout policy is unchanged.
This failed native session is 20261101T213157Z-c669b2651a15.

### Final runtime f73d9893: actual Windows acceptance

Shipping runtime is f73d98930ec4da9c70eb18a53fbe05fd4dde9c08, build identity
colorfulmeans-41353174329-1. Cloud Tests 41353177539 passed all eight jobs;
Build Windows launcher 41353174329 passed all three jobs. Artifact 13102034051
is 124,889,048 bytes. Independent download checks passed ZIP CRC, path/symlink
safety, x64 launcher, x86 native module, exactly two outer launch entries,
bundled server-source equality and all 227 Python-2.7 client code signatures.
The extracted package is PR119-f73d9893. Documentation-only acceptance updates
after this runtime do not change the tested binary identity.

Final affected local suites passed 1,624 tests across five isolated files
(follow-up 10, battle runtime 1,016, Bot runtime 550, consumables 21, bridge 27).
The isolated launcher suite passed 47 files / 1,239 tests. Exact-client static
resource fitting audit passed 576 vehicles / 9,216 cases. These are separate
checks, not counts of independently observed retail effects.

The exact Chinese HD #1513 client was operated through the downloaded diagnostic
launcher, without a source-tree client overlay. Governor scene session
20261101T215722Z-37b0d333cd90 ran 15:15 on 100_thepit. Fifteen distinct vehicle
fitting records all used elite skill; the visible player's Caernarvon AX retained
the new HT liner/rammer/stabilizer arrangement. Completed session logs recorded
125 governor transitions across 17 Bots (63 on / 62 off). Uphill enable waits were
2.0000--2.1940 simulation seconds; stop and non-uphill transitions disabled it.
Actual wreck contact was exercised as well: four continuous-contact no-progress
shutdowns occurred after 2.039, 2.159, 2.099 and 2.045 seconds. Other records showed
contact departure disabling it. Recontact is a new attempt; this does not stop
the ordinary vehicle recovery planner. Eight large-medkit effects and one
automatic-extinguisher effect were also recorded. This establishes live effect
dispatch and governor switching, not an isolated retail engine-wear measurement.

Governor report wot-error-report-20261102-060201-37b0d333cd90.zip was exported
while the round was running. Its four logs passed CRC and contained zero Python
tracebacks, consumable-contract rejections or worker failures. That report was
captured before the later wreck-contact transitions; the completed session log
audit native-equipment-20261101T215722Z-37b0d333cd90.json preserves those later
records separately. Do not attribute later events to the earlier ZIP capture.

Bridge scene session 20261101T220416Z-a72e9b12127e ran 1:15 on 37_caucasus.
One acknowledged player shot released enemy Bot 16, then recorded two apron
waypoints and native falling at y=-4.0184. Native world geometry supplied the
upper bridge and lower player positions. The visible enemy landed on the player;
both lost HP and native/server VEHICLE STACK records confirmed sustained contact.
The fixture did not set velocity, gravity or damage. Its report
wot-error-report-20261102-061007-a72e9b12127e.zip passed CRC; all four logs had zero
Python tracebacks and zero worker failures. Server log contained 1,175 stack
records; worker log contained four shot-drop events. The subsequent intentional
Close game action emitted worker_disconnected, which is an operator termination,
not a failed native startup. An initial transient invalid-roster toast cleared
when remembered room controls replayed; the room then started successfully.

Static equipment scene session 20261101T221243Z-3c8630970ed5 then ran 15:15 on
100_thepit. Fifteen distinct elite fitting records were present, targets held
position and did not return fire, and mouse fire consumed player AP (40 -> 39)
with acknowledged PLAYER SHOT TIMING. Report
wot-error-report-20261102-061842-3c8630970ed5.zip passed CRC. All four logs had
zero Python tracebacks, worker failures, removedRpmLimiter mentions and shot-drop
events. This checks scene switching and absence of governor/drop flag leakage;
it is not a controlled per-equipment damage comparison.

These scenes prove actual installation, live switching and restored contact-test
delivery. They do not by themselves measure every skill, directive, repair time,
fire chance, HE liner reduction or collision coefficient. Community calibration
and the remaining reconstruction boundaries above are retained explicitly.

## Previous package: equipment effects and crew consumers (2026-11-02)

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

`build/equipment-effects-candidate2-local/summary.json`: 18 files, 576 tests passed.
All 224 client files passed CPython 2.7 compilation and final-package bytecode
signature comparison. Cloud Tests run 41326363485 (f5a5828) passed all eight jobs;
Windows build 41326069674 (runtime 0e60da5) passed all three jobs. Independent ZIP,
x64 launcher, x86 native payload and bundled-source checks passed. Exact-package
Windows observations are recorded below; do not reuse older acceptance.
Firefighting and full native fire/ram calibration are not claimed fixed.

The first cloud candidate exposed an extra diagnostic dependency in the lethal
fire lifecycle fixture: inspecting an absent target descriptor entered the native
player fallback. Diagnostics now inspect only the target-owned descriptor and
record absence without entering BigWorld. The regression explicitly forbids that
fallback and the complete postmortem-fire tests pass. Historical route checks
required fetching this shallow checkout's real baseline commits; their expected
routes were not replaced by current output. The independent exact-resource audit
again passed 576 vehicles / 9,216 fitting records and all 36 special gun identities.

The full cloud suite also exposed six presentation/startup fixtures whose
synthetic fitting intentionally has no generated native crew. They now explicitly
donate an empty skill projection, just as they already donate empty crew and plain
factors. Production crew decoding remains mandatory for real generated fittings.
All six affected startup/countdown/teardown cases passed locally with the explicit
engine-free simulation owner. All 1,017 startup/battle-flow tests and final cloud
coverage of their full files passed. The wider local Bot run initially omitted
WOT_OFFLINE_DIAGNOSTICS: 538/550 passed, with 12 log assertions failing due to
missing detailed records. All 12 passed when rerun with diagnostics enabled;
the cloud full-file Bot suite also passed. No navigation expectation was weakened.

### Exact-package Windows acceptance (2026-11-02)

Runtime `0e60da5`, build identity `colorfulmeans-41326069674-1`, was independently
inspected and run from `D:/Games/wot-mod/9.22/PR119-0e60da5` using the diagnostic
entry. User data was isolated in `PR119-0e60da5-QA`; original launcher selections
were restored. The user handled the original EULA and assisted gameplay.

Mittengard round 1 ran with one visible leFH18B2 player and 29 elite Bots covering
IS-7, KV-2, AT 15, Tiger I, T29 and Centurion 7/1. Both visible and hidden clients
installed the six native fitting identities. Worker evidence contains 29 initial
ammunition records, 25 effective-factor states (16 with injured crew), and 31 old
Intuition decisions, including 10 successes across one/two-loader eligibility.
The battle ended by team elimination and the visible client applied one career
receipt before returning to the garage. Native crew decoding did not throw.

The launcher's report export produced
`wot-error-report-20261102-013519-cd8e6d47a1d6.zip` in the isolated QA reports folder.
Its ZIP integrity, coherent session logs and exception trails were checked:
no Python traceback/assertion/type error was found; exception trails contain
session headers only. The one rejected `simulation_progress` command follows the
last terminal projectile within the battle-end transition, immediately before
the logged result; no mid-battle rejection was observed.
Three native fire observations record decay factors 1.09245, 1.0940625 and
1.1057083333333333, `native_health_burn_per_second=0` and `skill_applied=false`.
This confirms diagnostic delivery and the missing native fire contract, not a
Firefighting repair. Static dependency scanning found no missing physical imports;
virtual API-set resolution remains outside that static check.

The user's moving KV-2 hit was traced to Bot 2, shot 6, projectile `1:b:2:6`:
HE penetrated and removed the player's remaining 260 HP at approximately 223 m.
Adjacent pose samples show about 6.10 m/s (22 km/h). The same KV-2 hit four of
nine shots overall; this isolated hit is not evidence of guaranteed accuracy.

Limits: this session proves real fitting/crew lifecycle, injured-factor donation,
Intuition decisions, combat/settlement and fire diagnostics for the exercised
lineup. It does not statistically prove all 49 device effects, every directive,
liner saving-throw probabilities or suspension impact reduction in native play;
those consumers have focused contract/rule tests. Full native fire and ram
calibration remain unresolved. Full cloud Tests at `7d27a8e`, run 41328312147,
passed; subsequent changes to this record do not change packaged runtime code.

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


## Economy v2 acceptance baseline (November 2, 2026)

The old own-tier Ace/mark XP curve and 2-credit/HP, zero-credit-assist checks
are invalid baselines and have been replaced. Keep task thresholds unchanged
while validating this new income model. Credits use the owner-selected 2015
community model as a whole; XP uses official categories with explicitly custom
missing numeric coefficients. See COMPATIBILITY_REVIEW.md for source conflicts,
375 measured vs 305 estimated vehicle coefficients, and the combat-model audit.

1. Diagnostic launcher -> Repair -> Earnings test: stationary targets. The
   scene reuses legal baseline fittings and real native targets, not a synthetic
   reward grant. Select Type 59; then test a normal vehicle for coefficient parity.
2. Finish a real battle. Capture both native detail columns, result-team base XP,
   first-win/carousel state, system-message rewards and actual wallet deltas.
3. Match REWARD BREAKDOWN to ECONOMY SETTLED by receipt ID. Compare model parts,
   measured/estimated vehicle coefficient, native account premium/reserve/save
   steps, and separate repair/ammunition/consumable costs. Capture/defence and
   assistance must be actual admitted events. Do not infer visibility at hit time
   from a final scoreboard.
4. Verify losing/drawing Battle Hero/Epic resistance once, native bonus rows,
   and no bonus for ordinary badges; a replayed receipt must pay nothing again.
5. Keep training zero and old pending receipts unchanged. Do not recalculate
   historical wallet balances or chase the owner's old task progress.

A native snapshot is evidence only for the vehicles/conditions it actually
exercises. Formula fixtures and cloud green alone do not prove live settlement.

### Final economy v2 package and Windows acceptance

Runtime: `90acd88c8db879d3d08b05216dd68ed73c8bc8a3`; these acceptance notes
are a later documentation-only change, not a different packaged runtime.

- [Tests 41429763001](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/41429763001): all eight jobs passed with the matching native simulation build and the new earnings regression gate.
- [Build 41429757820](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/41429757820): all three jobs passed. Artifact 13133604185 / `windows-574`, build identity `colorfulmeans-41429757820-1`, semantic version 1.1.1.
- Independent inspection: ZIP integrity and paths, x64 launcher/x86 extensions,
  236 source comparisons, 229 Python 2.7 code-object comparisons, and the full
  43-module frozen-launcher/package verification passed. Replay execution and
  the packaged Tk editor smoke passed. Exactly the normal EXE and diagnostic
  BAT remain exposed.
- Final ZIP: `C:/Users/USER/Downloads/PR119-90acd88c-Windows-x64.zip`;
  extracted package: `D:/Games/wot-mod/9.22/PR119-90acd88c`.
- Used separate `PR119-90acd88c-QA/Roaming` and `Local` directories. The
  existing user's assets were not recalculated or reset. The user authorized
  the EULA and personally drove the damage samples. English-to-Chinese
  switching and the new Repair-tab earnings entry were visibly checked.

| Native sample, Type 59 | Gross credits | Base XP | Awarded vehicle XP | Free XP | Currency services |
| --- | ---: | ---: | ---: | ---: | --- |
| Stationary round 1, no damage, first win | 16,380 | 180 | 396 | 20 | 12 bonds, no credit/gold cost |
| Stationary round 2, no damage, subsequent win | 16,380 | 180 | 198 | 10 | 12 bonds, no credit/gold cost |
| Stationary round 3, 50 damage, one kill, 35 defence points | 17,167 | 412 | 453 | 22 | 12 bonds, no credit/gold cost |
| Normal Mittengard, 3,480 damage, two kills, two initial spots, destroyed, team win | 71,505 | 1,711 | 1,882 | 94 | 7,410 repair credits, 50 consumable gold, 12 directive bonds |

The normal battle used the ordinary start button after closing the static
fixture. Its result was `team_eliminated`, not a synthetic reward grant.
Both the result's details and the native system-message entry were read.
Gross credits are independently reproducible from the admitted facts:
`(1300*8 + 10*3480 + 100*2) * 1.575 = 71505`.
Net battle credits were 64,095, matching wallet 100,049,927 -> 100,114,022.
The separate completed daily mission subsequently added 60,000 credits;
that mission money must not be reported as gross battle earnings.
XP parts were participation 100, damage 696, kills 200, criticals 55,
spots 40 and capped close-combat activity 50: subtotal 1,141, victory 1,711
after integer truncation. The native 10% vehicle bonus raised that to 1,882,
without multiplying the already vehicle-adjusted credits again. Account-premium
columns were display previews, not proof of an activated premium account.

#### Repeated consumables, stock and automatic purchase

Historical reference: [official 9.18 release notes](https://worldoftanks.com/en/content/docs/release_notes/918-updatenotes/).
The repair kit/medkit/extinguisher reusable change predates 9.22; using the same
consumable multiple times consumes one item, not one per activation. Never use
the modern console consumable policy as this PC client's baseline.

- Two player large-kit intents were recorded at 19:56:25.064 and 19:57:55.310
  (90.246 seconds apart), with different actual damaged-module sets.
- Persisted large-kit compact descriptor 1019: owned 581, mounted 581, spare 0
  before the battle. After use and automatic replenishment it was again 581.
  The native chosen currency was gold: one 50-gold resupply, not 100 gold.
  The actual transaction reduced gold from 1,000,250 to 1,000,200 before
  subsequent mission awards. The result detail row also showed -50 gold.
- Ammunition stock fell by 13 for AP descriptor 58 and 7 for HE descriptor 570,
  matching 20 actual shots. It was replenished from stock, so zero ammunition
  currency cost is correct and is not evidence of free ammunition.
- Worker logs contain 28 Bot effects across 19 Bots: regular small-kit/medkit
  one-use states, veteran reusable small kits/medkits and a manual extinguisher,
  and elite large-kit/medkit effects. Veteran Bot 2 used its small repair kit at
  simulation times 40.409 and 282.755 (242.346 seconds apart, cooldown 90).
  Bots have per-round consumable state, not player-account purchases. Trigger
  records do not by themselves prove every possible critical-state consumer;
  the shared native-effect and authority contract tests remain required.

Reports generated from the final launcher:
`wot-error-report-20261102-193001-0edc66371b81.zip` (first two rounds) and
`wot-error-report-20261102-201729-258b0e65c8fe.zip` (normal session, with
earlier launcher history). Both ZIPs passed integrity. The final report's
visible-client, hidden-worker and server logs contained no ERROR entries or
Python tracebacks; both native exception trails had session headers only.
All 35 physical imports were found; the static tool does not resolve API-set
contracts. Receipt `d5af17c3012d40fab4538f4f9268fabe:1:1` ties normal-battle
REWARD BREAKDOWN to ECONOMY SETTLED and the persisted garage transaction.

Unexercised native boundaries: other-spot/assistance payouts, player successful
capture, losing/drawing heroic resistance, an ordinary vehicle's coefficient,
active account premium/reserves, and paid ammunition after stock exhaustion.
Automated fixtures cover those model/transaction branches; they must not be
labelled observed Windows outcomes from this session. Static targets can end
the small-map fixture through capture; use normal battles for sustained combat
samples. Mission thresholds and bond award rules remain unchanged.
# Independent player control acceptance additions, November 3

The previous candidate's zero-output/friendly-hit run is a failure. Replace the
old isolated-Bot force-balance expectation with independent human control:

- Player remains a human actor. No Bot agent, fitting, allocation slot or Bot
  navigator state is created/changed by takeover. All feature masks preserve
  unclaimed manual input channels.
- Fire during takeover must not enter an unacknowledged stock shot wait. Test
  left/right clicks, repeated manual/auto toggles and subsequent manual shots
  through ammo decrease, accepted projectile and enemy damage, not sound alone.
- With a friendly hull between player and enemy, auto fire is held; after it
  clears, actual enemy damage is required. Static LOS alone is insufficient.
- Occluded contacts do not cause combat parking. Main and reserve points both
  enter 3D nearest-connected selection. Ground below a bridge cannot snap to
  the upper support layer. Record join status/goal/path and route index.
- Elite reaction/opening patience, actual player dispersion and reload apply.
  Preserve the manually chosen first round; afterward use actual carried
  stock/premium/HE rounds and the existing admitted-result switch policy.
  Player inventory/fitting never receives the elite Bot premium-only upgrade.
- Complete the native checkbox matrix and every mouse-panel action, including
  timed-drive expiry, Stop, panel-close Stop and starting the next round manual.

Include stopping while a burst subshot awaits acknowledgement: the admitted
round must settle once and only future subshots are cancelled.
Automated player tests cover 23 cases at this candidate; native replacement
acceptance remains pending and must be recorded separately.

