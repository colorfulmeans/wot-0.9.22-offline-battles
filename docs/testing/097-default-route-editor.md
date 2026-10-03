# Editable default routes and Airfield restoration

The Airfield lane rewrite in `0576e4dc` moved previously correct nodes and
introduced unwanted ridge crossings. Restore both teams' route objects exactly
from `31d8c001`; do not interpret the user's red drawing as another replacement
road design. Remove the broad Airfield corridor generator. Retain the reviewed
ground links, route-admission performance fix and destroyed-skin ownership fix.

The editor now edits built-in geometry directly, including moving, inserting
and deleting nodes. Each route still fits the existing 1..16-point protocol.
Per-map, per-team overrides remain separate from custom route allocation rules;
route IDs, capacities, risks and class/role affinities are retained. Original
graph resources and editor caches remain immutable. Saving and applying affects
the next round. Reset route and undo/redo restore earlier geometry.

The worker validates each override against the existing bounded navigation
graph before creating its director. Unusable or disconnected edits independently
fall back to their original routes with diagnostics. Assigned routes reach the
ordinary manifest, so the host's route catalog and subsequent lane switching
use the same coordinates. No terrain, collision or native firing veto is waived.

## Verification

- All 41 map registries match the shipped default route IDs and admit their
  original geometry through the editing contract.
- Real Windows Tk events cover default-node drag, insertion, deletion,
  undo/redo, persistence, apply, reopen and route reset without cache mutation.
- The launcher suite passes 906 cases, with 14 platform/optional skips.
- The dedicated Bot CI commands pass 714 cases, with one optional skip.
- A broader historical Bot run executes 692 cases: 59 failures, 18 errors,
  one skip. The exact parent snapshot `0576e4dc` executes the same 686 older
  cases with identical 59 failures and 18 errors; all 77 failure identities
  match and no new failure is introduced. Many assertions still describe
  suspension and crew effects from before the requested Bot rollback.
- Package/build verification and native-game acceptance remain separate.
  Tk and plain-data checks do not prove driving through the edited roads in
  the exact Chinese HD #1513 Windows client.
