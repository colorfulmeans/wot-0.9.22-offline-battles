"""Version 2 offline battle earnings: event facts, not mastery percentiles.

Credits use the complete 2015 community model selected by the user: 700/tier
participation (1300/tier for victory), 10/HP own/blind damage, 7.5/HP other-spot
damage, 5/HP assistance, 100 per first spot (200 for SPGs), 500 per successful
capturer and a 600/tier resistance supplement. There is no target-tier credit
bonus in this model. Sources: ltrat 2012-03-07 and HellQwer 2015-09-24 workbook.
XP separately follows WG support article 18960 and the 0.8.8 manual's categories;
missing numeric XP coefficients are explicitly offline reconstruction.
Credits are multiplied by the measured/labelled estimated vehicle coefficient
on the server, exactly once; premium account and reserves remain client-owned.

XP coefficients remain explicit offline reconstruction: 0.2 per own-spot HP,
0.1 per assisted HP, 100 per kill, 5 per critical transition, 20 per first
spot (40 for artillery), 2 per capture/defence point, 20 survival and up to
50 active-combat XP (5 per positive-damage event within 200 m). Target-tier
scaling is 10% per difference, also reconstruction for XP. None of these XP
magnitudes are claimed to be leaked WG server coefficients. The old ratio of
modern Ace/mark percentiles and victim-HP kill proxy are deliberately removed.
"""

ECONOMY_VERSION = 2
OFFLINE_PARTICIPATION_CREDITS_PER_TIER = 700
OFFLINE_DAMAGE_CREDITS_PER_POINT = 10
OFFLINE_ASSIST_CREDITS_PER_POINT = 5
OFFLINE_SPOTTING_CREDITS = 100
OFFLINE_SPG_SPOTTING_MULTIPLIER = 2
OFFLINE_CAPTURE_CREDITS = 500
OFFLINE_PARTICIPATION_XP = 100
COMMUNITY_WIN_PARTICIPATION_PER_TIER = 1300
OFFLINE_WIN_XP_FACTOR_100 = 150
OFFLINE_FREE_XP_PERCENT = 5


def nonnegative(value, default=0):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return default


def tier_weight(actor_tier, target_tier):
    """Tenths; higher-tier targets pay more, with no own-tier percentile curve."""
    own = max(1, min(10, nonnegative(actor_tier, 1)))
    victim = max(1, min(10, nonnegative(target_tier, own)))
    return 10 + victim - own


def compute_offline_rewards(statistics, won, participated=True,
                            vehicle_tier=1, spotted_spgs=0,
                            captured=False, reward_facts=None,
                            courageous=False, vehicle_coefficient=10000,
                            breakdown=None, vehicle_xp_factor=100):
    """Settle authoritative facts. Units are 1/100 tier-adjusted hull HP.

    Runtime callers always supply reward_facts, frozen on admitted events.
    Without them this pure calculator treats synthetic aggregate fixtures as
    equal-tier own-spot damage and uses the largest assist category, never the
    sum of overlapping track/radio/stun values. It cannot reconstruct old
    live spotting evidence from a final scoreboard.
    """
    statistics = statistics if isinstance(statistics, dict) else {}
    value = lambda name: nonnegative(statistics.get(name))
    tier = max(1, min(10, nonnegative(vehicle_tier, 1)))
    spots = value('spotted')
    spgs = min(spots, nonnegative(spotted_spgs))
    if reward_facts is None:
        facts = dict(damage_units=value('damage_dealt') * 100,
                     assist_units=max(value('damage_assisted_' + category)
                                      for category in ('track', 'radio', 'stun')) * 100,
                     kill_units=value('kills') * 100,
                     critical_units=value('critical_hits') * 100,
                     credit_damage_units=value('damage_dealt') * 100,
                     credit_assist_damage=max(value('damage_assisted_' + category)
                         for category in ('track', 'radio', 'stun')),
                     active_events=0, survived=False)
    else:
        facts = reward_facts
    damage_units = nonnegative(facts.get('damage_units'))
    assist_units = nonnegative(facts.get('assist_units'))
    xp_parts = dict(
        participation=OFFLINE_PARTICIPATION_XP if participated else 0,
        damage=damage_units // 500,
        assistance=assist_units // 1000,
        kills=nonnegative(facts.get('kill_units')),
        criticals=nonnegative(facts.get('critical_units')) // 20,
        spotting=(spots + spgs) * 20,
        capture=value('capture_points') * 2,
        defence=value('dropped_capture_points') * 2,
        survival=20 if facts.get('survived') else 0,
        active_combat=min(10, nonnegative(facts.get('active_events'))) * 5)
    action_xp = sum(xp_parts.values())
    win_xp = action_xp * 150 // 100 if won else action_xp
    # Reverse the documented enemy-action categories for eligible team damage;
    # this penalty coefficient remains an explicit offline reconstruction.
    penalty_terms = ((value('team_damage_penalized') + 4) // 5 +
                     value('_reward_team_kills_penalized') * 100)
    penalty = min(win_xp, penalty_terms * (150 if won else 100) // 100)
    normal_xp = max(0, win_xp - penalty)
    courageous = bool(courageous and not won)
    achievement_xp = (normal_xp * 150 // 100 - normal_xp) if courageous else 0
    # Apply before every base-XP consumer: scoreboard, mission counters and
    # settlement. Account, daily and ordinary premium bonuses remain separate.
    base_factor = max(1, int(vehicle_xp_factor))
    normal_xp = normal_xp * base_factor // 100
    achievement_xp = achievement_xp * base_factor // 100
    penalty = penalty * base_factor // 100
    xp = normal_xp + achievement_xp
    participation_credits = OFFLINE_PARTICIPATION_CREDITS_PER_TIER * tier if participated else 0
    credits_parts = dict(
        participation=(COMMUNITY_WIN_PARTICIPATION_PER_TIER * tier
                       if won and participated else participation_credits),
        damage=nonnegative(facts.get('credit_damage_units')) * OFFLINE_DAMAGE_CREDITS_PER_POINT // 100,
        assistance=nonnegative(facts.get('credit_assist_damage')) * OFFLINE_ASSIST_CREDITS_PER_POINT,
        spotting=(spots + spgs) * OFFLINE_SPOTTING_CREDITS,
        capture=OFFLINE_CAPTURE_CREDITS if captured else 0)
    raw_credits = sum(credits_parts.values())
    # Resistance restores only the victory participation payment; kills and
    # medals are not an extra damage/credit farm and medals never stack it.
    raw_achievement_credits = (600 * tier if participated else 0) if courageous else 0
    coefficient = nonnegative(vehicle_coefficient, 10000)
    credits = (raw_credits + raw_achievement_credits) * coefficient // 10000
    normal_credits = raw_credits * coefficient // 10000
    free_xp = xp * 5 // 100
    result = dict(credits=credits, xp=xp, free_xp=free_xp, repair_cost=0,
                  ammo_cost=0, economy_version=ECONOMY_VERSION,
                  achievement_credits=credits - normal_credits,
                  achievement_xp=achievement_xp,
                  achievement_free_xp=free_xp - normal_xp * 5 // 100)
    if penalty:
        result['xp_penalty'] = penalty
    if breakdown is not None:
        breakdown.update(version=ECONOMY_VERSION, credit_model='community_2015',
                         xp_model='official_categories_offline_coefficients', xp_parts=xp_parts,
                         credits_parts=credits_parts, facts=dict(facts),
                         vehicle_coefficient=coefficient, vehicle_xp_factor=base_factor, courageous=courageous,
                         won=bool(won), rewards=dict(result))
    return result
