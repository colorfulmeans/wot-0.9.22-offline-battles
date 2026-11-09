from __future__ import print_function

"""Roster fitting presets shared by the worker, server and launcher.

The historical module name is retained by wire-facing consumers, but rating
no longer changes target selection, aiming, lead or trigger admission. It
selects a native fitting tier only: researched modules, equipment and its
directive, crew training and skills, consumables and outfit retain their
existing independent overrides in bot_fittings and bot_tactics.

Crew training remains a real #1513 vehicle mechanic. Its actual aiming time,
dispersion, reload and other effects are applied by the native fitting model,
not by an additional artificial gunner error or delay in this module.
"""

import hashlib
import math
import random


SKILL_ROOKIE = 'rookie'
SKILL_REGULAR = 'regular'
SKILL_VETERAN = 'veteran'
SKILL_ELITE = 'elite'
SKILL_TIERS = (SKILL_ROOKIE, SKILL_REGULAR, SKILL_VETERAN, SKILL_ELITE)
DEFAULT_SKILL = SKILL_REGULAR

# Existing tier names, anchors and seeded draws remain stable for saved room
# settings and per-slot physical fitting assignments.
RATING_ANCHORS = (0.00, 0.34, 0.67, 1.00)
DEFAULT_RATING = RATING_ANCHORS[SKILL_TIERS.index(DEFAULT_SKILL)]
PROVEN_CREW_LEVELS = (50, 75, 100)
_CREW_LEVELS = dict(rookie=50, regular=75, veteran=100, elite=100)

SKILL_MODE_EASY = 'easy'
SKILL_MODE_RELAXED = 'relaxed'
SKILL_MODE_MIXED = 'mixed'
SKILL_MODE_HARD = 'hard'
SKILL_MODE_BRUTAL = 'brutal'
SKILL_MODES = (
    SKILL_MODE_EASY, SKILL_MODE_RELAXED, SKILL_MODE_MIXED,
    SKILL_MODE_HARD, SKILL_MODE_BRUTAL)
DEFAULT_SKILL_MODE = SKILL_MODE_MIXED

# Piecewise-linear inverse CDF, sampled once per round/team/slot. These
# distributions now choose fitting presets, never behavioural capabilities.
_MODE_RATING_POINTS = {
    SKILL_MODE_EASY: (0.00, 0.03, 0.08, 0.14, 0.30),
    SKILL_MODE_RELAXED: (0.05, 0.16, 0.28, 0.40, 0.67),
    SKILL_MODE_MIXED: (0.12, 0.42, 0.62, 0.80, 1.00),
    SKILL_MODE_HARD: (0.52, 0.70, 0.82, 0.92, 1.00),
    SKILL_MODE_BRUTAL: (1.00, 1.00, 1.00, 1.00, 1.00),
}


def _stable_seed(*parts):
    """Return the same positive integer on Python 2 and Python 3."""
    text_parts = []
    for part in parts:
        try:
            text_parts.append(str(part))
        except Exception:
            text_parts.append('?')
    payload = '|'.join(text_parts).encode('utf-8')
    return int(hashlib.sha1(payload).hexdigest()[:8], 16) & 0x7fffffff


def normalize_skill(value):
    """Return one supported native fitting tier name."""
    return value if value in SKILL_TIERS else DEFAULT_SKILL


def normalize_skill_mode(value):
    """Return one supported waiting-room fitting distribution."""
    return value if value in SKILL_MODES else DEFAULT_SKILL_MODE


def normalize_rating(value):
    """Return a bounded roster fitting rating, with the existing default."""
    try:
        rating = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_RATING
    if math.isnan(rating) or math.isinf(rating):
        return DEFAULT_RATING
    return max(0.0, min(1.0, rating))


def rating_for_skill(skill):
    return RATING_ANCHORS[SKILL_TIERS.index(normalize_skill(skill))]


def skill_for_rating(rating):
    """Return the nearest fitting tier; midpoint ties retain the lower tier."""
    rating = normalize_rating(rating)
    best_index = 0
    best_distance = None
    for index, anchor in enumerate(RATING_ANCHORS):
        distance = abs(rating - anchor)
        if best_distance is None or distance < best_distance - 1e-12:
            best_index, best_distance = index, distance
    return SKILL_TIERS[best_index]


def _interpolate(points, position):
    span = len(points) - 1
    scaled = max(0.0, min(1.0, position)) * span
    index = int(scaled)
    if index >= span:
        return float(points[-1])
    fraction = scaled - index
    lower = float(points[index])
    return lower + (float(points[index + 1]) - lower) * fraction


def rating_crew_level(rating):
    """Return native crew training for the resolved fitting tier."""
    return _CREW_LEVELS[skill_for_rating(rating)]


def crew_level(skill):
    return _CREW_LEVELS[normalize_skill(skill)]


def _mode_mean(mode):
    points = _MODE_RATING_POINTS[normalize_skill_mode(mode)]
    span = len(points) - 1
    return sum((points[index] + points[index + 1]) * 0.5 / span
               for index in range(span))


def resolve_rating(mode, round_id, team, slot):
    """Resolve one slot's fitting rating without global mutable state."""
    mode = normalize_skill_mode(mode)
    roll = random.Random(
        _stable_seed('bot-skill-rating-v1', round_id, mode, team,
                     slot)).random()
    return _interpolate(_MODE_RATING_POINTS[mode], roll)


def resolve_skill(mode, round_id, team, slot):
    return skill_for_rating(resolve_rating(mode, round_id, team, slot))
