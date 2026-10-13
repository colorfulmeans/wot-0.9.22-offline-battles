# Hold cleanup and rear-target movement arbitration

Windows244 report `20261014-025123-9f12bd73cead` records WZ-132A parked in
low_health_retreat with movement_intent false, while local retry age grows
from 16881 to 36732 ms. The retained/direct shortcut entry bypasses the
next_target cleanup. Retained-leg holds or changed intents and direct holds
or arrival now clear the same local_retry_progress record.

FV217 stays within a small area from about 02:45:47 to 02:46:13. Its server
withdrawal destination remains near (-14.269, 0, 451.48), but rear-enemy
selection changes between IDs 23 and 25 and rear laying converts withdrawal
to an in-place engagement. Per-enemy episode renewal can repeatedly interrupt
movement even though each episode has an eight-second limit.

One limited-traverse laying attempt during movement now opens an eight-second
lease at the realised vehicle origin. Changing enemy or route steering does
not renew it. Exhaustion gives movement priority for at least eight seconds
(or the installed reload duration, whichever is greater). Real travel beyond
two hull half lengths plus 1.5 m, arrival, parking or intentional hold modes
retire it; cooldown expiry permits another attempt. The first E4/fixed-gun
rear engagement remains admitted, and exact gun alignment still owns firing.
Expose lease and arbitration state in BOT MOTION gun diagnostics.

1342 checks across 27 navigation, driver, withdrawal, rear-limited aiming and
battle suites pass. The recorded coordinates and target switching locate the
problem; controlled fixtures are not native map playback. Windows acceptance
of actual departure and target tracking remains pending.
