"""Published 0.8.11 random-battle Personal Rating, independent of server averages.

Formula image: https://usercontent.one/wp/hokx.com/wp-content/uploads/2019/12/WTR-Personal-Rating.png
All offline battles are post-0.8.8. Use original battle XP, never banked rewards.
"""
from __future__ import division
import math


def personal_rating(progress):
    totals = dict((key, 0) for key in (
        "battles", "wins", "survivedBattles", "damage", "originalXP",
        "damageAssistedRadio", "damageAssistedTrack"))
    for row in (progress.get("vehicles") or {}).values():
        for key in totals:
            totals[key] += max(0, int(row.get(key, 0) or 0))
    battles = totals["battles"]
    if not battles:
        return 0
    win = min(battles, totals["wins"]) / battles
    survived = min(battles, totals["survivedBattles"]) / battles
    score = (3500.0 / (1.0 + math.exp(16.0 - 31.0 * win)) +
             1400.0 / (1.0 + math.exp(8.0 - 27.0 * survived)) +
             3700.0 * math.asinh(0.0006 * totals["damage"] / battles) +
             math.tanh(0.002 * battles) * (
                 3900.0 * math.asinh(0.0015 * totals["originalXP"] / battles) +
                 1.4 * totals["damageAssistedRadio"] / battles +
                 1.1 * totals["damageAssistedTrack"] / battles))
    value = 540.0 * battles ** 0.37 * math.tanh(
        0.00163 * battles ** -0.37 * score)
    return max(0, int(value))
