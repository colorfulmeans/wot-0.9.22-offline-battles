# Environmental attribution and death presentation

Report `20261014-224823` records the local fuel tank changing from destroyed
at zero HP to critical at 70 HP when fire stops at 22:47:39.099. Its event has
`cause=fire`, so the presentation formerly classified recovery as a fresh
critical hit. Improved device states now use repair notifications regardless
of the tick that produced recovery. The critical state/HP laws are unchanged.

The exact #1513 postmortem reader uses a private dictionary of translated
`(text, colors)` entries. After its normal population, replace the ammunition
fire text with `弹药架因燃烧而爆炸` and provide a separate world-collision
ammunition code with `弹药架因坠落而损毁`. Preserve normal shot templates,
colors, killer formatting and health/death ownership. Capture an explicit
ammunition-event cause before presentation and retain it when a terminal
callback arrives with the default shot index. Log the final selected code.
This report does not contain an ammunition death proving the new text on
Windows; the next game acceptance remains necessary.

Record environmental push lineage independently from direct ram HP. Use
accepted human momentum checkpoints, immutable human/Bot contact receipts,
and frozen worker contact bodies. A contact normal and incoming horizontal
velocities select a dominant approaching actor; tangential/equal head-on
approaches do not nominate a pusher. Reject vertically disjoint bodies and
ignore stationary co-moving pairs. This does not change motion or ram damage.

Contacts expire after three seconds unless a confirmed airborne/drowning
episode latches the source, with a thirty-second terminal bound. Surfacing,
completed landing, round changes and authority replacement retire lineage.
Cumulative Bot landing-HP totals keep nonfatal falls distinct from fire ticks
and make repeated publications incapable of crediting damage twice. Sequence
receipts prevent an old contact publication refreshing its attribution window.
Attribute fall/drowning damage and kills through the existing statistics
ledger and native HUD events. Friendly shoves causing actual environmental
damage mark the pusher blue and count team damage; they earn no enemy damage.
Enemy kills add one frag, allied kills subtract one. Preserve environmental
attack/death reasons, rather than displaying the event as a shot or ram.

Validation covers numeric push selection, contact expiry/replay, friendly and
enemy falls, the drowning countdown, fuel recovery callbacks, native friendly
damage-log delivery, central ammunition text/code mapping and a real worker
fall publication through the server with duplicate-publication accounting.
Engine-free tests prove source and adapter contracts, not Windows visuals or
native gameplay timing. The pre-existing bootstrap fake fails to import
`customization_rules` on both the previous `ac62d3b6` tree and this tree.

Shell tooltips retain the current 2.4-style presentation. Impact trial rates,
navigation rules and physical movement owners are unchanged.
