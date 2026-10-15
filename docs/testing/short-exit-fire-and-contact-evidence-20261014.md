# Short exit proof, fire presentation and contact evidence

Report 20261014-155900 confirms coefficient 25, landing module/crew damage,
repair-kit recovery and a later fire detonation of the 28.404 HP ammo rack.
Retain the calibrated impact coefficient and existing body/fire laws.

## Recovery

Type 59 Bot 25 repeatedly pivots without translation for at least 58 seconds;
Bot 30 has another prolonged route stall. Old candidate/long-direction yaw
penalties can suppress a currently safe shorter sweep. Recheck current short
terrain/vehicle proofs independently of candidate penalties. Separate actual
caller-observed movement failures from candidate preferences, retaining their
finite veto and preventing retry of a physically rejected short exit.
Existing native realised-pose, terrain and friendly-hull checks are unchanged.
Expose each short probe distance/sign, clear result, vehicle blocker and real
failure receipt in BOT MOTION. The recorded Windows stalls lack those proof
receipts; actual map departure remains a supported-client acceptance question.

## Fire

Player fire commits store durable state without one-shot events. Previously
publication copied only that state and dropped the tick's fire events, so the
client derived default shot causes. Copy validated tick events into the ordered
fire event while leaving durable state empty of replayable events. Preserve
health/death ownership and revisions. The regression exercises the real fire
tick and confirms publication cause plus durable-state event retirement.

## Evidence

Two contact records exceed the engine 8 KiB stdout boundary. Reuse the bounded
JSON writer with process/record/part identity. Extend read_native_evidence.py
with ENV MODULE CONTACT/DAMAGE labels; large escaped records reconstruct
exactly and all emitted lines stay below the engine boundary.

Validation: 1,304 tests across 12 relevant suites pass, including real movement
failure expiry/retirement, proved short exits, native rotation safety, strict
fire alignment, combat publication and fragmented evidence. All 181 client
source files compile under CPython 2.7. No native ABI changes are shipped.
