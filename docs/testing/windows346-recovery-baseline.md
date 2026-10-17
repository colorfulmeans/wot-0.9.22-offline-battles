# Windows346 recovery baseline before further navigation changes

This integration preserves the current working implementation before attempting
the M48A5 hillside and FV4005 bridge-underpass fixes. It is a recovery reference,
not a claim that navigation or physics is free of defects.

## Immutable source and package references

- Runtime source commit: `9294ad738e5c208e41b3073f773e5b1df8cdbf49`.
- Preserved branch: `baseline/windows346-before-navigation-fixes`.
- Package version: `0.10.1`, Windows346, build `colorfulmeans-39031405112-1`.
- Package filename: `wot-0.10.1-worker-query-diagnostics-Windows346-x64.zip`.
- Package size: `89720951` bytes.
- Package SHA-256: `2f56d5748684c12c2623ef1a4d8d1d0e96c252876c1772dbcbead30c244ca2a1`.
- Successful package build: https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/39031405112

The consolidated PR includes the existing history from PRs #61, #63 and #64
against main. At creation, main was
`144619f6eb2925f8da4b13637bf65b8550fc898f` and the runtime tip contained 77
commits beyond it. The baseline integration adds this document only; all other
tracked files remain byte-for-byte identical to the runtime source commit.
Use that full source commit for an exact restoration of code, tests and assets;
the document commit is not the source of the already-built Windows346 package.

## Preserved behavior and boundaries

- The normal launcher uses normal roster, spawn, navigation and firing behavior.
  Roof-crush and shot-triggered drop tests retain their independent opt-in entries.
- Retain current landing, roof contact, reciprocal live-vehicle pressure and wreck
  pressure behavior, player wreck simulation, destructible catalogs and native HUD
  callbacks.
- Retain the support contract: enable detailed support when at least one of five
  support points is invalid; disable it when all five are valid.
- Retain current route retries, route switching, avoidance and local candidate
  ordering: admissible candidates, then smaller `D + C`, then smaller `abs(theta)`.
  Slope observations do not participate in decisions. No new slope preference is
  approved by this baseline.
- Retain worker query-preparation reuse and navigation, landing and contact
  diagnostics from Windows346. No new height-layer gate is introduced here.

## Validation already associated with the source commit

The Windows346 package was inspected against the source, including 188 client
modules, 192 server sources, 42 navigation files, 84 destructible catalogs,
native payload stamps and the independent fixture launchers. Focused support,
contact, runtime and query-reuse checks were run during the preceding work.
These are package and local-contract checks, not proof of native gameplay.

The exact-source test workflow is:
https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/39031407242

Its completed status is mixed: `windows-server`, `native-geometry` and
`windows-editor-tests` succeeded; `bot-behavior-regressions` and `test` failed;
the launcher and exception-trail jobs were skipped. Do not describe this
baseline as full-CI green. This consolidation does not change tests or suppress
failures. Job logs remain the authority for their individual failures.

## Known issues retained for subsequent investigation

Both reports below identify Windows346:

- `wot-error-report-20261017-202608-acf4b8e9f349.zip`: 12 Bots received default
  routes and 17 received `full_or_unusable_routes_auto`. Type59 Bots 25 and 27
  climbed hillside terrain and later left it. Existing local ranking can favor
  a steeper candidate for a smaller `D + C`; this does not establish every
  initial entry cause.
- `wot-error-report-20261017-203418-18c2b73b05d3.zip`: all 29 Bots received
  default routes. M48A5 Bot 6 entered hillside terrain and subsequently stalled
  with rotation rejections and `planning_ground_missing`. Raw surface traces
  also show steep terrain in selected directions. The initial path admission,
  later candidate ranking and executable collision checks require separate
  investigation.
- In the second report FV4005 Bot 24, at approximately
  `(-10.801, -14.253, 110.924)`, accepted a local target around
  `(-8.202, 0.974, 112.650)`. A roughly 3.1-metre horizontal connection crossed
  about 15.23 metres vertically. Current baked XZ-cell lookup can describe the
  bridge deck while the physical vehicle occupies the lower surface. Actual
  support-layer connectivity remains unresolved.
- Each report recorded one Bot detailed-support enable and one disable, with
  valid-point counts 4 and 5 respectively. Those observations do not prove
  support behavior in unexercised scenes.

Further navigation fixes must be reviewed separately from this baseline.
Keep the complete `C` term and intentional retry behavior; distinguish physical
support height from authored route anchors whose Y may be a placeholder.
Validate any future layer or slope change against normal slopes, bridge access
from below via a real ramp, and both forward and reverse movement.
