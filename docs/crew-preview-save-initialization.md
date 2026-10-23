# Crew delivery, effective preview and save initialization

The launcher recruit handoff now selects a complete passport group matching the
requested gender from the native nation configuration. Normal groups are tried
before premium passport groups. The pinned client keeps ordinary female names
in its premium passport pool; this flag does not refer to the trained vehicle.
All three group indices are passed explicitly to the native factory. Missing
or incomplete groups leave the request pending. Existing request receipts and
atomic garage delivery remain responsible for preventing duplicate recruits.

`tools/export_crew_passports.py CLIENT_ROOT OUTPUT.json` exports the pinned
resource groups. Run `tools/audit_native_crew_grants.py CLIENT_ROOT OUTPUT.json`
with Python 2.7 to execute the exact native factory and codec across all ten
nations, both genders, all primary seats of a representative vehicle per nation,
and 50/75/100 training. The reviewed run covered 228 presets. Python bytecode
execution with resource-backed groups is not a live game acceptance test.

The effective preview is a read-only window with setting, effective value and
source columns. It resolves every selected team/class/slot using the same rule
matching order as the runtime, groups identical values and origins, and keeps
slot exceptions visible. Only rules already added to the current document draft
are included; unsubmitted form fields are excluded. Opening or translating the
preview never saves or applies the document. Missing difficulty is reported as
inherited room difficulty, retaining the existing sampled rating distribution.
Explicit crew presets suppress the legacy crew-level display. Ammunition ratios
use colon-separated values; all zero means no ammunition. Fixed vehicle gun
information is read only when research is resolvable, never guessed from Regular.

The Saves tab has two rows of four equally sized buttons. Initialize save is the
last button in the second row. It refuses a running game and defaults its warning
to No. It resets only the selected save, preserving its id, name, mode and earnings
multiplier. Initial funds and progress revert to the existing new-save defaults.
Fully unlocked saves therefore use the current improved equipment, matching
directive and directive auto-resupply defaults; users can still change those.

Before replacement, owned live states, recovery generations and pending inboxes
are backed up to an ordinary ZIP under a unique `pre-initialize-*` directory.
Interrupted owned writes are moved aside too. A metadata write failure restores
the old files. Shared vehicle/tactics profiles and other saves are not reset.
An explicit metadata marker prevents the default save from importing legacy
state again, in both the client path resolver and the launcher ledger reader.
The existing Restore save action can restore the automatic backup.

Verification includes native factory/codec checks, recruit retry/receipt tests,
all-scope preview/source tests, language changes, reset ownership/rollback/
legacy migration tests, and actual frozen editor smoke receipts for the preview,
initialization/backup and two-by-four button layout. Worker behavior and difficulty
sampling are unchanged in this revision. No user save was initialized during
verification; all reset tests use temporary directories.
