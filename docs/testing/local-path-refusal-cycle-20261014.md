# Same-request local/path refusal cycle

Windows243 report `20261014-021603-4b16de64f1c9` records IS-7 bot 3 on
101_dday around (-231.5, 29.65, -25.32). The strategic route goal remains
(-239.244, 0, 47.934), but the issued target alternates between the cached
path source (-230, 29.64, -26) and short fallback tips around (-232.6, 29.69,
-22.8). Fallback termination is logged as unsafe. The macro monitor changes
between path and temporary ownership and repeatedly renews its deadline.
Object 705 has the same near-node/route-goal alternation near (-238,31.7,-8.5).

Keep a separate retry receipt admitted only by a completed unsafe short-leg
proof. It belongs to the exact navigation request, survives cached-path
handoffs and private replans, and counts actual entry into previously unseen
terrain cells as progress, including a necessary retreat. A commanded hold,
changed request or arrival retires it. Two refusals plus twelve seconds
without new terrain request a private follower replan from the realised hull.
New refusals and a twelve-second retry interval are required before another
request. No shared terrain penalty or synthetic collision is introduced.

Proof budget deferral, including a deferred flag without a revision change,
keeps the issued short leg and pauses motion; it is not refusal evidence.
Search receipts expose retry age, failure count and replan count. Recorded
coordinates and controlled proof replies exercise these contracts; only a
new Windows playtest can establish actual escape from these map pockets.
