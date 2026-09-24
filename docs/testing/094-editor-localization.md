# v0.9.4 Bot tactics editor localization follow-up

Baseline: `c584fa591ccff2429c3850d92bafb1d4d6afbd1a` (the delivered PR #38 package).

## Request and implementation

The map selector previously had only twelve mixed-language names, including two
keys not in the active 41-map catalogue, and fell back to file IDs for the rest.
Built-in route names and enum controls rendered canonical wire values verbatim.
The editor only received the language once at creation.

The new presentation-only catalogue covers all 41 exact map keys and all 96
built-in route IDs in their navigation resources. Chinese and English are
separate display columns, not a combined `Chinese / English` value. Mainland
client-era full map names are used. Himmelsdorf uses the user's explicit
spelling `锡莫尔斯多夫`; its winter variant is `锡莫尔斯多夫（冬季）`.
The historical map `38_mannerheim_line` displays Arctic Region in English,
not a modern name inferred from the resource ID. `44_north_america` is Live
Oaks and `45_north_america` is Highway; the actual Paris key ends in `_ctf`.

Map-naming reference: the publisher's mainland map list at
https://wot.360.cn/features/play.html . Old Winterberg/Mittengard/Ghost Town
Chinese labels are also present in the publisher's 9.5 announcement as
reprinted at https://games.sina.com.cn/o/n/2014-12-22/1134843029.shtml .
These are UI labels, not a claim to have recovered the complete #1513 MO file.
Route captions are translations of this project's tactical authoring labels,
not official Wargaming tactical-place designations.

Enum dropdowns have a display variable separate from the canonical variable.
Skills, vehicle classes, team/slot/all/inherit, crew percentages, route policies,
class checkboxes, rule summaries, effective-value previews, validation result
captions and duplicate-item labels are localized. Canonical IDs remain in JSON,
route selection keys, logs and the network contract. No schema migration is
required. User-authored names are never automatically translated or renamed.

The main window's auto/en/zh setting is the only language authority. Existing
open editors are updated in place and newly opened editors get the same
resolved language. Dead windows are removed from the registration list.
A switch never saves, applies, reloads, or rebuilds the draft controls: current
map and team, selection, unsaved/invalid numeric entry, custom text, world
coordinates, view transform, undo/redo history, profile digest and active file
bytes remain unchanged. All static headings/help text and cached background
source notices switch with the dropdowns. Auto uses the same resolver as the
main window, not the game client's language.

## Scope and validation

Only launcher display, its storage label facade, main-window language wiring,
packaged-editor smoke and tests change. All server/client runtime files and
all 41 navigation artifacts remain byte-identical to the baseline. No Bot
behavior, route coordinates, artillery mechanics, collision, economy, crew,
penetration, visibility or radio changes are made.

Thirteen new tests cover all-map/all-route catalogue parity, canonical enum
round trips, multiple open windows responding to the real main language event,
Auto resolution, no-save/no-dirty changes, custom labels and in-progress forms.
Nine original actual-Tk tests and the original launcher/core/runtime suites are
retained. The frozen Windows EXE smoke now explicitly switches en -> zh -> en,
checks display names and proves that active profile bytes remain unchanged.
Build gates also compile/compare the actual Python 2.7 payload, verify the
bundled runtime, simulate installation and start the packaged server.

UI/contract tests do not assert native-gameplay acceptance. This is a test build,
not a main merge, tag or formal release. Install the complete package to avoid
mixing launcher dependencies; no account or tactics profile reset is needed.
