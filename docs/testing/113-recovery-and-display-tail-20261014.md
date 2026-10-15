# Native rotation refusal recovery and display latency tail

The Windows242 report `20261014-012742-5bf8214266e2` records a Ch22_113
in the same roughly three metre pocket from 01:21:00 to 01:21:27, with
recovery counts 7 through 15 and a realised `native_world` rotation refusal.
Ordinary recovery renews the macro objective lease for navigation backout;
removing that renewal breaks the finite dead-end motion acceptance cases.

The new pocket lease is admitted only by a realised native rotation refusal.
Starting more recoveries does not renew this separate eight second clock.
After two completed recoveries it prefers the existing proved short straight
exit over another pivot when the full rear escape does not fit. Native swept
hull checks remain authoritative. Travel beyond two hull half lengths plus
the arrival tolerance, a changed macro goal, or an intentional hold retires it.
BOT MOTION now includes the pocket origin and admission time.

Projectile `1:b:7:4` bounced on Object 260 with zero HP loss, then lost 397 HP
at a second contact after about 2 cm of projectile travel. The selected native
material identities differ (632482960 and 632482864); the world normals also
differ. The first pose was (96.4491, 1.7500, -0.0157), and the second was
(96.3713, 1.7500, 0.0023). There is one HP debit, not two. This evidence does
not justify rejecting all same-tank recontacts. Existing native surface,
pose, raw query, selected-contact and settlement evidence is retained.

Display recovery keeps the normal 60 ms floor and normal jitter decay.
Only a producer-stall tail above 120 ms decays faster: the packet target sheds
60 ms/s rather than 50 ms/s; render catch-up can follow confirmed history at
up to 1.10x. It never moves beyond the newest confirmed sample or rewinds the
cursor. Muzzle and hit ordering still waits for the matching presented pose.
The synthetic recovery comparison requires over 15 ms less retained delay at
three seconds, alongside monotonic and confirmed-history assertions. This is
not a claim that the measured 213 ms in-game BOT delay has been eliminated.
