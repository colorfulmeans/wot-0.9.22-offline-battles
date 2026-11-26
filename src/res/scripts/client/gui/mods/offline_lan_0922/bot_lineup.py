# -*- coding: utf-8 -*-
"""Bot lineup selection: tier presets, match templates and the SPG quota.

Engine-free and shared by the client and the LAN server, so it must parse on
both the embedded Python 2.7 runtime and the Python 3 server.
"""

import hashlib
import math
import random


BATTLE_TIER_RADIUS = 2
MATCH_CLASSES = ('heavyTank', 'mediumTank', 'AT-SPG', 'lightTank', 'SPG')

BOT_TIER_MODE_RANDOM = 'random'
BOT_TIER_MODE_SAME = 'same'
BOT_TIER_MODE_MINUS1_0 = 'minus1_0'
BOT_TIER_MODE_0_PLUS1 = '0_plus1'
BOT_TIER_MODE_MINUS1_PLUS1 = 'minus1_plus1'
BOT_TIER_MODE_MINUS2_0 = 'minus2_0'
BOT_TIER_MODE_0_PLUS2 = '0_plus2'
BOT_TIER_MODES = (
    BOT_TIER_MODE_RANDOM, BOT_TIER_MODE_SAME, BOT_TIER_MODE_MINUS1_0,
    BOT_TIER_MODE_0_PLUS1, BOT_TIER_MODE_MINUS1_PLUS1,
    BOT_TIER_MODE_MINUS2_0, BOT_TIER_MODE_0_PLUS2)


def _number(value, default=0.0):
    try:
        result = float(value)
        if math.isinf(result) or math.isnan(result):
            return float(default)
        return result
    except Exception:
        return float(default)


def stable_seed(*parts):
    """Return the same positive integer on Python 2 and Python 3."""
    text_parts = []
    for part in parts:
        try:
            text_parts.append(str(part))
        except Exception:
            text_parts.append('?')
    payload = '|'.join(text_parts).encode('utf-8')
    return int(hashlib.sha1(payload).hexdigest()[:8], 16) & 0x7fffffff


def vehicle_in_battle_tier_band(player_tier, candidate_tier):
    """Admit the union of legal windows; bot_match_tiers chooses ONE window."""
    try:
        return abs(int(candidate_tier) - int(player_tier)) <= BATTLE_TIER_RADIUS
    except Exception:
        return False


def team_artillery_limit(team_size):
    """Cap automatic artillery by total team size, including human slots."""
    team_size = max(0, int(team_size))
    return 0 if team_size <= 6 else min(3, (team_size - 4) // 3)


def select_bot_lineup(pool, count, spg_limit=None, fallback_candidates=()):
    """Fill a team while enforcing an exact SPG cap.

    The caller subtracts human artillery from the total-team limit. ``AT-SPG``
    is a tank destroyer and does not consume the artillery quota.
    """
    count = max(0, int(count))
    if spg_limit is None:
        spg_limit = team_artillery_limit(count)
    spg_limit = max(0, min(3, int(spg_limit)))
    pool = list(pool or ())
    if not pool or count <= 0:
        return []
    regular = []
    seen = set()
    for candidate in pool + list(fallback_candidates or ()):
        try:
            tags = candidate['tags']
            name = candidate['name']
        except Exception:
            continue
        if 'SPG' in tags or name in seen:
            continue
        seen.add(name)
        regular.append(candidate)
    result = []
    spg_count = 0
    regular_index = 0
    for index in range(count):
        candidate = pool[index % len(pool)]
        try:
            is_spg = 'SPG' in candidate['tags']
        except Exception:
            is_spg = False
        if is_spg and spg_count >= spg_limit:
            if not regular:
                continue
            candidate = regular[regular_index % len(regular)]
            regular_index += 1
            is_spg = False
        if is_spg:
            spg_count += 1
        result.append(candidate)
    return result


def vehicle_match_class(candidate):
    """Return the matchmaking class for a vehicle record."""
    try:
        tags = candidate['tags']
    except Exception:
        tags = ()
    for class_tag in MATCH_CLASSES:
        if class_tag in tags:
            return class_tag
    return 'mediumTank'


def choose_match_tiers(player_tier, mode_roll, side_roll=0.5,
                       available_tiers=(), required_tiers=()):
    """Select one contiguous window, including the known LAN humans first.

    The synthetic room has no public queue. Its random sampling is an offline
    policy, not Wargaming's queue-time algorithm or historical probabilities.
    Explicitly wide human selections stay a custom room, never a five-tier
    automatic expansion around the first connected player.
    """
    player_tier = max(1, min(10, int(_number(player_tier, 1))))
    available = set(int(_number(value)) for value in
                    (available_tiers or range(1, 11)) if 1 <= _number(value) <= 10)
    required = set(int(_number(value)) for value in
                   (required_tiers or ()) if 1 <= _number(value) <= 10)
    required.add(player_tier)
    available.update(required)
    if max(required) - min(required) > 2:
        return tuple(sorted(required))
    preferred = 1 if _number(mode_roll) < 0.28 else (
        2 if _number(mode_roll) < 0.72 else 3)
    minimum = max(required) - min(required) + 1
    preferred = max(preferred, minimum)
    for width in range(preferred, minimum - 1, -1):
        windows = []
        for low in range(max(1, player_tier - width + 1),
                         min(player_tier, 11 - width) + 1):
            window = tuple(range(low, low + width))
            if required.issubset(window) and set(window).issubset(available):
                windows.append(window)
        if windows:
            index = min(len(windows) - 1,
                        int(max(0.0, min(1.0, _number(side_roll))) * len(windows)))
            return windows[index]
    return tuple(sorted(required))


def normalize_bot_tier_mode(value):
    """Return one supported waiting-room Bot tier preset."""
    return value if value in BOT_TIER_MODES else BOT_TIER_MODE_RANDOM


def bot_match_tiers(player_tier, mode, mode_roll=0.5, side_roll=0.5,
                    available_tiers=(), required_tiers=()):
    """Resolve a host-selected tier preset against the available catalog."""
    try:
        player_tier = max(1, min(10, int(player_tier)))
    except Exception:
        player_tier = 1
    available = set()
    for value in (available_tiers or range(1, 11)):
        try:
            value = int(value)
        except Exception:
            continue
        if 1 <= value <= 10:
            available.add(value)
    available.add(player_tier)
    mode = normalize_bot_tier_mode(mode)
    if mode == BOT_TIER_MODE_RANDOM:
        return choose_match_tiers(
            player_tier, mode_roll, side_roll, available, required_tiers)
    desired = {
        BOT_TIER_MODE_SAME: (player_tier,),
        BOT_TIER_MODE_MINUS2_0: (player_tier - 2, player_tier - 1, player_tier),
        BOT_TIER_MODE_0_PLUS2: (player_tier, player_tier + 1, player_tier + 2),
        BOT_TIER_MODE_MINUS1_0: (player_tier - 1, player_tier),
        BOT_TIER_MODE_0_PLUS1: (player_tier, player_tier + 1),
        BOT_TIER_MODE_MINUS1_PLUS1: (
            player_tier - 1, player_tier, player_tier + 1),
    }[mode]
    return tuple(value for value in desired if value in available)


def vehicle_in_bot_tier_mode(player_tier, candidate_tier, mode):
    """Whether a vehicle can fill the selected preset before template fill."""
    try:
        candidate_tier = int(candidate_tier)
    except Exception:
        return False
    if normalize_bot_tier_mode(mode) == BOT_TIER_MODE_RANDOM:
        return vehicle_in_battle_tier_band(player_tier, candidate_tier)
    return candidate_tier in bot_match_tiers(
        player_tier, mode, available_tiers=range(1, 11))


def shared_human_requirements(team_profiles):
    """Return the per-profile maxima that a mirrored team template must hold."""
    representatives = {}
    required_counts = {}
    for profiles in (team_profiles or {}).values():
        team_counts = {}
        for profile in (profiles or ()):
            try:
                key = (int(profile.get('level', 0) or 0),
                       vehicle_match_class(profile))
            except Exception:
                continue
            team_counts[key] = team_counts.get(key, 0) + 1
            representatives.setdefault(key, profile)
        for key, count in team_counts.items():
            required_counts[key] = max(required_counts.get(key, 0), count)
    result = []
    for key in sorted(required_counts):
        for unused in range(required_counts[key]):
            result.append(representatives[key])
    return result


def match_tier_slots(allowed_tiers, team_size):
    """9.18 priorities: low/middle/top 7/5/3, or low/top 10/5 at 15.

    Largest-remainder scaling is only for the offline custom team sizes.
    Human reservations and an incomplete catalogue may relax these counts.
    """
    levels = tuple(sorted(set(allowed_tiers)))
    if not levels or team_size <= 0:
        return []
    weights = {1: (15,), 2: (10, 5), 3: (7, 5, 3)}.get(
        len(levels), (1,) * len(levels))
    total = sum(weights)
    counts = [int(team_size) * weight // total for weight in weights]
    order = sorted(range(len(levels)), key=lambda index:
                   (-(int(team_size) * weights[index] % total), index))
    for index in order[:int(team_size) - sum(counts)]:
        counts[index] += 1
    return [level for level, count in zip(levels, counts)
            for unused in range(count)]


def build_match_template(pool, team_size, player_candidate, allowed_tiers,
                         rng=None, required_profiles=()):
    """Share tier/class slots and a size-bounded SPG quota between teams.

    Reserve SPGs against tiers that actually contain artillery, so a tier
    without artillery cannot silently replace the sole SPG slot.
    """
    rng = rng or random
    team_size = max(1, int(team_size))
    artillery_limit = team_artillery_limit(team_size)
    allowed = tuple(sorted(set(int(value) for value in allowed_tiers)))
    if not allowed:
        allowed = (int(player_candidate.get('level', 1) or 1),)
    usable = [candidate for candidate in (pool or ())
              if int(candidate.get('level', 0) or 0) in allowed]
    if not usable:
        usable = [player_candidate]
    required = list(required_profiles or (player_candidate,))[:team_size]
    tier_slots = match_tier_slots(allowed, team_size)
    rng.shuffle(tier_slots)
    result, usage = [], {}

    def take(choices):
        choices = list(choices)
        rng.shuffle(choices)
        candidate = min(choices, key=lambda value:
                        usage.get(str(value.get('name', '')), 0))
        name = str(candidate.get('name', ''))
        usage[name] = usage.get(name, 0) + 1
        result.append(candidate)
        level = int(candidate.get('level', 0) or 0)
        if level in tier_slots:
            tier_slots.remove(level)
        elif tier_slots:
            tier_slots.pop()

    for profile in required:
        if (vehicle_match_class(profile) == 'SPG' and
                sum(vehicle_match_class(value) == 'SPG' for value in result) >= artillery_limit):
            # A human's chosen SPG remains theirs; it must not force an
            # automatic mirrored SPG into a small opposing team.
            choices = [candidate for candidate in usable
                       if vehicle_match_class(candidate) != 'SPG']
            if choices:
                same_tier = [value for value in choices if int(value['level']) == int(profile['level'])]
                take(same_tier or choices)
            continue
        choices = [candidate for candidate in usable
                   if int(candidate.get('level', 0) or 0) == int(profile['level'])
                   and vehicle_match_class(candidate) == vehicle_match_class(profile)]
        take(choices or [profile])

    spg_count = sum(vehicle_match_class(value) == 'SPG' for value in result)
    spg_max = min(artillery_limit, spg_count + team_size - len(result))
    # Uniform within the size limit is a room choice, not a retail spawn rate.
    quota = spg_count + int(rng.random() * (max(0, spg_max - spg_count) + 1))
    quota = min(spg_max, quota)
    while spg_count < quota:
        choices = [candidate for candidate in usable
                   if vehicle_match_class(candidate) == 'SPG'
                   and int(candidate.get('level', 0) or 0) in tier_slots]
        if not choices:
            break
        take(choices)
        spg_count += 1

    regular_classes = ('heavyTank', 'mediumTank', 'AT-SPG', 'lightTank')
    regular = [candidate for candidate in usable
               if vehicle_match_class(candidate) != 'SPG']
    while len(result) < team_size:
        level = tier_slots[-1] if tier_slots else allowed[0]
        role = regular_classes[len(result) % len(regular_classes)]
        choices = [candidate for candidate in regular
                   if int(candidate.get('level', 0) or 0) == level]
        preferred = [candidate for candidate in choices
                     if vehicle_match_class(candidate) == role]
        choices = preferred or choices or regular
        if not choices:
            # Do not fill an impossible catalogue with 15 SPGs.
            if spg_count >= artillery_limit:
                break
            choices = usable
            spg_count += 1
        take(choices)
    return result


def remaining_match_template(template, human_profiles):
    """Remove the closest template slot for each human already on a team."""
    remaining = list(template or ())
    for human in (human_profiles or ()):
        if not remaining:
            break
        human_tier = int(human.get('level', 0) or 0)
        human_class = vehicle_match_class(human)
        best_index = 0
        best_score = None
        for index, candidate in enumerate(remaining):
            candidate_tier = int(candidate.get('level', 0) or 0)
            candidate_class = vehicle_match_class(candidate)
            score = abs(candidate_tier - human_tier) * 3
            if candidate_class != human_class:
                score += 8
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        remaining.pop(best_index)
    return remaining


def bot_initially_visible(bot_team, player_team, spotting_enabled):
    """Hide an enemy model before its first spotting update can run."""
    try:
        return (not bool(spotting_enabled) or
                int(bot_team) == int(player_team))
    except Exception:
        return not bool(spotting_enabled)
