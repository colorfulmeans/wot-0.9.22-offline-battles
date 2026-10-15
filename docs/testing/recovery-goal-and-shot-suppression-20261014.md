# Recovery task identity and suppressed shot receipts (130410)

Windows246 report 130410 shows Pershing bot21 changing nearby targets while
remaining in a roughly 3 m pocket for 22 seconds. LocalDriver used the current
proved steering target as the identity of its native-rotation-refusal lease.
A target change of more than 2 m therefore retired the lease although the
strategic route was unchanged. The driver now accepts recovery_goal separately
from progress_target; BotAdapter passes the original movement order. Actual
travel beyond the hull-length boundary, changed orders and commanded holds
still retire the lease. Translation uses the existing complete collision and
neighbour probes; no unproved pivot or terrain relaxation is introduced.

Bot11 shot2 was published near its canonical fatal hit, with no echo/display
receipt. This is not enough evidence to resurrect the shell. Server admission
keeps its existing liveness and clock gates, but now records BOT SHOT SUPPRESSED
only after a complete publication transaction commits. The receipt separates
raw worker health/liveness from canonical health/liveness, includes the fire
sequence range and source/receipt clocks, and identifies death, source-clock
rebase or burst-inventory rebase. A publication is not accepted projectile
launch evidence. In-flight already-admitted projectiles keep their ledger.

New tests reproduce retirement under the old local identity, prove retained
lease and checked short translation under the new identity, check real travel
and order cancellation, exercise the actual adapter argument, and drive a real
encoded publication overtaken by canonical death through server admission.
Native-map gameplay acceptance remains a Windows test. Fire rules, profiles,
authored routes, slope policy and aiming constraints are unchanged.

Local verification: 522 tests across 30 navigation, driver, route, server
projectile/combat-lineage, burst, rear-aim and snapshot suites pass. This
includes the six finite dead-end vehicle/FPS subcases. CPython 2.7.18 compiles
all 180 client sources. Windows packaging and in-client acceptance are pending.
