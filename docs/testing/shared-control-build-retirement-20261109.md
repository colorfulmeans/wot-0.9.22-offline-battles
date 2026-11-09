# Shared-control build-entry cleanup — 2026-11-09

This cleanup follows the shared `vehicle_control` migration. It removes the
repository's executable paths for restoring pre-migration Bot implementations
or shipping pinned September runtime/map payloads. It does not rewrite Git
history, remove published releases, or modify user saves/backups.

## Removed paths

- 18 one-off tools: `bot077_build.py`, `full_bot080_build.py`,
  `apply_bot080_radio_fix.py`, `bot_editor_build.py`,
  `bot_editor_localization_build.py`, `exchange_crew_test_build.py`,
  `release_v094.py`, `spg_tracking_build.py`, `repair_094_build.py`,
  `ram_contact_build.py`, `apply_ram_contact_repair.py`, `test_094_repairs.py`,
  `verify_immutable_build.py`, `verify_v080_bot_build.py`,
  `test_v080_bot_behavior.py`, `test_v080_runtime_boundaries.py`,
  `verify_airfield_test_build.py`, and `test_airfield_review_gate.py`.
- 15 dedicated historical workflows: the Bot077/080 restore/compare builds,
  the September Airfield/no-native-review builds, the pinned 0.9.4
  mechanics/SPG/ramming/editor/localization/exchange builds, their editor-patch
  transport, and the Bot077-based 0.9.4 publication workflow. Exact filenames
  are asserted absent in `tests/test_retired_build_entrypoints.py`.
- 42 encoded source-patch fragments belonging only to those workflows:
  `bot_editor.patch*.b64`, `repair_094.patch*.b64`,
  `spg_tracking.patch*.b64`, `editor_i18n.patch*.b64`, and
  `exchange_crew_test.patch.b64`.

The Bot077/080 `integrate()` commands previously copied historical `ai/`,
`bot_runtime.py`, `bot_gunnery.py`, navigation and catalog trees into the
checkout, and deleted newer files absent from the historical tree. Their
workflows could commit and push the result. The old localization build also
copied a pinned September client ZIP over the newly staged output. These are
physical deletions, not redirects, flags, or alternative legacy imports.

## Retained boundaries

The standard `build-launcher.yml`, `tests.yml`, `build_wotmod.py`,
`build_for_client.sh`, server/launcher builders, current native/mesh builders,
release-bytecode/package verifiers, and the October owner-reviewed Default
remain. No current runtime, physical collision rule, vehicle fitting, crew,
equipment, or authored route data is changed by this build-tool cleanup.

Historical prose and proof JSON remain audit records, not restore entrypoints.
The current radio/roster source-or-bytecode contracts named
`test_bot080_radio_contract.py` and `test_bot080_startup_contract.py` are
retained: their names are historical, but they exercise current production
code and contain no old-source reconstruction. The read-only current
static-navigation contracts in `test_immutable_navigation.py` also remain.
Current gameplay tests are not removed along with the old selective runners.

## Verification and package handoff

`tests/test_retired_build_entrypoints.py` verifies all deleted entrypoints and
patch payloads are absent, remaining tools/workflows have no calls to them,
and the standard current-source package gates remain available. Run the full
current test suite through `tools/run_test_suite.py`; do not substitute pinned
historical test lists for current discovery.

The supported full Windows package entry is `build-launcher.yml` on the exact
reviewed source ref. It builds the Windows server, rebuilds the shipping x86
native module, compiles the client with CPython 2.7, compares every packaged
module with current source, then builds and executes the Windows launcher and
its embedded package checks. A passing host-only test run is not native game
acceptance. Deliver only the artifact from that same verified ref/run, followed
by the user's real-client gameplay test.
