# Chieftain pending-route local fallback cycle

Report `20261009-012658-f480490e0f75` is test143 on winter Himmelsdorf.
Team2 Bot19, GB88 T95 Chieftain turret, holds near (254.281, 296.103)
from 01:25:04 through 01:26:05 with zero drive/turn, pending navigation,
no parking phase/target, grounded support and no contact. A completed
41-point route later exists while a private connection remains pending.

The recorded fallback origin (254.572, 294.933) occupies eroded baked cell
(138,148); the stationary hull occupies supported cell (138,149). The
nearest supported node is the previously approached (254,298). Reproduction
with these poses, the exact bake, an explicit level native support plane,
and the existing temporary-stalled visited-history gate returns the hull
position repeatedly at 10, 20 and 80 seconds. The log does not serialize
the visited-history gate itself; this is an implementation reproduction,
not a native replay proving every hidden state of the reported episode.

Once the hull is back on supported graph terrain, a consumed eroded anchor
from the same intent no longer owns the next local origin. In that specific
reentry episode, stalled visited cells are excluded while selecting a short
fallback, before spending native proof on the one nearest candidate or
ranking ordinary fan candidates. Ordinary supported corners keep their
fixed origins. Normal movement/backtracking is not excluded by this policy.
Real walls and unknown native support still fail closed. Completed global
paths and search-prefix retracing retain their previous contracts.

The local diagnostic now counts the existing nearest-node attempt and records
successful native exits, as well as fan candidates. Query ceilings, live
ground/shoulder/full-width proof, slope/water/edge vetoes, search budgets,
arrival thresholds, motion laws and authored tactics are unchanged. No bake
height is filled and no full suspension solver is enabled.

Eight added cases cover the recorded loop and real drive input, supported
reentry/eroded origin, nearest-candidate selection within its proof cap,
observed wall refusal, unknown support, ordinary visited travel, supported
fixed corners and changed intent. The existing Panther II/M36/SU-122-44
finite-wall mobility scenario is retained and passes. The broader navigation
suite retains its known finite Pilsen doorway failure; it is not suppressed.
Native Chieftain progress around actual winter-map scenery remains the
test144 playtest boundary.
