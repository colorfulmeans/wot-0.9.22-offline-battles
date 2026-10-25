"""Pure-data tactical planner for the LAN bot authority.

The planner deliberately has no socket or BigWorld dependency. It imports only
the pure-data cover scorer shared with the client; all inputs and outputs are
JSON-compatible dictionaries so an eventual Go service can preserve the same
contract. Enemy data is accepted only through ``report_contacts``; players and
bot state are used to validate identities, never to invent a target position.
"""

import copy
import math
import os
import sys


_PORT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_CLIENT_SCRIPT_ROOT = os.path.join(
    _PORT_ROOT, 'src', 'res', 'scripts', 'client')
if _CLIENT_SCRIPT_ROOT not in sys.path:
    sys.path.insert(0, _CLIENT_SCRIPT_ROOT)

from gui.mods.offline_lan_0922 import bot_gunnery
from gui.mods.offline_lan_0922 import spg_positions, bot_tactics
from gui.mods.offline_lan_0922 import capture_orders
from server_route_recovery import RouteRecoveryMixin, ROUTE_ATTEMPT_SECONDS, MIN_ROUTE_AFFINITY
from server_route_tasks import RouteTasksMixin
from gui.mods.offline_lan_0922.ai.cover import (
    normalize_candidate,
    score_candidates,
)


CONTACT_TTL_SECONDS = 8.0
MAX_CONTACTS_PER_TEAM = 32
# The hidden worker samples at most three active cover users per second.  A
# full 29-Bot roster therefore needs almost ten seconds for one fair pass;
# retain the last geometry long enough for that pass plus publication jitter.
COVER_TTL_SECONDS = 12.0
MAX_COVER_REPORTS = 16
MAX_COVER_CANDIDATES = 12
COVER_PROGRESS_TIMEOUT_SECONDS = 8.0
COVER_PROGRESS_EPSILON = 1.5
COVER_CANDIDATE_RETRY_SECONDS = 12.0
TARGET_LEASE_SECONDS = 2.0
TARGET_SWITCH_MARGIN = 3.0
TARGET_AIM_NO_PROGRESS_SECONDS = 6.0
COMBAT_MODE_DWELL_SECONDS = 2.0
COMBAT_RANGE_HYSTERESIS_FRACTION = 0.06
COMBAT_RANGE_HYSTERESIS_MIN = 8.0
COMBAT_RANGE_HYSTERESIS_MAX = 20.0
RETREAT_ARRIVAL_RADIUS = 6.0
RETREAT_PROGRESS_TIMEOUT_SECONDS = 10.0
RETREAT_DEFENSIVE_PAUSE_SECONDS = 15.0
RETREAT_PROGRESS_EPSILON = 2.0
ROUTE_ARRIVAL_RADIUS = bot_tactics.ROUTE_ARRIVAL_RADIUS
CLOSE_THREAT_DISTANCE = 50.0
CLOSE_THREAT_SCORE_BONUS = 100.0
CLOSE_THREAT_FOCUS_LIMIT = 4
ROUTE_REBALANCE_SECONDS = 180.0
# Cover the next scheduled evaluation, including one server-tick boundary.
ROUTE_LEASE_SECONDS = ROUTE_REBALANCE_SECONDS + 1.0
WRECK_ROUTE_WAIT_SECONDS = ROUTE_ATTEMPT_SECONDS
WRECK_ROUTE_AVOID_SECONDS = 120.0
MAX_BASE_DEFENDERS = 3
BASE_DEFENSE_RELEASE_SECONDS = 3.0
MIN_ROUTE_CLASS_AFFINITY = MIN_ROUTE_AFFINITY
RECENT_HIT_SECONDS = 6.0
RECENT_ATTACKER_SCORE_BONUS = 140.0
# Target ranking weights.  A lower score wins, so a per-metre term prefers a
# nearer enemy and a bonus is subtracted.  All four are product numbers for
# this project; none of them is retail data.
#
# Every Bot pays the reach term at every rating.  How far a gun has to shoot
# is a fact about the gun, not a tactic, and without it a Bot that has not
# reached the nearest-enemy rung would rank a 400 m contact ahead of a 100 m
# one on nothing but a contact id.
TARGET_REACH_SCORE_PER_METRE = 0.018
# Deliberately preferring the nearer enemy is the ladder's first rung, so it
# is weighted to matter against the other rungs rather than to dominate them:
# a weakened target still wins inside roughly 100 m of extra travel, and the
# nearer target wins once the gap grows past roughly 200 m.
NEAREST_TARGET_SCORE_PER_METRE = 0.12
# The human is the round's real opponent, so the top rung goes for the player
# ahead of an equally convenient Bot. This preference alone is weaker than
# point-blank self-defence; retaliation also contributes to the total score.
HUMAN_TARGET_SCORE_BONUS = 60.0
# How much of the ranking the most nearly dead contact is worth.
TARGET_HEALTH_SCORE_SPAN = 28.0
CROSSFIRE_MIN_ANGLE = math.radians(55.0)
CROSSFIRE_MAX_DISTANCE = 360.0
TEAM_ORDER_COMMANDS = frozenset((
    "ATTACK", "BACKTOBASE", "HELPME", "FOLLOWME", "TURNBACK",
    "HELPMEEX", "STOP", "ATTACKENEMY", "SUPPORTMEWITHFIRE",
    "ATTENTIONTOCELL", "POSITIVE", "NEGATIVE",
))
TEAM_ORDER_ENEMY_COMMANDS = frozenset((
    "ATTACKENEMY", "SUPPORTMEWITHFIRE",
))
TEAM_ORDER_NAVIGATION_COMMANDS = frozenset((
    "ATTACK", "FOLLOWME", "HELPME", "HELPMEEX", "STOP", "TURNBACK",
    "BACKTOBASE", "ATTENTIONTOCELL",
))


def _number(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _point(raw):
    raw = raw or {}
    return {
        "x": round(_clamp(_number(raw.get("x")), -2000.0, 2000.0), 3),
        "y": round(_clamp(_number(raw.get("y")), -1000.0, 1000.0), 3),
        "z": round(_clamp(_number(raw.get("z")), -2000.0, 2000.0), 3),
    }


def _route_point_reached(bx, bz, waypoints, index, route_limit, previous=None):
    """Use the same disk/crossing contract as the client tactical owner."""
    point = waypoints[index]
    following = waypoints[index+1] if index < route_limit else None
    return bot_tactics.route_disk_reached((bx, bz),
        (_number(point.get('x')), _number(point.get('z'))),
        (_number(following.get('x')), _number(following.get('z'))) if following else None,
        previous)


def _bot_rating(raw):
    """Return one manifest entry's competence rating.

    An entry carrying neither field predates the rating.  It keeps this
    project's original behaviour - every Bot executing every tactic - rather
    than silently becoming a 34 percent Bot because the plumbing failed.
    """
    if "skill_rating" in raw:
        return bot_gunnery.normalize_rating(raw.get("skill_rating"))
    skill = raw.get("skill")
    if skill in bot_gunnery.SKILL_TIERS:
        return bot_gunnery.rating_for_skill(skill)
    return 1.0


def _order_signature(order):
    """Return the strategic fields which advance the order revision."""
    signature = dict(order or {})
    # Attempt observations are telemetry, not a new strategic instruction.
    signature.pop('route_attempt', None)
    signature.pop('route_assignment', None)
    signature.pop('tactical_evidence', None)
    if signature.get("target_id") is not None:
        # The worker overlays these coordinates from the live target pose.
        # Movement of that pose is not a new tactical decision, including
        # while an SPG is still waiting for permission to fire.
        signature.pop("aim_position", None)
        signature.pop("face_position", None)
        if signature.get("combat_mode") == "advance_contact":
            signature.pop("move_position", None)
    return signature


class BotPlanner(RouteTasksMixin, RouteRecoveryMixin):
    """Server-side route, focus-fire, and last-contact order coordinator."""

    def __init__(self):
        self.tactics = bot_tactics.empty()
        self.tactics_map = ''
        self.revision = 0
        self._round_id = 0
        self._contacts = {1: {}, 2: {}}
        self._last_orders = None
        self._last_order_signature = None
        self._route_states = {}
        self._route_history = {}
        self._wait_claims = {}
        self._route_recoveries = {}
        self._recovery_route_visits = {}
        self._wreck_route_progress = {}
        self._wreck_route_avoid = {}
        self._route_assignments = {}
        self._route_assignment_receipts = {}
        self._route_balance_receipts = {}
        self._next_route_rebalance = {1: 0.0, 2: 0.0}
        self._task_init()
        self._engage_anchors = {}
        self._firing_holds = {}
        self._affordances = {}
        self._cover_states = {}
        self._cover_failures = {}
        self._cover_reservations = set()
        self._target_assignments = {}
        self._target_decisions = {}
        self._combat_states = {}
        self._retreat_states = {}
        self._base_defense = {1: {}, 2: {}}
        self._capture_arrivals = {}
        self._artillery_anchors = {}
        self._recent_hits = {}

    def reset(self, round_id=None):
        """Start a clean round.

        ``round_id`` salts every competence draw, so a roster slot that never
        angled last round is not condemned to the same habit for the life of
        the server process.
        """
        self.revision = 0
        if round_id is not None:
            self._round_id = _integer(round_id)
        self._contacts = {1: {}, 2: {}}
        self._last_orders = None
        self._last_order_signature = None
        self._route_states = {}
        self._route_history = {}
        self._wait_claims = {}
        self._route_recoveries = {}
        self._recovery_route_visits = {}
        self._wreck_route_progress = {}
        self._wreck_route_avoid = {}
        self._route_assignments = {}
        self._route_assignment_receipts = {}
        self._route_balance_receipts = {}
        self._next_route_rebalance = {1: 0.0, 2: 0.0}
        self._task_init()
        self._engage_anchors = {}
        self._firing_holds = {}
        self._affordances = {}
        self._cover_states = {}
        self._cover_failures = {}
        self._cover_reservations = set()
        self._target_assignments = {}
        self._target_decisions = {}
        self._combat_states = {}
        self._retreat_states = {}
        self._base_defense = {1: {}, 2: {}}
        self._capture_arrivals = {}
        self._artillery_anchors = {}
        self._recent_hits = {}

    def _capable(self, bot, capability, *occasion):
        """Return whether one Bot does the tactically right thing this time.

        A latched capability is seeded with round and Bot identity alone, so
        the answer holds for the battle and a roster keeps Bots with a
        recognisable habit.  Every other capability is seeded with the
        identity of the single decision - a target lease, a cover manoeuvre,
        one hit - so a Bot hesitates instead of being uniformly incapable,
        and the answer still cannot flip inside one manoeuvre.

        Nothing is stored.  An order rebuilt on the next tick, or by a
        replacement authority after a failover, reaches the same answer.
        """
        if capability in bot_gunnery.LATCHED_CAPABILITIES:
            occasion = ()
        return bot_gunnery.capability_allowed(
            bot.get("rating"), capability, self._round_id, bot.get("id"),
            *occasion)

    def report_damage(self, victim_bot_id, attacker_kind, attacker_id,
                      damage, now):
        """Record one server-admitted hostile hit for tactical reactions."""
        victim_bot_id = _integer(victim_bot_id)
        attacker_id = _integer(attacker_id)
        damage = max(0, _integer(damage))
        kind = str(attacker_kind or "")
        if kind == "player":
            kind = "human"
        if (victim_bot_id <= 0 or attacker_id <= 0 or damage <= 0 or
                kind not in ("human", "bot")):
            return False
        self._recent_hits[victim_bot_id] = {
            "attacker": (kind, attacker_id),
            "reported_at": _number(now),
            "damage": damage,
        }
        return True

    def report_contacts(self, contacts, known_targets, now,
                        accepted_visibility=None):
        """Store only authority-reported observations after identity checks.

        ``known_targets`` maps an id to ``{"team": int, "alive": bool}``.
        Reporting a contact never looks up its target's live pose, which keeps
        this server from becoming omniscient.
        """
        accepted = 0
        if not isinstance(contacts, (list, tuple)):
            return accepted
        for raw in contacts[:MAX_CONTACTS_PER_TEAM * 2]:
            if not isinstance(raw, dict):
                continue
            # This package does not support mixed authority-client builds.
            # Missing or malformed per-bot firing-lane evidence must not fall
            # back to the old "every bot can shoot" interpretation.
            if ("shootable_by_bot_ids" not in raw or
                    not isinstance(raw.get("shootable_by_bot_ids"),
                                   (list, tuple)) or
                    "visible" not in raw or
                    not isinstance(raw.get("visible"), bool)):
                continue
            observing_team = _integer(raw.get("observing_team"))
            target_id = _integer(raw.get("target_id"))
            target_kind = str(raw.get("target_kind") or "")
            target = known_targets.get((target_kind, target_id)) if target_kind else None
            if target is None and not target_kind:
                matches = [value for key, value in known_targets.items()
                           if key[1] == target_id]
                if len(matches) == 1:
                    target = matches[0]
                    target_kind = target["kind"]
            if observing_team not in (1, 2) or target is None:
                continue
            if (_integer(target.get("team")) == observing_team or
                    _integer(raw.get("target_team"), target.get("team")) != _integer(target.get("team"))):
                continue
            if not bool(target.get("alive", True)):
                continue
            visible = bool(raw.get("visible", True))
            fresh = bool(raw.get("fresh", visible))
            time_left = max(0.0, _number(
                raw.get("time_left"), 10.0 if visible else 0.0))
            contact_key = (target_kind, target_id)
            previous = self._contacts[observing_team].get(contact_key)
            if visible:
                position = _point(raw)
                threatened = raw.get("threatened_bot_ids")
                threatened = (self._bot_id_list(threatened)
                              if isinstance(threatened, (list, tuple))
                              else None)
                self._contacts[observing_team][contact_key] = {
                    "id": target_id,
                    "target_kind": target_kind,
                    "team": _integer(target.get("team")),
                    "visible": True,
                    "last_seen": _number(now),
                    "position": position,
                    "health": max(0, _integer(raw.get("health"), 1)),
                    "max_health": max(1, _integer(raw.get("max_health"), 1)),
                    "class_tag": str(raw.get("class_tag") or "unknown")[:24],
                    "armor": max(0.0, _number(raw.get("armor"), 0.0)),
                    "shootable_by_bot_ids": self._bot_id_list(
                        raw.get("shootable_by_bot_ids")),
                    "pending_lane_by_bot_ids": self._bot_id_list(
                        raw.get("pending_lane_by_bot_ids")),
                    # Positive incoming-fire evidence. None means this pair
                    # was not sampled; an empty list is still not a global
                    # proof that the team is safe.
                    "threatened_bot_ids": threatened,
                }
                if "radio_recipients" in raw:
                    self._contacts[observing_team][contact_key]["radio_bot_until"] = {
                        _integer(row.get("id")): _number(now) + max(
                            0.0, min(10.0, _number(row.get("time_left"))))
                        for row in raw["radio_recipients"]
                        if isinstance(row, dict) and row.get("kind") == "bot"}
                accepted += 1
                if accepted_visibility is not None:
                    accepted_contact = {
                        "observing_team": observing_team,
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "target_team": _integer(target.get("team")),
                        "visible": True,
                        "fresh": fresh,
                        "time_left": time_left,
                        "visible_by_bot_ids": self._bot_id_list(
                            raw.get("visible_by_bot_ids")),
                        "visible_by_player_ids": self._bot_id_list(
                            raw.get("visible_by_player_ids")),
                        "shootable_by_bot_ids": self._bot_id_list(
                            raw.get("shootable_by_bot_ids")),
                    }
                    if threatened is not None:
                        accepted_contact["threatened_bot_ids"] = list(
                            threatened)
                    # Preserve the validated recipient schema even with the
                    # historical tactical policy. Do not turn radio leases
                    # back into a team-wide or self-spot-only presentation.
                    if "radio_recipients" in raw:
                        accepted_contact["radio_recipients"] = [
                            dict(row) for row in raw["radio_recipients"]]
                    accepted_visibility.append(accepted_contact)
            elif previous is not None:
                previous["visible"] = False
                previous["shootable_by_bot_ids"] = []
                previous["pending_lane_by_bot_ids"] = []
                previous["threatened_bot_ids"] = []
                if "radio_recipients" in raw or "radio_bot_until" in previous:
                    previous["radio_bot_until"] = {}
                accepted += 1
                if accepted_visibility is not None:
                    accepted_visibility.append({
                        "observing_team": observing_team,
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "target_team": _integer(target.get("team")),
                        "visible": False,
                        "fresh": False,
                        "time_left": 0.0,
                        "visible_by_bot_ids": [],
                        "visible_by_player_ids": [],
                        "shootable_by_bot_ids": [],
                        "threatened_bot_ids": [],
                    })
                    if "radio_recipients" in raw:
                        accepted_visibility[-1]["radio_recipients"] = []
        return accepted

    @staticmethod
    def _bot_id_list(raw):
        if not isinstance(raw, (list, tuple)):
            return []
        result = []
        seen = set()
        for value in raw[:MAX_CONTACTS_PER_TEAM]:
            bot_id = _integer(value)
            if bot_id <= 0 or bot_id in seen:
                continue
            seen.add(bot_id)
            result.append(bot_id)
        return result

    def report_affordances(self, reports, known_bots, known_targets, now):
        """Store client-probed cover geometry after identity validation.

        The server never probes map geometry.  It accepts only candidates for
        a live bot and an enemy already present in that bot team's contact
        memory, then chooses among those candidates globally.
        """
        accepted = 0
        if not isinstance(reports, (list, tuple)):
            return accepted
        for raw in reports[:MAX_COVER_REPORTS]:
            if not isinstance(raw, dict):
                continue
            bot_id = _integer(raw.get("bot_id"))
            bot = known_bots.get(bot_id)
            target_kind = str(raw.get("target_kind") or "")
            target_id = _integer(raw.get("target_id"))
            target_key = (target_kind, target_id)
            target = known_targets.get(target_key)
            if (bot is None or not bot.get("alive", True) or target is None or
                    _integer(bot.get("team")) == _integer(target.get("team"))):
                continue
            contact = self._contacts.get(_integer(bot.get("team")), {}).get(target_key)
            if (contact is None or not contact.get("visible") or
                    _number(now) - _number(contact.get("last_seen")) > CONTACT_TTL_SECONDS):
                continue
            candidates = []
            raw_candidates = raw.get("candidates")
            if not isinstance(raw_candidates, (list, tuple)):
                continue
            bx = _number(bot.get("x"))
            bz = _number(bot.get("z"))
            for value in raw_candidates[:MAX_COVER_CANDIDATES]:
                candidate = normalize_candidate(value)
                if candidate.get("position") is None:
                    continue
                if candidate.get("peek_feasible") and candidate.get("peek_position") is None:
                    continue
                candidate["position"] = _point(candidate.get("position"))
                if candidate.get("peek_position") is not None:
                    candidate["peek_position"] = _point(candidate.get("peek_position"))
                if (candidate["travel_distance"] > 180.0 or
                        candidate["water"] >= 0.5 or candidate["slope"] > 28.0):
                    continue
                if math.hypot(candidate["position"]["x"] - bx,
                              candidate["position"]["z"] - bz) > 180.0:
                    continue
                if (candidate.get("peek_position") is not None and
                        math.hypot(candidate["peek_position"]["x"] - bx,
                                   candidate["peek_position"]["z"] - bz) > 200.0):
                    continue
                candidates.append(candidate)
            if not candidates:
                continue
            self._affordances[bot_id] = {
                "target": target_key,
                "reported_at": _number(now),
                "candidates": candidates,
            }
            accepted += 1
        return accepted

    @staticmethod
    def _team_orders_by_bot(team_orders, bots):
        """Index the newest structurally live server-admitted order per Bot."""
        live = dict((bot["id"], bot) for bot in bots)
        result = {}
        if not isinstance(team_orders, (list, tuple)):
            return result
        ordered = sorted(
            (value for value in team_orders if isinstance(value, dict)),
            # Stable sorting preserves the server's admission order within a
            # tick. Lexicographic command IDs put sequence 9 after 10.
            key=lambda value: _integer(value.get("issued_tick")))
        for raw in ordered:
            command = str(raw.get("command") or "")
            if (command not in TEAM_ORDER_COMMANDS or
                    _integer(raw.get("expires_tick")) <=
                    _integer(raw.get("issued_tick"))):
                continue
            recipients = raw.get("recipient_bot_ids")
            if not isinstance(recipients, (list, tuple)):
                continue
            for raw_bot_id in recipients:
                bot_id = _integer(raw_bot_id)
                bot = live.get(bot_id)
                if (bot is None or
                        bot["team"] != _integer(raw.get("team"))):
                    continue
                result[bot_id] = dict(raw)
        return result

    @staticmethod
    def _team_order_focus(team_order, bot, contacts):
        if (not isinstance(team_order, dict) or
                team_order.get("command") not in
                TEAM_ORDER_ENEMY_COMMANDS):
            return None
        target_kind = str(team_order.get("target_kind") or "")
        if target_kind == "player":
            target_kind = "human"
        target_id = _integer(team_order.get("target_id"))
        for contact in contacts or ():
            if ((str(contact.get("target_kind") or ""),
                 _integer(contact.get("id"))) !=
                    (target_kind, target_id)):
                continue
            if (contact.get("visible") and
                    bot["id"] in (contact.get(
                        "shootable_by_bot_ids") or ()) and
                    BotPlanner._weapon_can_recover(bot)):
                return contact
        return None

    @staticmethod
    def _mark_flank_suppressors(assignments, bots):
        """Fence each local flank group with an assigned covering shooter."""
        bot_by_id = dict((bot["id"], bot) for bot in bots)
        groups = {}
        for bot_id, contact in assignments.items():
            bot = bot_by_id.get(bot_id)
            if (bot is None or contact.get("movement_lease") or
                    not BotPlanner._weapon_ready(bot)):
                continue
            key = (str(contact.get("target_kind") or ""),
                   _integer(contact.get("id")))
            groups.setdefault(key, []).append(bot)
        result = dict(assignments)
        for key, shooters in groups.items():
            if len(shooters) < 2:
                continue
            contact = assignments[shooters[0]["id"]]
            tx = _number(contact.get("position", {}).get("x"))
            tz = _number(contact.get("position", {}).get("z"))

            def hold_key(ally):
                profile = ally.get("profile") if isinstance(
                    ally.get("profile"), dict) else {}
                roles = profile.get("roles") if isinstance(
                    profile.get("roles"), dict) else {}
                state = ally.get("state") if isinstance(
                    ally.get("state"), dict) else {}
                return (_number(roles.get("flanker")), math.hypot(
                    _number(state.get("x")) - tx,
                    _number(state.get("z")) - tz), ally["id"])

            suppressor_id = min(shooters, key=hold_key)["id"]
            assigned_ids = [ally["id"] for ally in shooters]
            for ally in shooters:
                marked = dict(result[ally["id"]])
                marked["assigned_shooter_ids"] = list(assigned_ids)
                marked["flank_suppressor_bot_ids"] = [suppressor_id]
                result[ally["id"]] = marked
        return result

    @staticmethod
    def _apply_team_order(order, bot, team_order, players, defense,
                          route_point=None, turnback_point=None):
        """Overlay one admitted radio intent without inventing target data."""
        if not isinstance(team_order, dict):
            return order
        command = str(team_order.get("command") or "")
        if command not in TEAM_ORDER_COMMANDS:
            return order
        order["team_command_id"] = str(team_order.get("command_id") or "")
        order["team_command"] = command
        if "cell_index" in team_order:
            order["team_command_cell_index"] = _integer(
                team_order.get("cell_index"))

        # An admitted navigation command is a direct player control and must
        # replace autonomous tactics. Combat radio still cannot cancel a local
        # survival action or an urgent base response.
        protected_modes = (
            "base_defense", "low_health_retreat", "low_health_defend",
            "magazine_reload_retreat", "magazine_reload_hold",
            "under_fire_withdraw", "under_fire_hold",
            "crossfire_withdraw", "crossfire_hold",
        )
        if ((order.get("combat_mode") in protected_modes or order.get('defense_base_id')) and
                command not in TEAM_ORDER_NAVIGATION_COMMANDS):
            return order

        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        if command == "ATTACK":
            target = (route_point if isinstance(route_point, dict)
                      else order["move_position"])
            order["combat_mode"] = "team_attack"
            order["move_position"] = dict(target)
            if order.get("target_id") is None:
                order["face_position"] = dict(target)
            order["throttle_override"] = None
            return order
        if command == "STOP":
            order["combat_mode"] = "team_stop"
            order["move_position"] = _point(state)
            order["throttle_override"] = 0.0
            return order
        if command == "TURNBACK":
            target = (turnback_point if isinstance(turnback_point, dict)
                      else order["route_anchor"])
            order["combat_mode"] = "team_turnback"
            order["move_position"] = dict(target)
            order["face_position"] = dict(target)
            order["throttle_override"] = None
            return order
        if command == "BACKTOBASE":
            bases = (defense.get("capture_bases")
                     if isinstance(defense, dict) else None)
            points = BotPlanner._defense_points(bases, bot["team"])
            if points:
                base = min(points, key=lambda value: math.hypot(
                    value["point"]["x"] - _number(state.get("x")),
                    value["point"]["z"] - _number(state.get("z"))))
                order["combat_mode"] = "team_back_to_base"
                order["move_position"] = dict(base["point"])
                order["face_position"] = dict(base["point"])
                order["throttle_override"] = None
            return order
        if command == "ATTENTIONTOCELL":
            raw_bounds = (defense.get("arena_bounds")
                          if isinstance(defense, dict) else None)
            try:
                bounds = tuple(float(value) for value in raw_bounds)
            except (TypeError, ValueError, OverflowError):
                bounds = ()
            cell_index = team_order.get("cell_index")
            if (len(bounds) == 4 and
                    all(math.isfinite(value) for value in bounds) and
                    bounds[0] < bounds[2] and bounds[1] < bounds[3] and
                    isinstance(cell_index, int) and
                    not isinstance(cell_index, bool) and
                    0 <= cell_index <= 99):
                column, row = divmod(cell_index, 10)
                cell_width = (bounds[2] - bounds[0]) / 10.0
                cell_height = (bounds[3] - bounds[1]) / 10.0
                cell_min_x = bounds[0] + column * cell_width
                cell_max_x = cell_min_x + cell_width
                cell_max_z = bounds[3] - row * cell_height
                cell_min_z = cell_max_z - cell_height
                point = {
                    "x": round((cell_min_x + cell_max_x) * 0.5, 3),
                    # The worker's navigator resolves terrain. Preserve the
                    # current live altitude instead of guessing target ground.
                    "y": round(_number(state.get("y")), 3),
                    "z": round((cell_min_z + cell_max_z) * 0.5, 3),
                }
                order["combat_mode"] = "team_attention_cell"
                order["move_position"] = point
                order["move_area_bounds"] = [
                    round(cell_min_x, 3), round(cell_min_z, 3),
                    round(cell_max_x, 3), round(cell_max_z, 3),
                ]
                order["face_position"] = dict(point)
                order["throttle_override"] = None
            return order
        if command in ("HELPME", "HELPMEEX", "FOLLOWME"):
            issuer_id = _integer(team_order.get("issuer_id"))
            issuer = next((value for value in (players or ())
                           if _integer(value.get("id")) == issuer_id and
                           _integer(value.get("team")) == bot["team"] and
                           value.get("alive", True) and
                           value.get("world_pose") is True), None)
            if issuer is not None:
                point = _point(issuer)
                # A tactical escort keeps room for both hulls instead of
                # continually asking the driver to occupy the human's centre.
                recipients = team_order.get("recipient_bot_ids") or [bot["id"]]
                slot = recipients.index(bot["id"]) if bot["id"] in recipients else 0
                lateral = (slot - (len(recipients) - 1) * 0.5) * 12.0
                yaw = _number(issuer.get("yaw"))
                point["x"] += -math.sin(yaw) * 18.0 + math.cos(yaw) * lateral
                point["z"] += -math.cos(yaw) * 18.0 - math.sin(yaw) * lateral
                order["combat_mode"] = "team_follow"
                order["move_position"] = point
                order["face_position"] = dict(point)
                order["throttle_override"] = None
            return order
        # Enemy-target commands retain the ordinary locally proved target and
        # firing checks. Cell and social commands remain explicit markers for
        # the worker/UI until a validated world point or response exists.
        return order

    def build_orders(self, manifest, bot_states, players, now,
                     defense=None, team_orders=None):
        radii = dict((row['id'], _number(row.get('profile', {}).get(
            'parking_radius'), math.hypot(3.5, 1.7))) for row in manifest or ())
        self._wait_bodies = [dict(row, parking_kind='bot',
            parking_radius=radii.get(row['id'], math.hypot(3.5, 1.7)))
            for row in bot_states or ()] + [dict(row, parking_kind='human')
            for row in players or ()]
        known_targets = self.known_targets(bot_states, players)
        contacts = self._prune_contacts(known_targets, now)
        bots = self._alive_bots(manifest, bot_states, self.tactics)
        self._prune_tactical_state(bots, known_targets, now)
        defenders = self._update_base_defense(
            bots, contacts, defense, now)
        self._cover_reservations = set()
        team_axes = dict((team, self._team_base_axis(team, bots))
                         for team in (1, 2))
        capture_targets = dict((team, self._capture_target(defense, team))
                               for team in (1, 2))
        team_order_by_bot = self._team_orders_by_bot(team_orders, bots)
        orders = []
        self._target_decisions = {}
        for team in (1, 2):
            team_bots = sorted((bot for bot in bots if bot["team"] == team),
                               key=lambda value: value["id"])
            team_axis = team_axes[team]
            protected_ids = set(defenders.get(team, {}))
            self._rebalance_routes(
                team, team_bots, contacts[team], now, protected_ids)
            assignments = self._assign_targets(team_bots, contacts[team], now)
            assignments = self._prioritize_base_invaders(
                team, team_bots, contacts[team], assignments,
                defenders.get(team, {}), defense, now)
            for bot in team_bots:
                commanded_focus = self._team_order_focus(
                    team_order_by_bot.get(bot["id"]), bot,
                    self._contacts_for_bot(bot, contacts[team], now))
                if (commanded_focus is not None and assignments.get(bot['id']) is None and
                        bot["id"] not in defenders.get(team, {})):
                    assignments[bot["id"]] = commanded_focus
            assignments = self._mark_flank_suppressors(
                assignments, team_bots)
            for index, bot in enumerate(team_bots):
                order = self._order_for(
                    bot, index, len(team_bots), assignments.get(bot["id"]),
                    self._contacts_for_bot(bot, contacts[team], now), now,
                    defenders.get(team, {}).get(bot["id"]), team_axis,
                    team_bots, capture_targets[team],
                    not self._contacts_for_bot(bot, contacts[team], now),
                    active_capture=('bot', bot['id']) in
                        self._defense_contributor_keys(defense, 3-team))
                route_point = order.pop("_route_position")
                turnback_point = order.pop("_turnback_position")
                player_order = team_order_by_bot.get(bot['id'])
                combat = self._task_combat(order)
                automatic = (bot['id'] in defenders.get(team,{}) or bot['id'] in self._route_recoveries or
                    (self._travel_tasks.get(bot['id']) or {}).get('kind') in ('defense','pressure'))
                if combat or automatic:
                    if player_order:order['player_command_cancelled'] = True
                    player_order = None
                else:
                    self._apply_team_order(order, bot, player_order, players, defense, route_point, turnback_point)
                self._task_apply(order, bot, now, defenders.get(team,{}).get(bot['id']), player_order, defense)
                self._task_capture_handoff(order,bot,capture_targets[team])
                self._apply_authored_route_order(order, bot, route_point, now)
                self._handoff_route_terminal(order, bot, capture_targets[team], now)
                self._reroute_wreck_stall(order, bot, manifest, now)
                if ((order.get('route_attempt') or {}).get('action') in (
                        'recovery_complete', 'switch_at_start') and
                        bot['id'] not in self._route_recoveries):
                    self._handoff_route_terminal(order, bot, capture_targets[team], now)
                self._protect_capture_order(order, bot, capture_targets[team])
                evidence = order['tactical_evidence']
                evidence['retreat_after'] = dict(self._retreat_states.get(bot['id']) or {})
                evidence['final'] = dict((key, order.get(key)) for key in (
                    'combat_mode', 'tactical_phase', 'target_id', 'target_kind',
                    'fire_allowed', 'throttle_override', 'move_position', 'face_position'))
                order['route_assignment'] = dict(
                    self._route_assignment_receipts.get(bot['id']) or {})
                progress = (self._route_states.get(bot['id']) or {}).get('progress_receipt')
                progress = dict(progress or dict(outcome='no_active_route_evaluation', at=None))
                progress.update(
                    observation='evaluated' if progress['at'] == now else 'previous_or_unavailable',
                    age_seconds=now-progress['at'] if progress['at'] is not None else None,
                    final_order=dict(mode=order.get('combat_mode'),
                        route_id=order.get('route_id'), route_index=order.get('route_index'),
                        move_position=order.get('move_position')))
                order['route_assignment']['progress'] = progress
                balance = dict(self._route_balance_receipts.get(bot['team']) or {})
                balance.pop('contact_inputs', None)
                balance.pop('contributor_inputs', None)
                checks = balance.pop('candidates', ())
                balance.update(observed_at=now, candidate=next((dict(row) for row in checks
                    if row['bot'] == bot['id']), None))
                order['route_assignment']['balance'] = balance
                lease = self._route_assignments.get(bot['id']) or {}
                if _number(lease.get('until')) > 0.0:
                    order['route_assignment']['lease'] = dict(
                        until=_number(lease['until']),
                        check=dict(lease.get('_lease_check') or {}),
                        observation=dict(lease.get('_lease_observation') or {}))
                orders.append(order)
        orders.sort(key=lambda value: value["id"])
        payload = {"orders": orders}
        signature_orders = [_order_signature(order) for order in orders]
        signature_payload = {"orders": signature_orders}
        if signature_payload != self._last_order_signature:
            self.revision += 1
            self._last_order_signature = signature_payload
        self._last_orders = payload
        return {"revision": self.revision, "orders": orders}

    def debug_summary(self, now):
        """Return low-volume evidence for contact -> order diagnostics."""
        result = {"teams": {}}
        orders = ((self._last_orders or {}).get("orders") or [])
        for team in (1, 2):
            known = 0
            visible = 0
            for contact in self._contacts.get(team, {}).values():
                if _number(now) - _number(contact.get("last_seen")) > CONTACT_TTL_SECONDS:
                    continue
                known += 1
                if contact.get("visible"):
                    visible += 1
            team_orders = [order for order in orders
                           if _integer(order.get("team")) == team]
            modes = {}
            for order in team_orders:
                mode = str(order.get("combat_mode") or "unknown")
                modes[mode] = modes.get(mode, 0) + 1
            result["teams"][team] = {
                "contacts": known,
                "visible": visible,
                "orders": len(team_orders),
                "targeted": sum(order.get("target_id") is not None
                                for order in team_orders),
                "fire": sum(bool(order.get("fire_allowed"))
                            for order in team_orders),
                "modes": modes,
            }
        return result

    @staticmethod
    def known_targets(bot_states, players):
        result = {}
        for raw in players or []:
            target_id = _integer(raw.get("id"))
            if target_id:
                result[("human", target_id)] = {
                    "kind": "human", "team": _integer(raw.get("team")),
                    "alive": bool(raw.get("alive", True))}
        for raw in bot_states or []:
            target_id = _integer(raw.get("id"))
            if target_id:
                result[("bot", target_id)] = {
                    "kind": "bot", "team": _integer(raw.get("team")),
                    "alive": bool(raw.get("alive", True))}
        return result

    @staticmethod
    def known_bots(manifest, bot_states):
        states = {_integer(value.get("id")): value for value in (bot_states or [])}
        result = {}
        for raw in manifest or []:
            bot_id = _integer(raw.get("id"))
            if not bot_id:
                continue
            state = states.get(bot_id, {})
            result[bot_id] = {
                "team": _integer(raw.get("team")),
                "alive": bool(state.get("alive", raw.get("health", 1) > 0)),
                "x": _number(state.get("x", raw.get("x"))),
                "z": _number(state.get("z", raw.get("z"))),
            }
        return result

    def clear_observations(self):
        """Discard authority-owned tactical observations after a failover."""
        self._contacts = {1: {}, 2: {}}
        self._affordances = {}
        self._cover_states = {}
        self._cover_failures = {}
        self._cover_reservations = set()
        self._engage_anchors = {}
        self._firing_holds = {}
        self._combat_states = {}
        self._retreat_states = {}

    def _prune_tactical_state(self, bots, known_targets, now):
        live_capture_ids = set(bot['id'] for bot in bots)
        for actor in list(self._capture_arrivals):
            if actor not in live_capture_ids:
                self._capture_arrivals.pop(actor, None)
        live_bots = dict((bot["id"], bot) for bot in bots)
        for actor in set(self._travel_tasks)-set(live_bots):self._travel_tasks.pop(actor,None)
        self._previous_combat.intersection_update(live_bots)
        for actor in set(self._previous_player)-set(live_bots):self._previous_player.pop(actor,None)
        largest_radius = max([math.hypot(3.5, 1.7)] + [
            _number(bot.get('profile', {}).get('parking_radius'), math.hypot(3.5, 1.7))
            for bot in bots])
        for key, claim in list(self._wait_claims.items()):
            owner = live_bots.get(claim['bot_id'])
            stage = self._route_states.get(claim['bot_id'], {})
            departed = (owner is not None and claim.get('departing') and
                math.hypot(_number(owner['state'].get('x'))-claim['point'][0],
                           _number(owner['state'].get('z'))-claim['point'][1]) > claim['radius'] + largest_radius + 2.0)
            changed = stage.get('route_id') != key[1] or stage.get('index') != key[2]
            if owner is None or departed or (changed and not claim.get('departing')):
                self._wait_claims.pop(key, None)
        for states in (self._route_recoveries, self._recovery_route_visits,
                       self._wreck_route_progress, self._wreck_route_avoid):
            for bot_id in list(states):
                if bot_id not in live_bots:
                    del states[bot_id]
        for bot_id in list(self._route_states):
            if bot_id not in live_bots:
                del self._route_states[bot_id]
        for bot_id in list(self._route_history):
            if bot_id not in live_bots:
                del self._route_history[bot_id]
        for bot_id in list(self._route_assignments):
            if bot_id not in live_bots:
                del self._route_assignments[bot_id]
        for bot_id in list(self._target_assignments):
            if bot_id not in live_bots:
                del self._target_assignments[bot_id]
        for states in (self._combat_states, self._retreat_states,
                       self._cover_failures):
            for bot_id in list(states):
                if bot_id not in live_bots:
                    del states[bot_id]
        for bot_id in list(self._engage_anchors):
            if bot_id not in live_bots:
                del self._engage_anchors[bot_id]
        for bot_id in list(self._firing_holds):
            if bot_id not in live_bots:
                del self._firing_holds[bot_id]
        for bot_id in list(self._artillery_anchors):
            if bot_id not in live_bots:
                del self._artillery_anchors[bot_id]
        for bot_id, hit in list(self._recent_hits.items()):
            attacker = (known_targets.get(hit.get("attacker"))
                        if isinstance(hit, dict) else None)
            if (bot_id not in live_bots or not isinstance(hit, dict) or
                    attacker is None or not attacker.get("alive") or
                    _number(now) - _number(hit.get("reported_at")) >
                    RECENT_HIT_SECONDS):
                del self._recent_hits[bot_id]
        for bot_id, report in list(self._affordances.items()):
            bot = live_bots.get(bot_id)
            target_key = report.get("target") if isinstance(report, dict) else None
            target = known_targets.get(target_key)
            contact = (self._contacts.get(_integer(bot.get("team")), {}).get(target_key)
                       if bot is not None else None)
            if (bot is None or target is None or not target.get("alive") or
                    contact is None or not contact.get("visible") or
                    _number(now) - _number(report.get("reported_at")) > COVER_TTL_SECONDS):
                del self._affordances[bot_id]
        for bot_id, state in list(self._cover_states.items()):
            report = self._affordances.get(bot_id)
            if (bot_id not in live_bots or not isinstance(state, dict) or
                    report is None or state.get("target") != report.get("target")):
                del self._cover_states[bot_id]
        for bot_id, failures in list(self._cover_failures.items()):
            if not isinstance(failures, dict):
                del self._cover_failures[bot_id]
                continue
            for candidate_id, until in list(failures.items()):
                if _number(now) >= _number(until):
                    del failures[candidate_id]
            if not failures:
                del self._cover_failures[bot_id]
        for bot_id, state in list(self._combat_states.items()):
            if (not isinstance(state, dict) or
                    known_targets.get(state.get("target")) is None):
                del self._combat_states[bot_id]

    @staticmethod
    def _contact_known_to(contact, bot_id, now=None):
        """Missing metadata is legacy input; an explicit empty lease is not."""
        if "radio_bot_until" not in contact:
            return True
        until = contact["radio_bot_until"].get(bot_id)
        return until is not None and (now is None or until > _number(now))

    @classmethod
    def _contacts_for_bot(cls, bot, contacts, now=None):
        return [contact for contact in contacts
                if cls._contact_known_to(contact, bot["id"], now)]

    def _prune_contacts(self, known_targets, now):
        result = {1: [], 2: []}
        for team in (1, 2):
            stale = []
            for target_key, contact in self._contacts[team].items():
                target = known_targets.get(target_key)
                if target is None or not target.get("alive") or _number(now) - contact["last_seen"] > CONTACT_TTL_SECONDS:
                    stale.append(target_key)
                else:
                    if "radio_bot_until" in contact:
                        contact["radio_bot_until"] = {
                            identity: until for identity, until in
                            contact["radio_bot_until"].items() if until > _number(now)}
                        contact["shootable_by_bot_ids"] = [identity for identity in
                            contact.get("shootable_by_bot_ids", ())
                            if identity in contact["radio_bot_until"]]
                    result[team].append(dict(contact))
            for target_key in stale:
                del self._contacts[team][target_key]
        return result

    @staticmethod
    def _alive_bots(manifest, bot_states, tactics=None):
        states = {_integer(value.get("id")): value for value in (bot_states or [])}
        result = []
        for raw in manifest or []:
            bot_id = _integer(raw.get("id"))
            state = states.get(bot_id, {})
            if not bot_id or not bool(state.get("alive", raw.get("health", 1) > 0)):
                continue
            result.append({
                "id": bot_id,
                "team": _integer(raw.get("team")),
                "slot": _integer(raw.get("slot")),
                "rating": _bot_rating(raw),
                "spg_initial": spg_positions.canonical_plan(
                    raw.get("spg_initial"), vehicle=raw.get("vehicle"), team=raw.get("team"), tactics=tactics),
                "profile": raw.get("profile") if isinstance(raw.get("profile"), dict) else {},
                "route": raw.get("route") if isinstance(raw.get("route"), dict) else {},
                "state": state,
            })
        return result

    @staticmethod
    def _base_defense_eligible(bot):
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        if not bool(state.get("world_pose", True)):
            return False
        critical = state.get("critical")
        critical = critical if isinstance(critical, dict) else {}
        destroyed = set(str(value) for value in
                        (critical.get("destroyed") or ()))
        return not destroyed.intersection((
            "engineHealth", "leftTrackHealth", "rightTrackHealth"))

    @staticmethod
    def _route_donor_eligible(bot):
        """Require current pose and mobility for a route reassignment."""
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        if state.get("world_pose") is not True:
            return False
        critical = state.get("critical")
        critical = critical if isinstance(critical, dict) else {}
        destroyed = set(str(value) for value in
                        (critical.get("destroyed") or ()))
        return not destroyed.intersection((
            "engineHealth", "leftTrackHealth", "rightTrackHealth"))

    @staticmethod
    def _route_line_contributor(bot, contacts):
        """Count mobility, or proved fire from an immobilized line holder."""
        if BotPlanner._route_donor_eligible(bot):
            return True
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        if (state.get("world_pose") is not True or
                not BotPlanner._weapon_ready(bot)):
            return False
        return any(
            contact.get("visible") and
            bot["id"] in (contact.get("shootable_by_bot_ids") or ())
            for contact in (contacts or ()))

    @staticmethod
    def _defense_points(raw, team):
        if not isinstance(raw, dict):
            return []
        values = raw.get(str(team), raw.get(team))
        if not isinstance(values, (list, tuple)):
            return []
        result = []
        for index, value in enumerate(values[:4]):
            if not isinstance(value, dict):
                continue
            point = _point(value)
            result.append({
                "id": str(value.get("id") or "%d:%d" % (team, index)),
                "point": point,
                "radius": max(1.0, _number(value.get('radius'), 50.0)),
            })
        return result

    @staticmethod
    def _defense_eta(bot, point, contacts, deadline):
        state = bot["state"]
        distance = math.hypot(
            point["x"] - _number(state.get("x")),
            point["z"] - _number(state.get("z")))
        speed = _number(bot.get("profile", {}).get("speed"))
        cruise = _clamp(speed * 0.65, 4.0, 22.0)
        eta = 3.0 + distance * 1.30 / cruise
        diversion = 0.0
        for contact in contacts or ():
            if (not contact.get("visible") or
                    bot["id"] not in contact.get(
                        "shootable_by_bot_ids", ())):
                continue
            contact_distance = math.hypot(
                contact["position"]["x"] - _number(state.get("x")),
                contact["position"]["z"] - _number(state.get("z")))
            if contact_distance <= 50.0:
                diversion = max(diversion, 12.0)
            elif contact_distance <= 150.0:
                diversion = max(diversion, 4.0)
        health = max(0.0, _number(state.get("health"), 1.0))
        max_health = max(1.0, _number(state.get("max_health"), 1.0))
        diversion += 6.0 * (1.0 - min(1.0, health / max_health))
        class_tag = str(bot.get("profile", {}).get("class_tag") or "")
        if class_tag == "SPG":
            diversion += 8.0
        elif class_tag == "AT-SPG":
            diversion += 3.0
        if eta <= deadline:
            return (0, eta + diversion, eta, bot["id"])
        return (1, eta - deadline, eta + diversion, bot["id"])

    @staticmethod
    def _defense_contributor_keys(defense, team):
        if not isinstance(defense, dict):
            return set()
        contributor_map = defense.get("contributors")
        contributor_map = (contributor_map
                           if isinstance(contributor_map, dict) else {})
        raw = contributor_map.get(str(team), contributor_map.get(team, ()))
        result = set()
        if not isinstance(raw, (list, tuple)):
            return result
        for value in raw:
            if not isinstance(value, dict):
                continue
            kind = str(value.get("kind") or "")
            vehicle_id = _integer(value.get("id"))
            if kind in ("human", "bot") and vehicle_id > 0:
                result.add((kind, vehicle_id))
        return result

    @staticmethod
    def _defense_retention_key(bot, point, contacts, contributor_keys):
        """Prefer an arrived responder which can stop the current capture."""
        state = bot["state"]
        distance = math.hypot(
            point["x"] - _number(state.get("x")),
            point["z"] - _number(state.get("z")))
        can_engage = False
        if BotPlanner._weapon_can_recover(bot):
            for contact in contacts or ():
                key = (str(contact.get("target_kind") or ""),
                       _integer(contact.get("id")))
                if (key in contributor_keys and contact.get("visible") and
                        bot["id"] in contact.get(
                            "shootable_by_bot_ids", ()) and math.hypot(
                                contact['position']['x'] - _number(state.get('x')),
                                contact['position']['z'] - _number(state.get('z'))) <=
                            BotPlanner._engagement_range(bot, contact)):
                    can_engage = True
                    break
        speed = _number(bot.get("profile", {}).get("speed"))
        cruise = _clamp(speed * 0.65, 4.0, 22.0)
        eta = 3.0 + distance * 1.30 / cruise
        return (0 if can_engage else 1, eta, bot["id"])

    def _update_base_defense(self, bots, contacts, defense, now):
        """Keep a small, stable responder group while an own base is invaded."""
        if not isinstance(defense, dict):
            self._base_defense = {1: {}, 2: {}}
            return {1: {}, 2: {}}
        defense = defense if isinstance(defense, dict) else {}
        states = defense.get("states")
        states = states if isinstance(states, dict) else {}
        bases = defense.get("bases")
        capturing = dict((team, self._defense_contributor_keys(defense, 3 - team))
                         for team in (1, 2))
        live_by_team = dict((team, [
            bot for bot in bots
            if bot["team"] == team and self._base_defense_eligible(bot)
        ]) for team in (1, 2))
        result = {1: {}, 2: {}}
        for team in (1, 2):
            incident = self._base_defense.setdefault(team, {})
            responders = incident.setdefault("responders", {})
            blocked_until = incident.setdefault("blocked_until", {})
            protected = sorted(bot["id"] for bot in bots if bot["team"] == team
                               and ("bot", bot["id"]) in capturing[team])
            previous_protected = (incident.get("capture_protection") or {}).get("protected", [])
            released = sorted(set(protected).intersection(responders))
            history = incident.setdefault("capture_protection_history", [])
            if protected != previous_protected or released:
                history.append(dict(at=_number(now), entered=sorted(set(protected)-set(previous_protected)),
                    exited=sorted(set(previous_protected)-set(protected)), released_responders=released))
                del history[:-16]
            incident["capture_protection"] = dict(
                at=_number(now), base_team=3 - team, protected=protected,
                released_responders=released,
                source="canonical_capture_contributors")
            for bot_id, deadline in list(blocked_until.items()):
                if _number(now) >= deadline:
                    del blocked_until[bot_id]
            live = dict((bot["id"], bot) for bot in live_by_team[team])
            for bot_id in list(responders):
                if bot_id not in live or ("bot", bot_id) in capturing[team]:
                    del responders[bot_id]
            raw_state = states.get(str(team), states.get(team, {}))
            raw_state = raw_state if isinstance(raw_state, dict) else {}
            invaders = max(0, _integer(raw_state.get("invaders")), len(self._defense_contributor_keys(defense, team)))
            points = self._defense_points(bases, team)
            contributor_keys = self._defense_contributor_keys(
                defense, team)
            reserve_limit = (1 if len(live) == 1 else
                             max(0, len(live) - 1))
            if len(responders) > reserve_limit:
                ranked = sorted(
                    responders, key=lambda bot_id:
                    self._defense_retention_key(
                        live[bot_id], responders[bot_id]["point"],
                        self._contacts_for_bot(live[bot_id], contacts.get(team, ()), now),
                        contributor_keys))
                keep = set(ranked[:reserve_limit])
                for bot_id in list(responders):
                    if bot_id not in keep:
                        del responders[bot_id]

            if invaders <= 0:
                incident["release_since"] = None
                if not responders:
                    incident["clear_since"] = None
                    incident["need"] = 0
                    continue
                clear_since = incident.get("clear_since")
                if clear_since is None:
                    incident["clear_since"] = _number(now)
                elif _number(now) - _number(clear_since) >= 30.0:
                    responders.clear()
                    incident["clear_since"] = None
                    incident["need"] = 0
                    continue
            else:
                incident["clear_since"] = None
                # A nearest responder can be wedged among spawn props. Keep
                # arrived defenders, but replace a travelling tank which has
                # made no real approach for ten seconds when a backup exists.
                for bot_id, record in list(responders.items()):
                    current_base = next((value for value in points
                        if value['id'] == record.get('base_id')), None)
                    if current_base is not None:
                        record.update(point=dict(current_base['point']), radius=current_base['radius'])
                    state = live[bot_id]["state"]
                    point = record["point"]
                    distance = math.hypot(
                        point["x"] - _number(state.get("x")),
                        point["z"] - _number(state.get("z")))
                    if ("best_distance" not in record or
                            distance + 1.0 <= record["best_distance"]):
                        record["best_distance"] = distance
                        record["last_progress_at"] = _number(now)
                    if distance <= record.get('radius', 50.0):
                        record['last_progress_at'] = _number(now)
                    combat_progress = self._defense_combat_progress(
                        live[bot_id], record, self._contacts_for_bot(
                            live[bot_id], contacts.get(team, ()), now),
                        contributor_keys, now)
                    if (self._travel_tasks.get(bot_id) or {}).get('kind')=='defense':
                        pose=(_number(state.get('x')),_number(state.get('z')))
                        prior=record.setdefault('task_pose',pose)
                        if math.hypot(pose[0]-prior[0],pose[1]-prior[1])>=1.:
                            record['last_progress_at']=_number(now);record['task_pose']=pose
                    if combat_progress:
                        record['last_progress_at'] = _number(now)
                    backups = [value for value in live
                               if value not in responders and
                               value not in blocked_until and
                               ("bot", value) not in capturing[team]]
                    if (distance > record.get('radius', 50.0) and backups and
                            _number(now) - record["last_progress_at"] >= 10.0):
                        blocked_until[bot_id] = _number(now) + 15.0
                        del responders[bot_id]
                desired = min(MAX_BASE_DEFENDERS, max(1, invaders))
                if len(live) > 1:
                    desired = min(desired, len(live) - 1)
                elif live:
                    desired = 1
                else:
                    desired = 0
                previous_need = max(
                    0, _integer(incident.get("need")))
                if desired >= previous_need:
                    incident["need"] = desired
                    incident["release_since"] = None
                else:
                    release_since = incident.get("release_since")
                    if release_since is None:
                        incident["release_since"] = _number(now)
                    elif (_number(now) - _number(release_since) >=
                          BASE_DEFENSE_RELEASE_SECONDS):
                        incident["need"] = max(
                            desired, previous_need - 1)
                        incident["release_since"] = _number(now)

                keep_limit = min(
                    _integer(incident.get("need")), reserve_limit)
                if len(responders) > keep_limit:
                    ranked = sorted(
                        responders, key=lambda bot_id:
                        self._defense_retention_key(
                            live[bot_id], responders[bot_id]["point"],
                            self._contacts_for_bot(live[bot_id], contacts.get(team, ()), now),
                        contributor_keys))
                    keep = set(ranked[:keep_limit])
                    for bot_id in list(responders):
                        if bot_id not in keep:
                            del responders[bot_id]

                point_by_id = dict((value["id"], value) for value in points)
                for bot_id, record in list(responders.items()):
                    if record.get("base_id") in point_by_id:
                        continue
                    if not points:
                        del responders[bot_id]
                        continue
                    bot = live[bot_id]
                    selected = min(points, key=lambda value: (
                        math.hypot(
                            value["point"]["x"] - _number(
                                bot["state"].get("x")),
                            value["point"]["z"] - _number(
                                bot["state"].get("z"))),
                        value["id"]))
                    responders[bot_id] = {
                        "base_id": selected["id"],
                        "point": dict(selected["point"]),
                        "radius": selected['radius'],
                    }

                missing = max(0, min(_integer(incident.get("need")),
                                     reserve_limit) - len(responders))
                if missing and points:
                    deadline = max(
                        0.0, _number(raw_state.get("time_left")) - 2.0)
                    candidates = []
                    for bot in live.values():
                        if (bot["id"] in responders or
                                bot["id"] in blocked_until or
                                ("bot", bot["id"]) in capturing[team]):
                            continue
                        selected = min(points, key=lambda value: (
                            math.hypot(
                                value["point"]["x"] - _number(
                                    bot["state"].get("x")),
                                value["point"]["z"] - _number(
                                    bot["state"].get("z"))),
                            value["id"]))
                        key = self._defense_eta(
                            bot, selected["point"], self._contacts_for_bot(
                                bot, contacts.get(team, ()), now), deadline)
                        candidates.append((key, bot["id"], selected))
                    for unused_key, bot_id, selected in sorted(
                            candidates)[:missing]:
                        responders[bot_id] = {
                            "base_id": selected["id"],
                            "point": dict(selected["point"]),
                            "radius": selected['radius'],
                        }
            result[team] = dict(responders)
        return result

    def _defense_combat_progress(self, bot, record, contacts, contributor_keys, now):
        """Count executed fire/reload/aim work against a reachable invasion.

        Merely possessing a target or a positive lane is not progress: a wedged
        responder must still expire when neither its body nor gun is working.
        """
        state = bot['state']
        reachable = [contact for contact in contacts if
            (contact.get('target_kind'), contact['id']) in contributor_keys and
            contact.get('visible') and math.hypot(
                contact['position']['x'] - _number(state.get('x')),
                contact['position']['z'] - _number(state.get('z'))) <=
            self._engagement_range(bot, contact)]
        sequence = _integer(state.get('fire_seq'))
        previous_sequence = record.get('observed_fire_seq', sequence)
        record['observed_fire_seq'] = sequence
        reason = 'no_reachable_capturer'
        progressed = False
        if reachable:
            reason = 'no_executed_combat_progress'
            if sequence > previous_sequence:
                record['defense_shot_seq'] = sequence
                record['reload_best'] = _number(state.get('reload_time'))
                reason, progressed = 'shot_advanced', True
            elif (record.get('defense_shot_seq') == sequence and
                  0.0 < _number(state.get('reload_time')) <
                  record.get('reload_best', 0.0)):
                record['reload_best'] = _number(state.get('reload_time'))
                reason, progressed = 'reload_advanced', True
            key = (state.get('aim_feedback_kind'), state.get('aim_feedback_id'))
            if any((contact.get('target_kind'), contact['id']) == key and
                   bot['id'] in contact.get('shootable_by_bot_ids', ()) for contact in reachable):
                error = _number(state.get('aim_feedback_error'))
                old = record.get('defense_aim')
                if old is None or old[0] != key or error + math.radians(1.0) <= old[1]:
                    record['defense_aim'] = (key, error)
                    reason, progressed = 'capturer_aim_advanced', True
        record['combat_progress'] = dict(at=now, reason=reason,
            progressed=progressed, reachable=[(c.get('target_kind'), c['id']) for c in reachable],
            fire_seq=sequence, previous_fire_seq=previous_sequence,
            reload_time=state.get('reload_time'), aim_target=(
                state.get('aim_feedback_kind'), state.get('aim_feedback_id')),
            aim_error=state.get('aim_feedback_error'))
        return progressed

    def _apply_base_defense_order(self, order, bot, base):
        self._engage_anchors.pop(bot["id"], None)
        self._cover_states.pop(bot["id"], None)
        order["combat_mode"] = "base_defense"
        order["defense_base_id"] = str(base["base_id"])
        order["move_position"] = dict(base["point"])
        order["throttle_override"] = None
        order["route_join"] = False
        if order.get("target_id") is None:
            order["face_position"] = dict(base["point"])
        arrived = self._inside_base(bot, base)
        order['tactical_evidence']['base_arrival'] = dict(
            kind='defense', base_id=base['base_id'], point=dict(base['point']),
            radius=base.get('radius', 50.0), arrived=arrived)
        if arrived:
            order['move_position'] = _point(bot['state'])
            order['throttle_override'] = 0.0
            if order.get('target_id') is not None:
                order['combat_mode'] = 'engage'
                self._apply_stationary_angling(order, bot, bot['profile'], order['personality'])
            else:
                order['face_position'] = _point(bot['state'])

    @staticmethod
    def _inside_base(bot, target):
        pose = bot['state']
        return bool(pose.get('world_pose') and not pose.get('airborne') and
            not pose.get('route_wreck_blocked') and math.hypot(
                target['point']['x'] - _number(pose.get('x')),
                target['point']['z'] - _number(pose.get('z'))) <= target.get('radius', 50.0))

    @staticmethod
    def _capture_target(defense, team):
        """Return the exact opposing CTF circle supplied by BattleState."""
        if not isinstance(defense, dict):
            return None
        bases = defense.get("capture_bases")
        if not isinstance(bases, dict):
            return None
        enemy_team = 3 - int(team)
        values = bases.get(str(enemy_team), bases.get(enemy_team))
        if not isinstance(values, (list, tuple)):
            return None
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                continue
            try:
                x = float(raw["x"])
                z = float(raw["z"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(x) or not math.isfinite(z):
                continue
            return {
                "id": str(raw.get("id") or "%d:%d" %
                          (enemy_team, index)),
                "point": _point(raw),
                "radius": max(1.0, _number(raw.get("radius"), 50.0)),
            }
        return None

    def _protect_capture_order(self, order, bot, target):
        """Circle occupancy belongs to every arrival, not a three-Bot squad."""
        actor = bot['id']
        if (target is None or actor in self._travel_tasks or
                actor in self._route_recoveries or order.get('team_command') or
                order.get('defense_base_id')):
            self._capture_arrivals.pop(actor, None)
            return
        area = dict(id=target['id'], point=dict(target['point']), radius=target['radius'])
        previous = self._capture_arrivals.get(actor)
        if previous is not None and previous != area:
            self._capture_arrivals.pop(actor, None)
        pose = bot['state']
        if (not pose.get('world_pose') or pose.get('airborne') or
                pose.get('route_wreck_blocked')):
            return
        if pose.get('world_pose') and not pose.get('airborne') and capture_orders.inside(pose, area):
            self._capture_arrivals[actor] = area
        if actor not in self._capture_arrivals:
            return
        order['capture_area'] = area
        previous_destination = order.get('move_position')
        guarded = capture_orders.constrain(order, pose)
        order.update(guarded)
        order['tactical_evidence']['capture_hold'] = dict(
            base_id=area['id'], inside=capture_orders.inside(pose, area),
            constrained=guarded.get('move_position') != previous_destination,
            source='actual_circle_arrival')

    def _apply_base_capture_order(self, order, bot, target):
        """Send an unengaged vehicle to the opposing CTF capture circle."""
        self._engage_anchors.pop(bot["id"], None)
        self._cover_states.pop(bot["id"], None)
        point = dict(target["point"])
        order["combat_mode"] = "base_capture"
        order["capture_base_id"] = str(target["id"])
        order["aim_position"] = point
        order["face_position"] = point
        order["move_position"] = point
        order["throttle_override"] = None
        order["route_join"] = False

    def _route_arrival_radius(self, route, team):
        # A one-point automatic tactical goal is distinct from an authored disk.
        authored = bot_tactics.route_config(self.tactics, self.tactics_map,
                                            route.get('id'), team)
        return ROUTE_ARRIVAL_RADIUS if authored is not None or len(route.get('waypoints') or ()) > 1 else 1.5

    def _capture_staged(self, bot, route_index, target=None):
        """Determine completion of the existing authored capture corridor."""
        if bot['id'] in self._route_recoveries:
            return False
        assignment = self._route_assignments.get(bot["id"])
        route = assignment.get("route") if isinstance(
            assignment, dict) else None
        if not isinstance(route, dict):
            route = bot.get("route") if isinstance(
                bot.get("route"), dict) else {}
        waypoints = route.get("waypoints")
        if not isinstance(waypoints, list) or not waypoints:
            # Legacy manifests without a usable corridor retain the direct
            # capture behaviour instead of leaving the vehicle stranded.
            return True
        if target is not None:
            if self._inside_base(bot, target):return True
            if route_index != len(waypoints)-1:
                return False
            if (not bot['state'].get('world_pose') or bot['state'].get('airborne') or
                    bot['state'].get('route_wreck_blocked')):
                return False
            final = _point(waypoints[-1])
            final_inside = math.hypot(final['x']-target['point']['x'],
                                     final['z']-target['point']['z']) <= target['radius']
            if final_inside:
                return self._inside_base(bot, target)
            state = self._route_states.get(bot['id'], {})
            if (state.get('completed_terminal') == final or
                    (state.get('terminal_crossing') or {}).get('point') == final):
                return True
            radius = self._route_arrival_radius(route, bot['team'])
            arrived = math.hypot(final['x']-_number(bot['state'].get('x')),
                                 final['z']-_number(bot['state'].get('z'))) <= radius
            if arrived:
                state['completed_terminal'] = final
            return arrived
        return False

    def _prioritize_base_invaders(self, team, bots, contacts, assignments,
                                  defenders, defense, now=None):
        if not defenders or not isinstance(defense, dict):
            return assignments
        contributor_keys = self._defense_contributor_keys(defense, team)
        if not contributor_keys:
            return assignments
        result = dict(assignments)
        bot_by_id = dict((bot["id"], bot) for bot in bots)
        reservations = {}
        for bot_id in sorted(defenders):
            bot = bot_by_id.get(bot_id)
            if bot is None:
                continue
            if not self._inside_base(bot, defenders[bot_id]):continue
            bx = _number(bot["state"].get("x"))
            bz = _number(bot["state"].get("z"))
            choices = []
            current = result.get(bot_id)
            current_key = ((current.get('target_kind'), current['id'])
                           if current is not None else None)
            hit = self._recent_hit(bot_id, now) if now is not None else None
            lease = self._target_assignments.get(bot_id) or {}
            reads = self._target_decisions.get(bot_id, {}).get('target_capabilities', {})
            for contact in self._contacts_for_bot(bot, contacts, now):
                key = (str(contact.get("target_kind") or ""),
                       _integer(contact.get("id")))
                if (key not in contributor_keys or
                        not contact.get("visible") or
                        bot_id not in contact.get(
                            "shootable_by_bot_ids", ())):
                    continue
                distance = math.hypot(
                    contact["position"]["x"] - bx,
                    contact["position"]["z"] - bz)
                if distance > self._engagement_range(bot, contact):
                    continue
                health_fraction = (
                    _number(contact.get("health"), 1.0) /
                    max(1.0, _number(contact.get("max_health"), 1.0)))
                capture_rows = (defense.get('contributors', {}).get(str(team)) or ())
                capture_points = max([float(row.get('points', 0)) for row in capture_rows
                    if (row.get('kind'), row.get('id')) == key] or [0.])
                scores=dict((tuple(row['target']),row['score']) for row in self._target_decisions.get(bot_id,{}).get('candidates',()) if 'score' in row)
                choices.append((
                    -capture_points, scores.get(key,distance), reservations.get(key, 0),
                    0 if key == current_key else 1, health_fraction, distance,
                    key[0], key[1], contact))
            if not choices:
                self._target_decisions.setdefault(bot_id, {})['base_priority'] = dict(
                    reason='no_proved_capturer_lane', contributors=sorted(contributor_keys),
                    selected=current_key)
                continue
            selected = min(choices)
            contact = selected[-1]
            key = (str(contact.get("target_kind") or ""),
                   _integer(contact.get("id")))
            reservations[key] = reservations.get(key, 0) + 1
            result[bot_id] = contact
            if lease.get('target') != key:
                self._target_assignments[bot_id] = self._new_target_lease(bot, key, now)
            decision = self._target_decisions.setdefault(bot_id, {})
            decision.update(selected=key, outcome='base_capturer',
                lease_after=dict(self._target_assignments[bot_id]),
                base_priority=dict(reason='proved_capturer_lane',
                    contributors=sorted(contributor_keys), selected=key))
        return result

    @staticmethod
    def _desired_focus(contact):
        remaining = max(0, _integer(contact.get("health")))
        if remaining >= 1800:
            return 3
        if remaining >= 900 or contact.get("class_tag") in ("heavyTank", "AT-SPG"):
            return 2
        return 1

    @staticmethod
    def _focus_limit(contact, distance):
        """Let nearby tanks defend themselves without pulling a whole flank."""
        limit = BotPlanner._desired_focus(contact)
        if distance <= CLOSE_THREAT_DISTANCE:
            return max(limit, CLOSE_THREAT_FOCUS_LIMIT)
        return limit

    @staticmethod
    def _selected_shell_damage(bot, contact):
        """Return nominal damage for the descriptor-backed selected round."""
        profile = bot.get("profile") if isinstance(
            bot.get("profile"), dict) else {}
        shells = profile.get("shells")
        if not isinstance(shells, list) or not shells:
            return None
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        shell_index = BotPlanner._shell_index(
            profile, contact, BotPlanner._personality(bot["id"]), state)
        for shell in shells:
            if _integer(shell.get("index"), -1) != shell_index:
                continue
            damage = _number(shell.get("damage"), -1.0)
            return damage if damage > 0.0 else None
        return None

    @staticmethod
    def _reserve_focus(reservations, key, bot, contact):
        reservation = reservations.setdefault(key, {
            "count": 0,
            "nominal_damage": 0.0,
            "smallest_shot": None,
            "unknown_damage": False,
        })
        damage = BotPlanner._selected_shell_damage(bot, contact)
        reservation["count"] += 1
        if damage is None:
            reservation["unknown_damage"] = True
            return
        reservation["nominal_damage"] += damage
        smallest = reservation.get("smallest_shot")
        reservation["smallest_shot"] = (
            damage if smallest is None else min(_number(smallest), damage))

    @staticmethod
    def _focus_saturated(reservations, key, contact, distance):
        reservation = reservations.get(key)
        if not isinstance(reservation, dict):
            return False
        count = max(0, _integer(reservation.get("count")))
        if distance <= CLOSE_THREAT_DISTANCE:
            return count >= BotPlanner._focus_limit(contact, distance)
        if reservation.get("unknown_damage"):
            return count >= BotPlanner._focus_limit(contact, distance)
        smallest = reservation.get("smallest_shot")
        if smallest is None or count < 2:
            return False
        # Descriptor damage is nominal and the live roll is random. Reserve
        # one complete additional shot instead of treating the nominal sum as
        # a guaranteed kill. Projectile physics remains owned by the worker.
        covered_damage = (_number(reservation.get("nominal_damage")) -
                          _number(smallest))
        return covered_damage >= max(1.0, _number(contact.get("health"), 1.0))

    @staticmethod
    def _engagement_range(bot, contact):
        """Keep nearby combat primary without pulling an entire team off-route."""
        profile = bot.get("profile") if isinstance(bot.get("profile"), dict) else {}
        roles = profile.get("roles") if isinstance(profile.get("roles"), dict) else {}
        desired = max(40.0, _number(profile.get("desired_range"), 180.0))
        if str(profile.get("class_tag") or "") == "SPG":
            # Artillery may track received contacts beyond the ordinary
            # direct-fire envelope. Tracking never substitutes for the
            # worker's pitch-valid, obstacle-free launch proof.
            return max(
                desired,
                min(2500.0, _number(profile.get("fire_range"), 1250.0)))
        mobility = max(_number(roles.get("scout")),
                       _number(roles.get("flanker")))
        if contact.get("visible"):
            distance = max(340.0, min(560.0,
                                     desired * 2.0 + mobility * 300.0))
        else:
            distance = max(240.0, min(420.0,
                                     desired * 1.5 + mobility * 210.0))
        return distance

    def _recent_hit(self, bot_id, now):
        hit = self._recent_hits.get(_integer(bot_id))
        if not isinstance(hit, dict):
            return None
        if (_number(now) - _number(hit.get("reported_at")) >
                RECENT_HIT_SECONDS):
            self._recent_hits.pop(_integer(bot_id), None)
            return None
        return hit

    @staticmethod
    def _weapon_can_recover(bot):
        """Return whether current inventory can eventually supply a shot."""
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        remaining = state.get("ammo_remaining")
        return bool(
            isinstance(remaining, (list, tuple)) and
            sum(max(0, _integer(value)) for value in remaining) > 0)

    @staticmethod
    def _weapon_ready(bot):
        """Return whether this Bot can turn a firing lane into a current shot."""
        if not BotPlanner._weapon_can_recover(bot):
            return False
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        critical = state.get("critical")
        critical = critical if isinstance(critical, dict) else {}
        if "gunHealth" in set(str(value) for value in
                              (critical.get("destroyed") or ())):
            return False
        remaining = state.get("ammo_remaining")
        if isinstance(remaining, (list, tuple)):
            loaded = _integer(state.get("shell_index"), -1)
            if (loaded < 0 or loaded >= len(remaining) or
                    _integer(remaining[loaded]) <= 0):
                return False

        # A burst which is already in flight owns its remaining rounds even
        # though the ordinary loaded-shell snapshot is reload-pending.
        if state.get("burst_active"):
            return True
        if state.get("ammo_reload_pending") is True:
            return False
        if "clip" in state and _integer(state.get("clip")) <= 0:
            return False
        if ("reload_time" in state and
                _number(state.get("reload_time")) > 0.0):
            return False
        return True

    @staticmethod
    def _magazine_has_followup(bot):
        """Return whether an exposed magazine or burst still has a next shot."""
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        if state.get("burst_active"):
            return True
        if (_integer(state.get("clip_size"), 1) <= 1 or
                _integer(state.get("clip")) <= 0):
            return False
        remaining = state.get("ammo_remaining")
        return bool(
            isinstance(remaining, (list, tuple)) and
            sum(max(0, _integer(value)) for value in remaining) > 0)

    def _recent_threat_contact(self, bot, contacts, now):
        hit = self._recent_hit(bot["id"], now)
        if hit is None:
            return None
        key = hit.get("attacker")
        for contact in contacts:
            if (str(contact.get("target_kind") or ""),
                    _integer(contact.get("id"))) == key:
                return contact
        return None

    @staticmethod
    def _ally_support_score(bot, team_bots, focus):
        """Return nearby support which can currently fire on this contact."""
        bx = _number(bot["state"].get("x"))
        bz = _number(bot["state"].get("z"))
        tx = _number(focus.get("position", {}).get("x"))
        tz = _number(focus.get("position", {}).get("z"))
        shooters = set(_integer(value) for value in
                       (focus.get("shootable_by_bot_ids") or ()))
        score = 0.0
        for ally in team_bots or ():
            if (ally["id"] == bot["id"] or ally["id"] not in shooters or
                    not BotPlanner._weapon_ready(ally)):
                continue
            state = ally.get("state") if isinstance(
                ally.get("state"), dict) else {}
            health_fraction = (_number(state.get("health"), 1.0) /
                               max(1.0, _number(
                                   state.get("max_health"), 1.0)))
            bot_distance = math.hypot(
                _number(state.get("x")) - bx,
                _number(state.get("z")) - bz)
            target_distance = math.hypot(
                _number(state.get("x")) - tx,
                _number(state.get("z")) - tz)
            score += health_fraction * max(
                0.0, 1.0 - bot_distance / 130.0) * 0.55
            score += health_fraction * max(
                0.0, 1.0 - target_distance / 220.0) * 0.35
        return round(_clamp(score, 0.0, 1.0), 3)

    @staticmethod
    def _crossfire_risk(bot, contacts):
        """Estimate exposure only from explicit enemy-to-bot firing lanes."""
        bx = _number(bot["state"].get("x"))
        bz = _number(bot["state"].get("z"))
        bearings = []
        for contact in contacts:
            if (not contact.get("visible") or
                    bot["id"] not in (
                        contact.get("threatened_bot_ids", ()) or ())):
                continue
            dx = _number(contact.get("position", {}).get("x")) - bx
            dz = _number(contact.get("position", {}).get("z")) - bz
            distance = math.hypot(dx, dz)
            if distance <= 1.0 or distance > CROSSFIRE_MAX_DISTANCE:
                continue
            bearings.append(math.atan2(dx, dz))
        if len(bearings) < 2:
            # Unknown and incomplete pair sampling is not evidence of safety.
            return None
        best = 0.0
        for first_index, first in enumerate(bearings):
            for second in bearings[first_index + 1:]:
                separation = abs((first - second + math.pi) %
                                 (math.pi * 2.0) - math.pi)
                if separation < CROSSFIRE_MIN_ANGLE:
                    continue
                best = max(best, _clamp(
                    (separation - CROSSFIRE_MIN_ANGLE) /
                    math.radians(90.0), 0.0, 1.0))
        return round(best, 3)

    def _previous_target_order(self, bot_id, focus):
        target_key = (focus.get("target_kind"), focus.get("id"))
        orders = ((self._last_orders or {}).get("orders") or ())
        for order in orders:
            if (_integer(order.get("id")) == _integer(bot_id) and
                    (order.get("target_kind"), order.get("target_id")) ==
                    target_key):
                return order
        return None

    @staticmethod
    def _combat_approach(order, position, reason):
        """A lost firing lane changes combat movement, not objective ownership."""
        order.update(combat_mode='advance_contact', move_position=dict(position),
                     throttle_override=None, fire_allowed=False)
        order.setdefault('tactical_evidence', {})['combat_handoff'] = dict(
            owner='combat', reason=reason, destination=dict(position))

    def _apply_leased_movement_order(self, order, bot, focus):
        """Debounce movement while the current lane generation catches up."""
        previous = self._previous_target_order(bot["id"], focus)
        if not isinstance(previous, dict) or previous.get(
                "combat_mode") not in (
                "advance", "advance_contact", "support_hold", "engage", "flank",
                "route", "take_cover", "cover_hold", "cover_peek", "cover_return"):
            return False
        if (previous.get("combat_mode") == "route" and
                not (self._firing_holds.get(bot["id"]) or {}).get("destination")):
            return False
        if (previous.get('combat_mode') in ('engage', 'support_hold') and
                previous.get('throttle_override') == 0.0):
            if bot['id'] in focus.get('pending_lane_by_bot_ids', ()):
                # The authority retained a positive ray while refreshing it.
                # Keep this stationary owner without authorizing a stale shot.
                order.setdefault('tactical_evidence', {})['blocked_hold_handoff'] = dict(
                    reason='lane_refresh_pending', previous_mode=previous['combat_mode'])
            else:
                # Release only the stationary hold. The caller keeps the combat
                # objective and lets the existing navigator seek an approach.
                order.setdefault('tactical_evidence', {})['blocked_hold_handoff'] = dict(
                    reason='stationary_lane_lost', previous_mode=previous['combat_mode'])
                return False
        if previous.get('combat_mode') == 'flank':
            state = bot['state']
            point = _point(previous.get('move_position'))
            if math.hypot(point['x'] - _number(state.get('x')),
                          point['z'] - _number(state.get('z'))) <= 1.5:
                # The lane lease may preserve unfinished travel, not a completed
                # flank with no shot. Yield to the caller's existing route path.
                order.setdefault('tactical_evidence', {})['flank_handoff'] = dict(
                    reason='completed_flank_without_lane', point=point)
                return False
        for name in (
                "combat_mode", "move_position", "face_position",
                "throttle_override", "cover_id", "hull_angle_degrees",
                "stable_hull_face"):
            if name in previous:
                if name == "move_position" and previous.get("combat_mode") == "advance":
                    continue
                value = previous[name]
                order[name] = dict(value) if isinstance(value, dict) else value
        if previous.get("combat_mode") == "advance_contact":
            order["move_position"] = dict(focus["position"])
        # The movement lease is deliberately not a launch authorization.
        order["fire_allowed"] = False
        return True

    def _stable_range_mode(self, bot, focus, distance, far_limit,
                           far_mode, fire_range, now):
        """Return one range mode with a small Schmitt band and dwell lease."""
        bot_id = bot["id"]
        target_key = (focus.get("target_kind"), focus["id"])
        hysteresis = _clamp(
            far_limit * COMBAT_RANGE_HYSTERESIS_FRACTION,
            COMBAT_RANGE_HYSTERESIS_MIN, COMBAT_RANGE_HYSTERESIS_MAX)
        if far_mode == "support_hold" and distance > fire_range:
            far_mode = "advance_contact"
        preferred = far_mode if distance > far_limit else "engage"
        current = self._combat_states.get(bot_id)
        if not isinstance(current, dict) or current.get("target") != target_key:
            current = {
                "target": target_key,
                "mode": preferred,
                "since": _number(now),
            }
            self._combat_states[bot_id] = current
            return preferred
        previous = current.get("mode")
        if previous == "support_hold" and distance > fire_range:
            previous = "advance_contact"
        if previous == "engage" and distance <= min(
                fire_range, far_limit + hysteresis):
            preferred = "engage"
        elif (previous in ("support_hold", "advance_contact") and
              distance >= far_limit - hysteresis):
            preferred = previous
        if (_number(now) - _number(current.get("since")) <
                COMBAT_MODE_DWELL_SECONDS and
                abs(distance - far_limit) <= hysteresis):
            if (previous != "support_hold" or distance <= fire_range):
                preferred = previous
        if preferred != current.get("mode"):
            current["mode"] = preferred
            current["since"] = _number(now)
        return preferred

    def _apply_retreat_order(self, order, bot, retreat_point, face_point,
                             now, moving_mode, hold_mode):
        """Drive one withdrawal to an explicit arrival or timeout terminal."""
        bot_id = bot["id"]
        target = _point(retreat_point)
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        retreat = self._retreat_states.get(bot_id)
        if (isinstance(retreat, dict) and
                retreat.get("moving_mode") == moving_mode and
                isinstance(retreat.get("target_point"), dict)):
            # Route progress can change while the Bot is withdrawing.  Freeze
            # the first graph-safe endpoint so the command cannot reverse on
            # the next one-hertz planning tick.
            target = dict(retreat["target_point"])
        bx = _number(state.get("x"))
        bz = _number(state.get("z"))
        distance = math.hypot(target["x"] - bx, target["z"] - bz)
        face = _point(face_point)
        fire_range = _number(bot.get("profile", {}).get("fire_range"))
        local_threat = bool(order.get("target_id") is not None and
            (fire_range <= 0.0 or
             math.hypot(face["x"] - bx, face["z"] - bz) <= fire_range * 1.15))
        local_threat = local_threat or self._recent_hit(bot_id, now) is not None
        if (not isinstance(retreat, dict) or
                retreat.get("moving_mode") != moving_mode):
            retreat = {
                "moving_mode": moving_mode,
                "target_point": dict(target),
                "phase": "withdraw",
                "best_distance": distance,
                "last_progress_at": _number(now),
                "face": dict(face),
                "hold_mode": hold_mode,
            }
            self._retreat_states[bot_id] = retreat
        elif (distance + RETREAT_PROGRESS_EPSILON <
              _number(retreat.get("best_distance"), distance)):
            retreat["best_distance"] = distance
            retreat["last_progress_at"] = _number(now)
        if retreat.get("phase") == "resume":
            if not local_threat:
                return order
            self._retreat_states.pop(bot_id, None)
            return self._apply_retreat_order(
                order, bot, retreat_point, face_point, now, moving_mode, hold_mode)
        if retreat.get("phase") != "hold" and (
                distance <= RETREAT_ARRIVAL_RADIUS or
                _number(now) - _number(retreat.get("last_progress_at")) >=
                RETREAT_PROGRESS_TIMEOUT_SECONDS):
            retreat["phase"] = "hold"
            retreat["hold_since"] = _number(now)
            retreat["anchor"] = (
                target if distance <= RETREAT_ARRIVAL_RADIUS else
                _point(state))
            retreat["face"] = _point(face_point)
        if retreat.get("phase") == "hold":
            # A finished withdrawal is a defensive pause, not a permanent
            # battle-long parking order after the local threat has gone.
            if (not local_threat and _number(now) -
                    _number(retreat.get("hold_since"), now) >= RETREAT_DEFENSIVE_PAUSE_SECONDS):
                retreat["phase"] = "resume"
                return order
            # Keep the established combat mode so the worker continues its
            # normal cover-refresh eligibility.  The explicit phase marks
            # this as a terminal defensive hold rather than an endless drive.
            order["combat_mode"] = moving_mode
            order["tactical_phase"] = hold_mode
            order["move_position"] = dict(retreat["anchor"])
            order["face_position"] = dict(retreat["face"])
            order["throttle_override"] = 0.0
            order["stable_hull_face"] = True
        else:
            order["combat_mode"] = moving_mode
            order["tactical_phase"] = "withdraw"
            order["move_position"] = target
            order["throttle_override"] = None
            order['face_position'] = dict(retreat['face'])
        return order

    @staticmethod
    def _new_target_lease(bot, key, now):
        return dict(target=key, until=_number(now) + TARGET_LEASE_SECONDS,
                    aim_start_seq=_integer(bot['state'].get('fire_seq')),
                    aim_progress_at=_number(now), aim_best_error=None)

    @staticmethod
    def _target_aim_in_progress(bot, lease, now):
        """Protect one executed aim until a shot or bounded lack of progress."""
        state = bot['state']
        key = (state.get('aim_feedback_kind'), state.get('aim_feedback_id'))
        if key != lease.get('target') or _integer(state.get('fire_seq')) > lease.get(
                'aim_start_seq', _integer(state.get('fire_seq'))):
            return False
        error = _number(state.get('aim_feedback_error'))
        best = lease.get('aim_best_error')
        if best is None or error + math.radians(1.0) <= best:
            lease['aim_best_error'] = error
            lease['aim_progress_at'] = _number(now)
        lease['aim_aligned'] = bool(state.get('aim_feedback_aligned'))
        return _number(now) - _number(lease.get('aim_progress_at')) < TARGET_AIM_NO_PROGRESS_SECONDS

    def _assign_targets(self, bots, contacts, now):
        """Assign only locally shootable contacts, with a shared focus budget.

        Team spotting is shared intelligence, not proof that every tank has a
        firing lane. The authority client reports the bot ids whose own static
        ray succeeded, so a shared red dot cannot pull the rest of a flank off
        its route.

        Which of those lanes a Bot prefers is a difficulty ladder: see the
        rungs and their onsets below and in ``bot_gunnery``. The focus cap
        does not read the ladder, so a human contact is reserved exactly like
        a Bot contact however hard the roster is.
        """
        if not bots or not contacts:
            for bot in bots:
                self._target_decisions[bot['id']] = dict(
                    at=now, candidates=[], selected=None, outcome='no_team_contacts')
            return {}
        reservations = {}
        assigned = {}
        candidates = []
        by_bot = {}
        tactics = {}
        for bot in bots:
            observation = dict(at=now, candidates=[], selected=None,
                previous=dict(self._target_assignments.get(bot['id']) or {}),
                outcome='evaluating', focus_refusals=[],
                weapon=dict((key, list(value) if isinstance(value, (list, tuple)) else value)
                    for key, value in ((key, bot['state'].get(key)) for key in (
                        'shell_index', 'ammo_remaining', 'ammo_reload_pending',
                        'clip', 'clip_size', 'reload_time', 'burst_active'))),
                destroyed=list((bot['state'].get('critical') if isinstance(
                    bot['state'].get('critical'), dict) else {}).get('destroyed') or ()))
            self._target_decisions[bot['id']] = observation
            bx = _number(bot["state"].get("x"))
            bz = _number(bot["state"].get("z"))
            # Choosing an enemy is a ladder of separate competences, not one
            # decision: preferring the nearer contact, finishing the most
            # nearly dead one, turning on whoever just hit you, and going for
            # the human instead of a Bot each have their own onset on the
            # rating axis, so a stronger roster reaches for strictly more of
            # them instead of only hesitating less often. The occasion is the
            # target lease this assignment already runs on, not the wall
            # clock: a Bot that re-decided on a timer would change its mind
            # mid-lease, and every candidate's score would move at once for
            # no reason the enemy gave it. Decided once per call and reused
            # below, so a score and its override cannot disagree. Gun reach
            # and the point-blank override survive at every rating: neither
            # is a tactic.
            lease = self._target_assignments.get(bot["id"])
            occasion = (round(_number(lease.get("until")), 3)
                        if isinstance(lease, dict) else None)
            reads = dict(
                (capability, self._capable(bot, capability, occasion))
                for capability in bot_gunnery.TARGET_CAPABILITIES)
            tactics[bot["id"]] = reads
            observation['target_capabilities'] = dict(reads)
            known = set(id(contact) for contact in self._contacts_for_bot(bot, contacts, now))
            for contact in contacts:
                row = dict(target=(contact.get('target_kind'), contact['id']),
                    visible=bool(contact.get('visible')),
                    local_lane=bot['id'] in contact.get('shootable_by_bot_ids', ()),
                    last_seen=contact.get('last_seen'),
                    radio_until=(contact.get('radio_bot_until') or {}).get(bot['id']),
                    position=dict(contact.get('position') or {}),
                    known=id(contact) in known, reason='not_known_to_bot')
                observation['candidates'].append(row)
                if not row['known']:
                    continue
                # A curved artillery lane is tied to the physical muzzle
                # pose. Requiring that lane before selecting a target creates
                # a cycle: acquire -> turn hull -> invalidate lane -> lose the
                # two-second lease -> face the base -> acquire again. Tracking
                # received enemy intelligence is not permission to skip the
                # worker's independent ballistic and exact launch checks.
                artillery = str(bot.get("profile", {}).get("class_tag") or "") == "SPG"
                if (not contact.get("visible") or
                        (not artillery and bot["id"] not in contact.get(
                            "shootable_by_bot_ids", ()))):
                    row['reason'] = 'not_visible' if not contact.get('visible') else 'no_local_lane'
                    continue
                distance = math.hypot(
                    contact["position"]["x"] - bx,
                    contact["position"]["z"] - bz)
                row['distance'] = distance
                row['range'] = self._engagement_range(bot, contact)
                if distance > row['range']:
                    row['reason'] = 'outside_engagement_range'
                    continue
                row['reason'] = 'eligible'
                score = 0.0
                if reads[bot_gunnery.CAPABILITY_TARGET_PRIORITY]:
                    score += (contact["health"] / float(
                        max(1, contact["max_health"])) *
                        TARGET_HEALTH_SCORE_SPAN)
                score += distance * TARGET_REACH_SCORE_PER_METRE
                if reads[bot_gunnery.CAPABILITY_TARGET_NEAREST]:
                    score += distance * NEAREST_TARGET_SCORE_PER_METRE
                hit = self._recent_hit(bot["id"], now)
                if (reads[bot_gunnery.CAPABILITY_TARGET_RETALIATION] and
                        hit is not None and
                        hit.get("attacker") == (
                            str(contact.get("target_kind") or ""),
                            _integer(contact.get("id")))):
                    score -= RECENT_ATTACKER_SCORE_BONUS
                if (reads[bot_gunnery.CAPABILITY_TARGET_HUMAN] and
                        str(contact.get("target_kind") or "") == "human"):
                    score -= HUMAN_TARGET_SCORE_BONUS
                if distance <= CLOSE_THREAT_DISTANCE:
                    # A point-blank enemy is an immediate self-defence problem,
                    # even while a previous long-range target still owns a
                    # short lease.
                    score -= CLOSE_THREAT_SCORE_BONUS
                sort_key = (
                    score, bot["id"], str(contact.get("target_kind") or ""),
                    contact["id"], distance)
                candidate = (
                    sort_key, bot, contact, distance,
                    self._weapon_ready(bot) and
                    (not artillery or bot["id"] in contact.get(
                        "shootable_by_bot_ids", ())))
                candidates.append(candidate)
                row.update(score=score, ready=bool(candidate[4]))
                by_bot.setdefault(bot["id"], []).append(candidate)

        # Preserve a valid target through small score changes. Without this,
        # sub-metre motion between two similar enemies flips the order every
        # server tick and repeatedly cancels the client's private A* search.
        for bot in bots:
            bot_candidates = sorted(
                by_bot.get(bot["id"], ()), key=lambda value: value[0])
            previous = self._target_assignments.get(bot["id"])
            if not bot_candidates:
                # A tactical firing-lane refresh is spread across render
                # frames.  During that incomplete generation the current
                # contact remains visible but its shooter list can briefly be
                # empty. Keep the current visible tracking target, while the order's
                # fire flag still follows the current (negative) lane sample.
                leased_contact = None
                cover_state = self._cover_states.get(bot["id"])
                cover_target = (cover_state.get("target")
                                if isinstance(cover_state, dict) else None)
                # A current visible contact remains an aiming target even
                # when its firing lane is temporarily blocked. The contact
                # lifetime/range/death checks, not the firing lease deadline,
                # own tracking expiry. This does not reserve a firing slot.
                if isinstance(previous, dict):
                    bx = _number(bot["state"].get("x"))
                    bz = _number(bot["state"].get("z"))
                    for contact in self._contacts_for_bot(bot, contacts, now):
                        key = (contact.get("target_kind"), contact["id"])
                        if (key != previous.get("target") or
                                not contact.get("visible")):
                            continue
                        distance = math.hypot(
                            contact["position"]["x"] - bx,
                            contact["position"]["z"] - bz)
                        if distance <= self._engagement_range(bot, contact):
                            leased_contact = dict(contact)
                            leased_contact["movement_lease"] = True
                            break
                if leased_contact is not None:
                    if not self._weapon_can_recover(bot):
                        self._target_assignments.pop(bot["id"], None)
                        continue
                    if cover_target == previous.get("target"):
                        previous["until"] = (
                            _number(now) + TARGET_LEASE_SECONDS)
                    assigned[bot["id"]] = leased_contact
                    observation['tracking_reason'] = 'current_visible_contact_blocked'
                    continue
                self._target_assignments.pop(bot["id"], None)
                continue
            if not isinstance(previous, dict):
                continue
            previous_candidate = None
            for candidate in bot_candidates:
                contact = candidate[2]
                key = (contact.get("target_kind"), contact["id"])
                if key == previous.get("target"):
                    previous_candidate = candidate
                    break
            if previous_candidate is None:
                # A missing lane never authorizes fire. Brief publication or
                # mechanical transitions should not discard a live aim merely
                # because another enemy is eligible in the same update.
                previous.setdefault('lane_missing_since', _number(now))
                old = next((contact for contact in self._contacts_for_bot(bot, contacts, now)
                    if (contact.get('target_kind'), contact['id']) == previous.get('target')
                    and contact.get('visible') and math.hypot(
                        contact['position']['x'] - _number(bot['state'].get('x')),
                        contact['position']['z'] - _number(bot['state'].get('z'))) <=
                        self._engagement_range(bot, contact)), None)
                best = bot_candidates[0]
                hit = self._recent_hit(bot['id'], now)
                urgent = bool(hit is not None and (best[2].get('target_kind'), best[2]['id']) ==
                    hit.get('attacker') and tactics[bot['id']].get(
                        bot_gunnery.CAPABILITY_TARGET_RETALIATION, True))
                if old is not None:
                    old_distance = math.hypot(old['position']['x'] - _number(bot['state'].get('x')),
                                              old['position']['z'] - _number(bot['state'].get('z')))
                    urgent = urgent or (best[3] <= CLOSE_THREAT_DISTANCE < old_distance)
                if (old is not None and not urgent and self._weapon_can_recover(bot) and
                        _number(now) - previous['lane_missing_since'] < TARGET_LEASE_SECONDS):
                    assigned[bot['id']] = dict(old, movement_lease=True)
                    observation['tracking_reason'] = 'bounded_lane_transition'
                    continue
                self._target_assignments.pop(bot["id"], None)
                continue
            previous.pop('lane_missing_since', None)
            if not previous_candidate[4]:
                if self._weapon_can_recover(bot):
                    contact = dict(previous_candidate[2])
                    contact["movement_lease"] = True
                    assigned[bot["id"]] = contact
                    previous["until"] = _number(now) + TARGET_LEASE_SECONDS
                else:
                    self._target_assignments.pop(bot["id"], None)
                continue
            best_score = bot_candidates[0][0][0]
            lease_expired = _number(now) >= _number(previous.get("until"))
            best_candidate = bot_candidates[0]
            best_key = (best_candidate[2].get("target_kind"),
                        best_candidate[2]["id"])
            close_override = (
                best_key != previous.get("target") and
                best_candidate[3] <= CLOSE_THREAT_DISTANCE and
                previous_candidate[3] > CLOSE_THREAT_DISTANCE
            )
            hit = self._recent_hit(bot["id"], now)
            attacker_override = bool(
                hit is not None and best_key == hit.get("attacker") and
                best_key != previous.get("target") and
                tactics.get(bot["id"], {}).get(
                    bot_gunnery.CAPABILITY_TARGET_RETALIATION, True))
            if close_override or attacker_override:
                continue
            aiming = self._target_aim_in_progress(bot, previous, now)
            observation['aim_retention'] = dict(active=aiming,
                aligned=previous.get('aim_aligned'), best_error=previous.get('aim_best_error'),
                progress_at=previous.get('aim_progress_at'), start_seq=previous.get('aim_start_seq'))
            if (lease_expired and not aiming and
                    previous_candidate[0][0] >
                    best_score + TARGET_SWITCH_MARGIN):
                continue
            contact = previous_candidate[2]
            key = (contact.get("target_kind"), contact["id"])
            if self._focus_saturated(
                    reservations, key, contact, previous_candidate[3]):
                self._target_decisions[bot['id']]['focus_refusals'].append(dict(
                    target=key, distance=previous_candidate[3], health=contact.get('health'),
                    limit=self._focus_limit(contact, previous_candidate[3]),
                    reservation=dict(reservations.get(key) or {}), stage='retained_target'))
                continue
            self._reserve_focus(reservations, key, bot, contact)
            assigned[bot["id"]] = contact
            if lease_expired:
                previous["until"] = _number(now) + TARGET_LEASE_SECONDS
        for (unused_sort_key, bot, contact, distance) in sorted(
                (candidate[:4] for candidate in candidates
                 if candidate[4]), key=lambda value: value[0]):
            if bot["id"] in assigned:
                continue
            key = (contact.get("target_kind"), contact["id"])
            if self._focus_saturated(
                    reservations, key, contact, distance):
                self._target_decisions[bot['id']]['focus_refusals'].append(dict(
                    target=key, distance=distance, health=contact.get('health'),
                    limit=self._focus_limit(contact, distance),
                    reservation=dict(reservations.get(key) or {}), stage='ranked_target'))
                continue
            self._reserve_focus(reservations, key, bot, contact)
            assigned[bot["id"]] = contact
            self._target_assignments[bot["id"]] = self._new_target_lease(bot, key, now)
        # Reloading and repairable vehicles still need one tactical contact
        # for spacing, withdrawal and cover.  Add that movement-only lease
        # after every current shooter has competed for the focus cap, so it
        # cannot displace fire that is actually available.
        for bot in bots:
            if bot["id"] in assigned or not self._weapon_can_recover(bot):
                continue
            bot_candidates = sorted(
                by_bot.get(bot["id"], ()), key=lambda value: value[0])
            if not bot_candidates or bot_candidates[0][4]:
                continue
            contact = dict(bot_candidates[0][2])
            contact["movement_lease"] = True
            key = (contact.get("target_kind"), contact["id"])
            assigned[bot["id"]] = contact
            self._target_assignments[bot["id"]] = self._new_target_lease(bot, key, now)
        for bot in bots:
            if bot["id"] not in assigned:
                self._target_assignments.pop(bot["id"], None)
            selected = assigned.get(bot['id'])
            observation = self._target_decisions[bot['id']]
            observation['selected'] = ((selected.get('target_kind'), selected['id'])
                                        if selected is not None else None)
            observation['outcome'] = ('movement_lease' if selected is not None and
                selected.get('movement_lease') else 'assigned' if selected is not None
                else 'no_eligible_lane' if not by_bot.get(bot['id'])
                else 'weapon_unready' if not self._weapon_ready(bot)
                else 'focus_capacity')
            observation['lease_after'] = dict(self._target_assignments.get(bot['id']) or {})
        return assigned

    @staticmethod
    def _route_catalog(bots):
        result = {}
        for bot in bots:
            route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
            route_id = str(route.get("id") or "")
            if route_id and route.get("waypoints") and route_id not in result:
                result[route_id] = route
        return result

    @staticmethod
    def _team_base_axis(team, bots):
        """Infer one direction-neutral own/enemy axis from uploaded routes.

        Baked routes start at their team's own base, so the opposing team's
        route starts provide the cleanest enemy-base endpoint. If no opposing
        bot exists, the farthest own-route endpoint is the conservative fallback
        because a local rear-guard route may end near its own base. The
        calculation is invariant under map rotation and reflection.
        """
        starts = {1: [], 2: []}
        own_ends = []
        for bot in bots:
            route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
            waypoints = route.get("waypoints")
            if not isinstance(waypoints, list) or len(waypoints) < 2:
                continue
            bot_team = _integer(bot.get("team"))
            if bot_team not in (1, 2):
                continue
            starts[bot_team].append(_point(waypoints[0]))
            if bot_team == team:
                own_ends.append(_point(waypoints[-1]))
        own_starts = starts.get(team, ())
        if not own_starts or not own_ends:
            return None
        own = {
            "x": round(sum(value["x"] for value in own_starts) /
                       len(own_starts), 3),
            "y": round(sum(value["y"] for value in own_starts) /
                       len(own_starts), 3),
            "z": round(sum(value["z"] for value in own_starts) /
                       len(own_starts), 3),
        }
        enemy_starts = starts.get(3 - team, ())
        if enemy_starts:
            enemy_ends = enemy_starts
        else:
            distances = [math.hypot(value["x"] - own["x"],
                                    value["z"] - own["z"])
                         for value in own_ends]
            farthest = max(distances)
            # Average equally distant through-route endpoints instead of
            # breaking a geometric tie with ids or world-axis signs.
            threshold = max(1.0, farthest * 0.02)
            enemy_ends = [value for value, distance in
                          zip(own_ends, distances)
                          if farthest - distance <= threshold]
        enemy = {
            "x": round(sum(value["x"] for value in enemy_ends) /
                       len(enemy_ends), 3),
            "y": round(sum(value["y"] for value in enemy_ends) /
                       len(enemy_ends), 3),
            "z": round(sum(value["z"] for value in enemy_ends) /
                       len(enemy_ends), 3),
        }
        if math.hypot(enemy["x"] - own["x"],
                      enemy["z"] - own["z"]) < 1.0:
            return None
        return own, enemy

    def _artillery_anchor(self, bot, team_axis):
        """Prefer the canonical sourced initial plan; otherwise keep legacy.

        The authority resolves community areas against the loaded #1513 graph
        before publishing the manifest. A missing plan explicitly keeps the
        old rear-route fallback; neither path proves a clear firing arc.
        """
        initial = spg_positions.canonical_plan(bot.get("spg_initial"), tactics=self.tactics)
        if initial is not None:
            # This point was selected inside a sourced area by the authority's
            # actual #1513 graph. It is independent of ordinary route catalogues.
            return {"point": dict(initial["point"]), "face": dict(initial["face"]),
                    "index": 0, "parking_radius": initial["radius"]}
        route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
        waypoints = route.get("waypoints")
        route_signature = (
            str(route.get("id") or ""),
            tuple((_number(value.get("x")), _number(value.get("y")),
                   _number(value.get("z")))
                  for value in waypoints)
            if isinstance(waypoints, list) else (),
        )
        cached = self._artillery_anchors.get(bot["id"])
        if (isinstance(cached, dict) and
                cached.get("route_signature") == route_signature):
            return {
                "point": dict(cached["point"]),
                "face": dict(cached["face"]),
                "index": cached["index"],
            }
        if not isinstance(waypoints, list) or not waypoints:
            position = _point(bot.get("state"))
            result = {
                "point": position,
                "face": position,
                "index": 0,
            }
            self._artillery_anchors[bot["id"]] = dict(
                result, route_signature=route_signature)
            return result
        points = [_point(value) for value in waypoints]
        if team_axis is None:
            own = points[0]
            enemy = points[-1]
        else:
            own, enemy = team_axis
        axis_x = enemy["x"] - own["x"]
        axis_z = enemy["z"] - own["z"]
        axis_length = math.hypot(axis_x, axis_z)
        if axis_length < 1.0:
            own = points[0]
            enemy = points[-1]
            axis_x = enemy["x"] - own["x"]
            axis_z = enemy["z"] - own["z"]
            axis_length = max(1.0, math.hypot(axis_x, axis_z))
        axis_squared = axis_length * axis_length
        desired_radius = _clamp(axis_length * 0.16, 35.0, 120.0)
        candidates = []
        for point_index, point in enumerate(points):
            offset_x = point["x"] - own["x"]
            offset_z = point["z"] - own["z"]
            radius = math.hypot(offset_x, offset_z)
            progress = (offset_x * axis_x + offset_z * axis_z) / axis_squared
            outside_rear = max(0.0, progress - 0.30,
                               -0.12 - progress)
            base_overlap = max(0.0, desired_radius * 0.35 - radius)
            score = (outside_rear * axis_length * 8.0 +
                     base_overlap * 5.0 +
                     abs(radius - desired_radius) +
                     abs(progress - 0.12) * axis_length * 0.20)
            candidates.append((score, point_index, point))
        unused_score, point_index, point = min(candidates)
        result = {
            "point": dict(point),
            "face": dict(enemy),
            "index": point_index,
        }
        self._artillery_anchors[bot["id"]] = dict(
            result, route_signature=route_signature)
        return result

    @staticmethod
    def _nearest_route(contact, catalog):
        best = None
        best_key = None
        point = contact.get("position") or {}
        for route_id, route in sorted(catalog.items()):
            distance = None
            for waypoint in route.get("waypoints") or []:
                dx = _number(waypoint.get("x")) - _number(point.get("x"))
                dz = _number(waypoint.get("z")) - _number(point.get("z"))
                value = dx * dx + dz * dz
                if distance is None or value < distance:
                    distance = value
            key = (distance if distance is not None else 1e18, route_id)
            if best_key is None or key < best_key:
                best_key = key
                best = route_id
        return best

    def _record_route_assignment(self, bot, now, previous, current, reason,
                                 evidence=None):
        """Diagnostic provenance only; never participates in route selection."""
        old = self._route_assignment_receipts.get(bot['id']) or {}
        self._route_assignment_receipts[bot['id']] = dict(
            sequence=old.get('sequence', 0) + 1, at=_number(now),
            clock_basis='server_monotonic_seconds', round=self._round_id,
            bot=bot['id'],
            previous_route=str(previous or ''), route=str(current or ''),
            reason=reason, position=_point(bot.get('state') or {}))
        previous_lease = self._route_assignments.get(bot['id']) or {}
        if _number(previous_lease.get('until')) > 0.0:
            self._route_assignment_receipts[bot['id']]['previous_lease'] = dict(
                until=_number(previous_lease['until']),
                check=dict(previous_lease.get('_lease_check') or {}),
                observation=dict(previous_lease.get('_lease_observation') or {}))
        receipt = self._route_assignment_receipts[bot['id']]
        cursor = self._route_states.get(bot['id']) or {}
        route = previous_lease.get('route') or bot.get('route') or {}
        points = route.get('waypoints') or []
        index = _integer(cursor.get('index'), -1)
        point = dict(points[index]) if 0 <= index < len(points) else None
        receipt['previous_progress'] = dict(index=index, point=point,
            distance=(math.hypot(_number(point.get('x')) - receipt['position']['x'],
                                _number(point.get('z')) - receipt['position']['z'])
                      if point is not None else None))
        if evidence is not None:
            receipt['selection'] = evidence
        # A lease can expire and be replaced again within the same server
        # update. Preserve each immutable event, not only the last decision.
        event = dict(receipt)
        receipt['history'] = list(old.get('history') or [])[-7:] + [event]
        receipt['history_dropped'] = max(0, receipt['sequence'] - len(receipt['history']))

    def _rebalance_routes(self, team, bots, contacts, now,
                          protected_ids=()):
        """Evaluate pressure assignments and their releases once per minute."""
        if _number(now) < _number(self._next_route_rebalance.get(team)):
            self._observe_route_leases(bots, now, 'rebalance_not_due', evaluation=False)
            return
        self._next_route_rebalance[team] = _number(now) + ROUTE_REBALANCE_SECONDS
        protected_ids = set(protected_ids).union(self._previous_combat)
        for bot in bots:
            authored = bot_tactics.route_config(self.tactics, self.tactics_map, (bot.get('route') or {}).get('id'), bot['team'])
            if authored is not None and authored['policy'] == 'fixed':
                protected_ids.add(bot['id'])
        catalog = self._route_catalog(bots)
        # An unexpired pressure assignment is itself a live route owner.
        # Losing the last original donor must not erase its recipient's road.
        retained_routes = []
        for bot in bots:
            assignment = self._route_assignments.get(bot['id']) or {}
            route = assignment.get('route')
            if ((assignment.get('ordered_task') or assignment.get('radio_scoped') and
                    _number(assignment.get('until')) > _number(now)) and
                    isinstance(route, dict) and route.get('waypoints')):
                route_id = str(route.get('id') or '')
                if route_id and route_id not in catalog:
                    catalog[route_id] = route
                    retained_routes.append(route_id)
        for bot in bots:
            task = self._travel_tasks.get(bot['id'])
            if task:
                protected_ids.add(bot['id'])
                for route in (task.get('route'),task.get('target_route')):
                    if route and route.get('waypoints'):
                        catalog[str(route['id'])]=route
        family=lambda identity:self._task_family(catalog.get(identity) or {'id':identity},team)
        # An active recovery owns its frozen lane through combat and folding.
        # Finishing recovery releases this protection for ordinary pressure work.
        for bot in bots:
            assigned = self._route_assignments.get(bot['id'], {})
            if bot['id'] in self._route_recoveries:
                route = assigned.get('route') or bot.get('route') or {}
                catalog[str(route.get('id') or '')] = route
                protected_ids.add(bot['id'])
        for bot in bots:
            if bot["id"] in self._route_recoveries or bot['id'] in self._travel_tasks:
                continue
            route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
            route_id = str(route.get("id") or "")
            assigned = self._route_assignments.get(bot["id"])
            assigned_route = assigned.get("route") if isinstance(assigned, dict) else None
            assigned_id = (str(assigned_route.get("id") or "")
                           if isinstance(assigned_route, dict) else "")
            assigned_until = _number(assigned.get("until")) if isinstance(assigned, dict) else 0.0
            knowledge_lost = bool(
                isinstance(assigned, dict) and assigned.get("radio_scoped") and
                not any(self._nearest_route(contact, catalog) == assigned_id
                        for contact in self._contacts_for_bot(bot, contacts, now)))
            if (knowledge_lost or assigned_id not in catalog or
                    assigned_route != catalog.get(assigned_id) or
                    (assigned_until > 0.0 and assigned_until <= _number(now))):
                if assigned is not None:
                    self._record_route_assignment(bot, now, assigned_id, route_id,
                        'radio_knowledge_lost' if knowledge_lost else
                        ('lease_expired' if assigned_until > 0.0 and
                         assigned_until <= _number(now) else 'catalog_reset'),
                        evidence=dict(evaluated_at=_number(now),
                            assigned_until=assigned_until, knowledge_lost=knowledge_lost,
                            knowledge_contacts=[dict(contact=copy.deepcopy(contact),
                                nearest_route=self._nearest_route(contact, catalog))
                                for contact in self._contacts_for_bot(bot, contacts, now)],
                            catalog_contains_route=assigned_id in catalog,
                            catalog_route_matches=assigned_route == catalog.get(assigned_id),
                            retained_assignment_routes=list(retained_routes),
                            invalidation_causes=[cause for cause, applies in (
                                ('radio_knowledge_lost', knowledge_lost),
                                ('catalog_missing', assigned_id not in catalog),
                                ('catalog_changed', assigned_id in catalog and
                                 assigned_route != catalog.get(assigned_id)),
                                ('lease_expired', assigned_until > 0.0 and
                                 assigned_until <= _number(now))) if applies]))
                if route_id in catalog:
                    self._route_assignments[bot["id"]] = {
                        "route": catalog[route_id], "until": 0.0,
                    }
                else:
                    self._route_assignments.pop(bot["id"], None)
                self._route_states.pop(bot["id"], None)
        if len(catalog) < 2:
            self._route_balance_receipts[team] = dict(sampled_at=_number(now),
                outcome='catalog_has_no_alternative', candidates=[])
            self._observe_route_leases(bots, now, 'catalog_has_no_alternative')
            return
        balance = dict(sampled_at=_number(now), outcome='no_known_pressure',
                       selected_bot=None, candidates=[])
        self._route_balance_receipts[team] = balance
        pressure = dict((route_id, 0.0) for route_id in catalog)
        for contact in contacts:
            if not any(self._contact_known_to(contact, bot["id"], now)
                       for bot in bots):
                continue
            route_id = self._nearest_route(contact, catalog)
            if route_id is None:
                continue
            health_fraction = (_number(contact.get("health"), 1.0) /
                               max(1.0, _number(contact.get("max_health"), 1.0)))
            pressure[route_id] += max(0.3, health_fraction)
        totals={}
        for identity,value in pressure.items():totals[family(identity)]=totals.get(family(identity),0.)+value
        pressure=dict((identity,totals[family(identity)]) for identity in pressure)
        if not pressure or max(pressure.values()) <= 0.0:
            self._observe_route_leases(bots, now, 'no_known_pressure')
            for bot in bots:
                if bot['id'] in self._route_recoveries:
                    continue
                assignment = self._route_assignments.get(bot['id']) or {}
                if _number(assignment.get('until')) > 0.0:
                    assignment['_lease_observation'] = dict(
                        evaluated_at=_number(now), outcome='no_known_pressure',
                        until=_number(assignment['until']))
            return
        # SPGs stage behind a lane and do not provide its front-line coverage.
        # Counting them here made a road look defended while also preventing
        # the artillery itself from ever being selected as a donor.
        counts = dict((route_id, 0) for route_id in catalog)
        class_counts = {}
        for bot in bots:
            if str(bot.get("profile", {}).get("class_tag") or "") == "SPG" or bot['id'] in self._travel_tasks:
                continue
            assignment = self._route_assignments.get(bot["id"], {})
            route = assignment.get("route") if isinstance(assignment, dict) else None
            if not isinstance(route, dict):
                route = bot.get("route") or {}
            route_id = str(route.get("id") or "")
            if route_id in counts:
                key = (route_id, bot.get("profile", {}).get("class_tag"))
                class_counts[key] = class_counts.get(key, 0) + 1
                if self._route_line_contributor(bot, self._contacts_for_bot(bot, contacts, now)):
                    counts[route_id] += 1
        totals={}
        for identity,value in counts.items():totals[family(identity)]=totals.get(family(identity),0)+value
        counts=dict((identity,totals[family(identity)]) for identity in counts)
        reservations=dict((route_id,0) for route_id in catalog)
        for bot in bots:
            task=self._travel_tasks.get(bot['id']) or {}
            target=task.get('target_route') or {}
            if task.get('kind')=='pressure' and target.get('id') in reservations:
                for identity in reservations:
                    if family(identity)==family(target['id']):reservations[identity]+=1
        target_route = max(sorted(catalog), key=lambda route_id:
                           pressure[route_id] - (counts[route_id]+reservations[route_id]) * 0.45)
        target_score = pressure[target_route] - (counts[target_route]+reservations[target_route]) * 0.45
        balance.update(outcome='no_improving_donor', target_route=target_route,
                       pressure=dict(pressure), contributors=dict(counts), reservations=reservations,
                       target_score=target_score)
        # Preserve the inputs behind pressure changes, not only the winning
        # total. Radio expiry, deaths and route transfers can change a total
        # between two pressure evaluations without a new visible enemy.
        balance['contact_inputs'] = [dict(
            target_kind=contact.get('target_kind'), target_id=contact.get('id'),
            position=_point(contact.get('position') or {}),
            route=self._nearest_route(contact, catalog),
            health=contact.get('health'), max_health=contact.get('max_health'),
            visible=contact.get('visible'),
            radio_bot_until=dict(contact.get('radio_bot_until') or {}),
            known_by=[bot['id'] for bot in bots
                      if self._contact_known_to(contact, bot['id'], now)])
            for contact in contacts]
        balance['contributor_inputs'] = [dict(bot=bot['id'],
            route=str(((self._route_assignments.get(bot['id']) or {}).get('route')
                       or bot.get('route') or {}).get('id') or ''),
            contributes=self._route_line_contributor(
                bot, self._contacts_for_bot(bot, contacts, now)),
            position=_point(bot['state'])) for bot in bots
            if str(bot.get('profile', {}).get('class_tag') or '') != 'SPG']
        self._observe_route_leases(bots, now,
            'pressure_already_covered' if target_score <= 0.0 else 'pressure_evaluated',
            target_route=target_route, target_pressure=pressure[target_route],
            target_contributors=counts[target_route], target_score=target_score)
        target_record = catalog[target_route]
        # Re-evaluation happens before a temporary assignment expires. Renew
        # the same pressured route in place so its waypoint index survives;
        # only a real route change clears progress below.
        for bot in bots:
            if bot['id'] in self._route_recoveries or bot['id'] in self._travel_tasks:
                continue
            knows_target = any(family(self._nearest_route(contact, catalog)) == family(target_route)
                               for contact in self._contacts_for_bot(bot, contacts, now))
            assignment = self._route_assignments.get(bot["id"])
            route = assignment.get("route") if isinstance(assignment, dict) else None
            own_id = str((route or {}).get('id') or '')
            knows_own = any(self._nearest_route(contact, catalog) == own_id
                            for contact in self._contacts_for_bot(bot, contacts, now))
            own_score = pressure.get(own_id, 0.0) - counts.get(own_id, 0) * 0.45
            # Test whether this deployment is still needed AFTER it leaves.
            # Counting the donor as its own replacement made covered lanes
            # expire to default and immediately borrow the same vehicle back.
            own_contribution = int(self._route_line_contributor(bot,
                self._contacts_for_bot(bot, contacts, now)) and
                str(bot.get('profile', {}).get('class_tag') or '') != 'SPG')
            departure_score = own_score + own_contribution * 0.45
            if isinstance(assignment, dict) and _number(assignment.get('until')) > 0.0:
                assignment['_lease_observation'] = dict(
                    evaluated_at=_number(now), target_route=target_route,
                    own_route=own_id, own_pressure=pressure.get(own_id, 0.0),
                    target_pressure=pressure[target_route],
                    own_contributors=counts.get(own_id, 0),
                    target_contributors=counts[target_route],
                    knows_target=knows_target, knows_own=knows_own, own_score=own_score,
                    own_contribution=own_contribution, departure_score=departure_score,
                    until=_number(assignment['until']),
                    outcome=('pressure_already_covered' if target_score <= 0.0 else
                             'no_target_contact' if not knows_target else
                             'different_pressure_target'))
            # Another lane winning this evaluation does not end a still
            # needed deployment. Preserve its cursor rather than expire to
            # the default lane and borrow the same hull back at the next evaluation.
            # Donor scoring below can still make a real reassignment.
            if (isinstance(route, dict) and
                    knows_own and departure_score > 0.0 and
                    _number(assignment.get("until")) > 0.0):
                assignment["until"] = _number(now) + ROUTE_LEASE_SECONDS
                assignment['_lease_observation'].update(
                    outcome='renewed', until=assignment['until'])
        if target_score <= 0.0:
            balance['outcome'] = 'pressure_already_covered'
            return
        candidates = []
        candidate_checks = balance['candidates']
        for bot in bots:
            check = dict(bot=bot['id'], outcome='eligible')
            candidate_checks.append(check)
            if bot['id'] in self._travel_tasks or bot['id'] in self._route_recoveries or bot['state'].get('route_wreck_blocked'):
                check['outcome'] = 'route_recovery_in_progress'
                continue
            received = self._contacts_for_bot(bot, contacts, now)
            if not any(family(self._nearest_route(contact, catalog)) == family(target_route)
                       for contact in received):
                check['outcome'] = 'no_received_target_contact'
                continue
            if bot["id"] in protected_ids:
                check['outcome'] = 'protected'
                continue
            if self._route_states.get(bot['id'], {}).get('parking_phase') in (
                    'approach', 'waiting', 'queue'):
                # Rebalancing cannot discard an authored parking timer/lease.
                check['outcome'] = 'parking_in_progress'
                continue
            recipient_route=self._task_class_route(catalog[target_route],bot,catalog)
            if recipient_route is None:
                check['outcome']='authored_class_mismatch'
                continue
            target_authored = bot_tactics.route_config(self.tactics, self.tactics_map, recipient_route['id'], bot['team'])
            if target_authored is not None and not bot_tactics.matches(target_authored, bot):
                check['outcome'] = 'authored_class_mismatch'
                continue
            if str(bot.get("profile", {}).get("class_tag") or "") == "SPG":
                check['outcome'] = 'artillery'
                continue
            # An immobilized tank may still hold a firing lane, so it remains
            # in counts above. It cannot satisfy a movement reassignment.
            if not self._route_donor_eligible(bot):
                check['outcome'] = 'immobile_donor'
                continue
            assignment = self._route_assignments.get(bot["id"], {})
            current = assignment.get("route") if isinstance(assignment, dict) else None
            if not isinstance(current, dict):
                current = bot.get("route") or {}
            current_id = str(current.get("id") or "")
            check['current_route'] = current_id
            if family(current_id) == family(target_route) or counts.get(current_id, 0) <= 1:
                check['outcome'] = ('already_on_target' if family(current_id) == family(target_route)
                                    else 'last_line_contributor')
                continue
            # Use the existing pressure-minus-contributors metric on BOTH
            # sides of this transfer. A donor must not create a larger deficit
            # on departure than the one it resolves, then be selected back four
            # seconds later under unchanged contacts. Real pressure changes can
            # still reverse a transfer through the same score and tie-breaks.
            own_score = pressure.get(current_id, 0.0) - counts.get(current_id, 0) * 0.45
            before = max(0.0, own_score, target_score)
            after = max(0.0, own_score + 0.45, target_score - 0.45)
            check.update(current_pressure_score=own_score, target_pressure_score=target_score,
                         before_transfer=before, after_transfer=after)
            if after + 1.e-9 >= before:
                check['outcome'] = 'no_pressure_improvement'
                continue
            profile = bot.get("profile", {})
            roles = profile.get("roles") or {}
            class_weights = recipient_route.get("class_weights")
            class_affinity = 0.5
            if isinstance(class_weights, dict):
                class_tag = str(profile.get("class_tag") or "")
                if class_tag in class_weights:
                    class_affinity = _clamp(
                        _number(class_weights.get(class_tag)), 0.0, 1.0)
                    if class_affinity < MIN_ROUTE_CLASS_AFFINITY:
                        check['outcome'] = 'class_affinity_too_low'
                        continue
            route_roles = target_record.get("role_weights")
            role_affinity = 0.0
            if isinstance(route_roles, dict):
                role_affinity = sum(
                    _number(value) * _number(route_roles.get(name))
                    for name, value in roles.items())
            mobility = max(_number(roles.get("support")),
                           _number(roles.get("flanker")),
                           _number(roles.get("scout")))
            personality = self._personality(bot["id"])
            score = (mobility * 2.0 + personality["adaptability"] -
                     _number(roles.get("brawler")) * 0.65 -
                     pressure.get(current_id, 0.0) * 0.7 +
                     class_affinity * 1.8 + role_affinity * 1.2)
            candidates.append((score, -bot["id"], bot))
            check.update(score=score, tie_break=-bot['id'],
                mobility=mobility, adaptability=personality['adaptability'],
                brawler=_number(roles.get('brawler')), current_pressure=pressure.get(current_id, 0.0),
                class_affinity=class_affinity, role_affinity=role_affinity)
        if not candidates:
            return
        donor = max(candidates)[2]
        balance.update(outcome='assigned', selected_bot=donor['id'])
        previous = self._route_assignments.get(donor['id']) or {}
        previous_route = previous.get('route') or donor.get('route') or {}
        self._record_route_assignment(donor, now, previous_route.get('id'),
            target_route, 'pressure_rebalance', evidence=dict(
                evaluated_at=_number(now), target_route=target_route,
                pressure=dict(pressure), contributors=dict(counts),
                target_score=pressure[target_route] - counts[target_route] * 0.45,
                contact_inputs=balance['contact_inputs'],
                contributor_inputs=balance['contributor_inputs'],
                candidates=candidate_checks, selected_bot=donor['id']))
        destination=self._task_class_route(catalog[target_route],donor,catalog)
        self._task_begin(donor, 'pressure', target_route=destination, now=now)

    def _observe_route_leases(self, bots, now, outcome, evaluation=True, **values):
        """Record early exits without renewing leases or altering allocation."""
        for bot in bots:
            if bot['id'] in self._route_recoveries or bot['id'] in self._travel_tasks:
                continue
            lease = self._route_assignments.get(bot['id']) or {}
            if _number(lease.get('until')) <= 0.0:
                continue
            receipt = dict(values, evaluated_at=_number(now), outcome=outcome,
                until=_number(lease['until']))
            lease['_lease_check'] = dict(receipt)
            if evaluation:
                lease['_lease_observation'] = receipt

    def _reroute_automatic_goal(self, order, bot, manifest, now):
        """Bound each blocked gate attempt; skip once before changing lanes."""
        bot_id = bot['id']
        state = bot['state']
        route_id = str(order.get('route_id') or '')
        if ((order.get('combat_mode') in ('support_hold', 'base_defense', 'advance_contact') or
                order.get('defense_base_id')) and
                not order.get('team_command') and self._route_donor_eligible(bot)):
            # An intermittent tactical hold pauses the same gate attempt;
            # resuming it is not evidence that the previous exit succeeded.
            progress = self._wreck_route_progress.get(bot_id)
            if progress is not None:
                progress.setdefault('paused_at', _number(now))
                order['route_attempt'] = dict(route_id=progress['key'][0],
                    route_index=progress['key'][1],action='pause_'+order['combat_mode'],
                    elapsed=round(progress['paused_at']-progress['since'],3))
            return
        if (order.get('combat_mode') not in ('route', 'advance', 'parking_approach', 'base_capture',
                                            'withdraw', 'under_fire_withdraw', 'low_health_retreat') or
                order.get('team_command') or
                (order.get('throttle_override') is not None and
                 _number(order.get('throttle_override')) <= 0.0) or
                not self._route_donor_eligible(bot)):
            self._wreck_route_progress.pop(bot_id, None)
            return
        # Normal advance carries a positive travel override. It is still the
        # same authored gate attempt, with the original retry/skip budget.
        point = _point(state)
        goal = _point(order.get('move_position') or {})
        physical_block = bool(state.get('route_wreck_blocked'))
        distance = math.hypot(goal['x'] - point['x'], goal['z'] - point['z'])
        route = (self._route_assignments.get(bot_id) or {}).get('route') or bot.get('route') or {}
        waypoints = route.get('waypoints') or []
        # A one-point automatic objective has no next macro gate. A local
        # connector eleven metres away cannot consume that destination.
        arrival = max(1.5 if len(waypoints) <= 1 else ROUTE_ARRIVAL_RADIUS,
                      _number(order.get('arrival_radius')))
        trace = dict(route_id=route_id, route_index=order.get('route_index'),
                     distance=round(distance, 3), arrival=arrival,
                     physical_block=physical_block, action='attempt', elapsed=0.)
        order['route_attempt'] = trace
        # Completed arrivals, intentional holds and unowned poses are not
        # failed travel. Native geometry refusal need not be a wreck receipt.
        if not physical_block and (not state.get('world_pose') or
                distance <= arrival):
            trace['action'] = 'arrived_or_unowned'
            self._wreck_route_progress.pop(bot_id, None)
            return
        key = (route_id, order.get('route_index'))
        progress = self._wreck_route_progress.get(bot_id)
        if progress is None or progress['key'] != key:
            progress = None
        if progress is None:
            self._wreck_route_progress[bot_id] = {
                'key': key, 'goal': goal, 'since': _number(now),
                'best_distance': distance,
                'origin': dict(point), 'physical_block': physical_block}
            trace.update(attempt_started_at=_number(now), reset_reason='new_gate')
            return
        # A receipt describes the current blocker, not a new gate attempt.
        # Contact flicker must not renew an unmoved tank's twenty-second lease.
        previous_block = progress.get('physical_block')
        progress['physical_block'] = physical_block
        trace['previous_physical_block'] = previous_block
        trace['blocker_changed'] = previous_block != physical_block
        paused_at = progress.pop('paused_at', None)
        if paused_at is not None:
            progress['since'] += max(0., _number(now) - paused_at)
            trace['resumed_after_pause'] = max(0., _number(now) - paused_at)
        trace.update(attempt_started_at=progress['since'],
            attempt_origin=dict(progress.get('origin', point)))
        # A movable corpse may remain in the corridor throughout a successful
        # push. Keep the same half-metre progress quantum as the local motor;
        # do not classify continuing contact as twenty seconds of no progress.
        # The high-water mark belongs to the gate, so reversing and returning
        # to the same place cannot buy another attempt.
        best_distance = progress.setdefault('best_distance', math.hypot(
            goal['x'] - progress['origin']['x'],
            goal['z'] - progress['origin']['z']))
        progress_goal = progress['goal']
        progress_distance = math.hypot(progress_goal['x'] - point['x'],
                                       progress_goal['z'] - point['z'])
        improvement = best_distance - progress_distance
        trace.update(best_distance=round(best_distance, 3),
                     improvement=round(improvement, 3),
                     progress_goal=dict(progress_goal),
                     progress_distance=round(progress_distance, 3))
        if physical_block and improvement >= 0.5:
            progress.update(since=_number(now), origin=dict(point),
                            best_distance=progress_distance)
            trace.update(action='physical_progress_renewed', elapsed=0.,
                         attempt_started_at=_number(now), attempt_origin=dict(point))
            return
        if not physical_block:
            origin = progress.get('origin', point)
            net = math.hypot(point['x'] - origin['x'], point['z'] - origin['z'])
            toward = math.hypot(goal['x'] - origin['x'], goal['z'] - origin['z']) - distance
            if net >= 6.0 and toward >= 4.0:
                progress.update(since=_number(now), origin=dict(point), goal=goal,
                                best_distance=min(best_distance, distance))
                return
        # A moving recovery orbit still has a finite attempt budget. Only
        # consuming the gate or clearing the physical blocker ends this attempt.
        trace['elapsed'] = round(_number(now) - progress['since'], 3)
        if _number(now) - progress['since'] < WRECK_ROUTE_WAIT_SECONDS:
            return
        route_state = self._route_states.get(bot_id) or {}
        index = _integer(order.get('route_index'))
        if order.get('combat_mode') == 'parking_approach':
            # The small parking place is optional. Decline it first and use
            # its ordinary parent gate, including when it is the last gate.
            route_state.setdefault('parking_completed', set()).add(index)
            route_state.setdefault('parking_skipped', set()).add(index)
            route_state.pop('parking_phase', None)
            route_state.pop('parking_slot', None)
            for claim_key, claim in list(self._wait_claims.items()):
                if claim['bot_id'] == bot_id and claim_key[:3] == (bot['team'], route_id, index):
                    self._wait_claims.pop(claim_key, None)
            self._route_states[bot_id] = route_state
            new_id, new_index, move, anchor, join = self._route(bot, now)
            order.update(route_id=new_id, route_index=new_index,
                         combat_mode='route', parking_phase=None,
                         parking_slot=None, arrival_radius=None,
                         move_position=move, face_position=dict(move),
                         route_anchor=anchor, route_join=join,
                         parking_skip_reason='blocked_approach_timeout')
            self._apply_authored_route_order(order, bot, move, now)
            trace.update(action='skip_parking', next_route=new_id, next_index=new_index)
            self._wreck_route_progress[bot_id] = {
                'key': (new_id, new_index), 'goal': _point(move),
                'since': _number(now), 'origin': dict(point),
                'physical_block': physical_block}
            return
        if route_state.get('blocked_skip_to') != index and index + 1 < len(waypoints):
            next_index = index + 1
            route_state.update(index=next_index, blocked_skip_to=next_index,
                               join_index=next_index, join_anchor=dict(point))
            # Abandon the blocked gate's parking lease as well as its geometry.
            route_state.setdefault('parking_completed', set()).add(index)
            route_state.pop('parking_phase', None)
            route_state.pop('parking_slot', None)
            for claim_key, claim in list(self._wait_claims.items()):
                if claim['bot_id'] == bot_id and claim_key[:3] == (bot['team'], route_id, index):
                    self._wait_claims.pop(claim_key, None)
            self._route_states[bot_id] = route_state
            new_id, new_index, move, anchor, join = self._route(bot, now)
            order.update(route_id=new_id, route_index=new_index,
                         combat_mode='route', parking_phase=None,
                         parking_slot=None, arrival_radius=None,
                         move_position=move, face_position=dict(move),
                         route_anchor=anchor, route_join=join,
                         route_point_skip_reason='blocked_timeout',
                         previous_route_index=index)
            self._apply_authored_route_order(order, bot, move, now)
            trace.update(action='skip_gate', next_route=new_id, next_index=new_index)
            self._wreck_route_progress[bot_id] = {
                'key': (new_id, new_index), 'goal': _point(move),
                'since': _number(now), 'origin': dict(point),
                'physical_block': physical_block}
            return
        avoided = self._wreck_route_avoid.setdefault(bot_id, {})
        avoided[route_id] = _number(now) + WRECK_ROUTE_AVOID_SECONDS
        catalog = self._route_catalog([
            raw for raw in manifest or ()
            if _integer(raw.get('team')) == bot['team']])
        candidates = []
        retry_candidates = []
        entry_receipts = []
        class_tag = str(bot.get('profile', {}).get('class_tag') or '')
        for candidate_id, route in sorted(catalog.items()):
            entry_receipt = dict(route=candidate_id, outcome='eligible')
            entry_receipts.append(entry_receipt)
            if candidate_id == route_id:
                entry_receipt['outcome'] = 'current_route'
                continue
            config = bot_tactics.route_config(
                self.tactics, self.tactics_map, candidate_id, bot['team'])
            if config is not None and not bot_tactics.matches(config, bot):
                entry_receipt['outcome'] = 'class_mismatch'
                continue
            affinity = _number((route.get('class_weights') or {}).get(
                class_tag), 0.5)
            if affinity < MIN_ROUTE_CLASS_AFFINITY:
                entry_receipt.update(outcome='class_affinity', affinity=affinity)
                continue
            points = route['waypoints']
            entry = min(range(len(points)), key=lambda i: math.hypot(
                _number(points[i].get('x')) - point['x'],
                _number(points[i].get('z')) - point['z']))
            while entry < len(points) - 1 and math.hypot(
                    _number(points[entry].get('x')) - point['x'],
                    _number(points[entry].get('z')) - point['z']) < 30.0:
                entry += 1
            # Different route names may share the same failed next gate.
            # Do not call that an alternative exit.
            if math.hypot(_number(points[entry].get('x')) - goal['x'],
                          _number(points[entry].get('z')) - goal['z']) < 16.0:
                entry_receipt.update(outcome='same_failed_gate', entry=entry,
                                     point=_point(points[entry]))
                continue
            nearest = min(math.hypot(
                _number(p.get('x')) - point['x'],
                _number(p.get('z')) - point['z'])
                for p in route['waypoints'])
            candidate = (-affinity, nearest, candidate_id, route, entry)
            entry_receipt.update(entry=entry,
                point=_point(points[entry]), affinity=affinity,
                nearest_distance=nearest,
                entry_distance=math.hypot(_number(points[entry].get('x')) - point['x'],
                                          _number(points[entry].get('z')) - point['z']),
                retry_after=_number(avoided.get(candidate_id)))
            if _number(avoided.get(candidate_id)) > _number(now):
                retry_candidates.append((_number(avoided[candidate_id]), candidate))
            else:
                candidates.append(candidate)
        # Changing route names does not clear the physical pocket. Respect
        # failed-route leases even when every alternative has been tried;
        # local checked recovery continues while the earliest lease expires.
        trace['entry_selection'] = dict(sampled_at=_number(now), origin=dict(point),
            policy='existing_affinity_then_nearest_route_point', candidates=entry_receipts)
        if not candidates and retry_candidates:
            trace['retry_after'] = min(value[0] for value in retry_candidates)
        if not candidates:
            trace['action'] = 'no_alternative'
            # No suitable alternative: keep the physical hold, never force
            # through a wreck or repeat a route-switch storm each tick.
            progress['since'] = _number(now)
            return
        chosen = min(candidates, key=lambda value: value[:3])
        route, entry = chosen[3:]
        self._record_route_assignment(bot, now, route_id, route.get('id'), 'wreck_stall')
        self._route_assignment_receipts[bot_id]['entry_selection'] = dict(
            sampled_at=_number(now), origin=dict(point),
            policy='existing_affinity_then_nearest_route_point',
            candidates=entry_receipts, selected_route=str(route.get('id')),
            selected_index=entry, selected_point=_point(route['waypoints'][entry]))
        self._route_assignments[bot_id] = {
            'route': route, 'until': 0.0}
        # Join the evaluated entry from the current hull position, rather than
        # restoring a stale failed cursor from an earlier visit to this lane.
        saved = self._route_history.get(bot_id, {}).get(str(route.get('id'))) or {}
        self._route_states[bot_id] = dict(
            route_id=str(route.get('id')), index=entry, join_index=entry,
            join_anchor=dict(point),
            parking_completed=set(saved.get('parking_completed', ())),
            parking_skipped=set(saved.get('parking_skipped', ())))
        self._wreck_route_progress.pop(bot_id, None)
        new_id, index, move, anchor, join = self._route(bot, now)
        order.update(route_id=new_id, route_index=index,
                     combat_mode='route', parking_phase=None,
                     parking_slot=None, arrival_radius=None,
                     move_position=move, face_position=dict(move),
                     route_anchor=anchor, route_join=join,
                     route_switch_reason='wreck_stall' if physical_block else 'no_route_progress',
                     previous_route_id=route_id)
        trace.update(action='switch_route', next_route=new_id, next_index=index)
        self._apply_authored_route_order(order, bot, move, now)

    def _route(self, bot, now):
        if bot['id'] in self._travel_tasks:
            return self._task_position(bot, now)
        if bot['id'] in self._route_recoveries:
            return self._cycle_position(bot, now)
        assignment = self._route_assignments.get(bot["id"])
        route = assignment.get("route") if isinstance(assignment, dict) else None
        if not isinstance(route, dict):
            route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
        waypoints = route.get("waypoints") if isinstance(route.get("waypoints"), list) else []
        if not waypoints:
            route_ids = ("left_flank", "center_line", "right_flank")
            route_id = route_ids[(bot["slot"] + bot["id"]) % len(route_ids)]
            side = -1.0 if route_id == "left_flank" else (1.0 if route_id == "right_flank" else 0.0)
            direction = 1.0 if bot["team"] == 1 else -1.0
            point = {"x": round(side * 115.0, 3), "y": 0.0,
                     "z": round(direction * 18.0, 3)}
            return route_id, 0, point, point, False
        route_id = str(route.get("id") or "uploaded_route")
        authored = bot_tactics.route_config(
            self.tactics, self.tactics_map, route_id, bot['team'], waypoints)
        scripted = authored is not None and (not authored.get('default') or
                    any(len(p) > 3 for p in authored['points']))
        route_limit = len(waypoints) - 1
        state = self._route_states.get(bot["id"])
        history = self._route_history.setdefault(bot['id'], {})
        if scripted and (state is None or state.get('route_id') != route_id):
            saved = history.get(route_id)
            if saved is not None:
                state = dict(index=saved['index'],route_id=route_id,
                    entry_receipt=dict(sampled_at=now, source='restored_scripted_index',
                        position=_point(bot['state']), selected_index=saved['index'],
                        speed=_number(bot['state'].get('speed')),
                        yaw=_number(bot['state'].get('yaw')), skipped=[]),
                    parking_completed=set(saved.get('parking_completed', ())),
                    parking_skipped=set(saved.get('parking_skipped', ())),
                    blocked_skip_to=saved.get('blocked_skip_to'),
                    join_index=saved['index'],join_anchor=_point(bot['state']))
                self._route_states[bot['id']] = state
        if state is None or state.get("route_id") != route_id:
            bx = _number(bot["state"].get("x"))
            bz = _number(bot["state"].get("z"))
            nearest = min(range(len(waypoints)), key=lambda value:
                          (_number(waypoints[value].get("x")) - bx) ** 2 +
                          (_number(waypoints[value].get("z")) - bz) ** 2)
            index = nearest
            entry = dict(sampled_at=now, source='nearest_route_point',
                         position=_point(bot['state']), nearest=nearest,
                         speed=_number(bot['state'].get('speed')),
                         yaw=_number(bot['state'].get('yaw')), skipped=[])
            # Route point zero is the team's own flag. The actual line-up starts
            # in front of it, so do not order every deployed tank to turn around
            # and visit its own base before it may advance toward the enemy flag.
            if nearest == 0 and len(waypoints) > 1:
                index = 1
                entry['skipped'].append(dict(index=0, reason='spawn_flag'))
            index = min(index, route_limit)
            while (index < route_limit and
                   math.hypot(_number(waypoints[index].get("x")) - bx,
                              _number(waypoints[index].get("z")) - bz) <= ROUTE_ARRIVAL_RADIUS):
                entry['skipped'].append(dict(index=index, reason='inside_arrival_disk'))
                index += 1
            # Bot snapshots carry hull yaw in the same shared frame as uploaded
            # routes. Skip only a truly rear-facing connector; a side road remains a
            # valid lane opening and must not be flattened into the next macro point.
            #
            # A parked hull's yaw is a parking orientation, not a travel
            # direction, so there is nothing for a connector to be "behind" yet.
            # Applying the filter at the spawn discarded the authored first
            # connector on 246 of the 1230 shipped spawn slots across 33 of the
            # 41 baked maps - a median of 58 m away - and sent those tanks
            # straight at a farther macro point instead of down the reviewed
            # lane. Turning in place is cheap; leaving the authored egress is
            # not.
            # Positive longitudinal speed proves that hull yaw is the current
            # route direction. Negative speed is a temporary reverse recovery,
            # not a request to abandon the nearest connector behind that yaw.
            if _number(bot["state"].get("speed")) > 0.5:
                yaw = _number(bot["state"].get("yaw"))
                while index < route_limit:
                    point = waypoints[index]
                    bearing = math.atan2(_number(point.get("x")) - bx,
                                         _number(point.get("z")) - bz)
                    delta = ((bearing - yaw + math.pi) %
                             (math.pi * 2.0) - math.pi)
                    if abs(delta) <= 1.75:
                        break
                    entry['skipped'].append(dict(index=index,
                        reason='behind_moving_hull', bearing=bearing, delta=delta))
                    index += 1
            # User point zero is an instruction, not a baked base connector.
            if not history and scripted:
                index = 0
                entry['source'] = 'first_scripted_instruction'
            if authored is not None and not history and len(waypoints)>1 and not authored['points'][0][2]:
                index=min(1,route_limit)
                entry['source']='fixed_spawn_next_node'
            entry.update(selected_index=index, selected_point=_point(waypoints[index]))
            state = {"index": index, "route_id": route_id,
                     "entry_receipt": entry,
                     "join_index": index,
                     "join_anchor": {"x": bx,
                                     "y": _number(bot["state"].get("y")),
                                     "z": bz}}
            self._route_states[bot["id"]] = state
        # The pinned route geometry is immutable for this round. Keep progress
        # and completed waits when temporary assignments retire the active state.
        history[route_id] = state
        requested_limit = route_limit
        previous_index = max(0, _integer(state.get('index')))
        index = min(max(0, _integer(state.get("index"))), route_limit)
        state["index"] = index
        point = _point(waypoints[index])
        bx = _number(bot["state"].get("x"))
        bz = _number(bot["state"].get("z"))
        grounded_observation = bool(bot['state'].get('world_pose') and
                                    not bot['state'].get('airborne'))
        previous_pose = (state.get('arrival_previous_pose') if
                         grounded_observation and state.get('arrival_previous_grounded') and
                         0.0 < now-state.get('arrival_previous_at', now-3.0) <= 2.0 else None)
        state['arrival_previous_pose'] = (bx, bz)
        state['arrival_previous_at'] = now
        state['arrival_previous_grounded'] = grounded_observation
        # Macro points describe the lane, not parking places.  Tanks keep
        # advancing until combat, safety or the final destination stops them.
        # Consume every already-reached adjacent gate in this one 1 Hz global
        # tactics pass; otherwise a short next segment makes LocalDriver stop
        # at it until the following planner tick.
        state["holding"] = False
        state.pop('parking_phase', None)
        state.pop('parking_slot', None)
        while True:
            authored_point = authored['points'][index] if authored is not None else ()
            places = bot_tactics.waiting_positions(authored_point)
            if places:
                completed, parking = self._wait_parking(bot, state, route_id, index, places, now)
                if not completed:
                    point = parking
                    break
                if (index in state.get('parking_skipped', ()) and
                        not _route_point_reached(bx, bz, waypoints, index, route_limit, previous_pose)):
                    break
            elif not _route_point_reached(bx, bz, waypoints, index, route_limit, previous_pose):
                break
            if index >= route_limit:
                if (index == len(waypoints)-1 and grounded_observation and
                        not bot['state'].get('route_wreck_blocked') and
                        (authored is not None or len(waypoints)>1)):
                    state['terminal_crossing'] = dict(point=_point(waypoints[index]), at=now)
                break
            index += 1
            state['index'] = index
            point = _point(waypoints[index])
        if (state.get('blocked_skip_to') != index or
                state.get('parking_phase') == 'waiting'):
            state.pop('blocked_skip_to', None)
        route_join = (state.get("join_index") == index and
                      isinstance(state.get("join_anchor"), dict))
        if route_join:
            anchor = _point(state["join_anchor"])
        else:
            anchor = _point(waypoints[max(0, index - 1)])
        state['progress_receipt'] = dict(at=now, route_id=route_id,
            entry=state.get('entry_receipt'),

            requested_limit=requested_limit, effective_limit=route_limit,
            previous_index=previous_index, selected_index=index,
            point=dict(point), anchor=dict(anchor), route_join=route_join,
            outcome='normal_progress')
        return route_id, index, point, anchor, route_join

    def _handoff_route_terminal(self, order, bot, capture_target, now):
        """Retire completed macro travel, without consuming local path corners."""
        route = (self._route_assignments.get(bot['id']) or {}).get('route') or bot.get('route') or {}
        points = route.get('waypoints') or []
        route_state = self._route_states.get(bot['id'])
        evidence = dict(at=now, route_id=order.get('route_id'),
            route_index=order.get('route_index'), terminal_index=len(points)-1,
            input_mode=order.get('combat_mode'), outcome='no_route')
        order['tactical_evidence']['route_terminal'] = evidence
        if bot['id'] in self._route_recoveries or bot['id'] in self._travel_tasks:
            evidence['outcome'] = 'route_recovery_in_progress'
            return
        if not points or route_state is None:
            if order.get('combat_mode') == 'base_capture' and capture_target:
                arrived = self._inside_base(bot, capture_target)
                evidence.update(arrival_kind='circle', inside_capture=arrived,
                    circle_radius=capture_target['radius'],
                    outcome='base_capture' if arrived else 'outside_arrival')
                if arrived:
                    order.update(move_position=_point(bot['state']),
                        face_position=_point(bot['state']), throttle_override=0.0,
                        route_join=False)
            return
        capture = order.get('combat_mode') == 'base_capture'
        goal = _point(capture_target['point'] if capture and capture_target else points[-1])
        pose = bot['state']
        position = _point(pose)
        distance = math.hypot(goal['x']-position['x'], goal['z']-position['z'])
        # Authored route disks share the editor's six-metre radius. Keep the
        # precise automatic one-point goal and native local corners separate.
        arrival = self._route_arrival_radius(route, bot['team'])
        inside_capture = bool(capture_target and math.hypot(
            capture_target['point']['x']-position['x'],
            capture_target['point']['z']-position['z']) <= capture_target['radius'])
        final = _point(points[-1])
        final_inside = bool(capture_target and math.hypot(
            final['x']-capture_target['point']['x'],
            final['z']-capture_target['point']['z']) <= capture_target['radius'])
        circle_arrival = capture or final_inside
        arrived = inside_capture if circle_arrival else (distance <= arrival or
            (route_state.get('terminal_crossing') or {}).get('point') == final)
        evidence.update(goal=goal, distance=distance, arrival_radius=arrival,
                        inside_capture=inside_capture, final_inside_capture=final_inside,
                        arrival_kind='circle' if circle_arrival else 'point',
                        circle_radius=capture_target['radius'] if capture_target else None)
        previous = route_state.get('terminal_hold')
        if previous is not None and (previous['goal'] != goal or not arrived):
            route_state.pop('terminal_hold', None)
            evidence['released'] = 'goal_changed' if previous['goal'] != goal else 'outside_arrival'
        if not arrived:
            if (not capture and not final_inside and capture_target and
                    route_state.get('completed_terminal') == final and
                    order.get('combat_mode') in ('route', 'advance') and
                    not order.get('target_id') and not order.get('team_command') and
                    not order.get('parking_phase') and not route_state.get('holding') and
                    order.get('move_position') == final):
                self._apply_base_capture_order(order, bot, capture_target)
                evidence['outcome'] = 'completed_terminal_to_base'
                return
            evidence['outcome'] = 'outside_arrival'
            return
        if (order.get('team_command') or order.get('parking_phase') or
                route_state.get('holding') or
                order.get('combat_mode') not in ('route', 'advance', 'base_capture')):
            evidence['outcome'] = 'tactical_owner'
            return
        if (not capture and (order.get('route_index') != len(points)-1 or
                route_state.get('index') != len(points)-1)):
            evidence['outcome'] = 'intermediate_point'
            return
        requested = order.get('move_position') or {}
        if math.hypot(_number(requested.get('x'))-goal['x'],
                      _number(requested.get('z'))-goal['z']) > 0.01:
            # Cover, shot-lane repositioning and explicit goals have separate
            # arrival owners; being near the old lane end cannot cancel them.
            evidence['outcome'] = 'different_destination'
            return
        if (not pose.get('world_pose') or pose.get('airborne') or
                pose.get('route_wreck_blocked') or capture and not inside_capture):
            evidence['outcome'] = 'physical_or_capture_not_arrived'
            return
        route_state['completed_terminal'] = final
        if not capture and capture_target and not final_inside and order.get('target_id') is None:
            # Complete a lane outside the circle before handing travel to the
            # objective. A combat or authored parking owner still takes priority.
            self._apply_base_capture_order(order, bot, capture_target)
            evidence['outcome'] = 'terminal_to_base'
            return
        hold = route_state.get('terminal_hold')
        if hold is None:
            hold = dict(goal=goal, position=position, arrived_at=now)
            route_state['terminal_hold'] = hold
        order['move_position'] = dict(hold['position'])
        order['throttle_override'] = 0.0
        order['route_join'] = False
        if order.get('target_id') is not None:
            # Target selection and launch permission were already decided.
            # Keep both, even while reloading or a native lane is obstructed.
            order['combat_mode'] = 'engage'
            self._apply_stationary_angling(order, bot, bot['profile'], order['personality'])
        else:
            order['combat_mode'] = 'base_capture' if capture else 'hold'
            # No enemy requires a hull turn back toward the base coordinate.
            # The turret may retain its existing route/capture aiming intent.
            order['face_position'] = position
        evidence.update(outcome=order['combat_mode'], arrived_at=hold['arrived_at'],
                        hold_position=dict(order['move_position']),
                        target_id=order.get('target_id'),
                        fire_allowed=order['fire_allowed'])

    def _wait_place_occupied(self, bot_id, place, radius, height):
        """Physical occupancy includes humans, with distinct identity domains."""
        for body in getattr(self, '_wait_bodies', ()):
            if (body.get('parking_kind') == 'bot' and body.get('id') == bot_id or
                    body.get('world_pose') is not True):
                continue
            shape = body.get('collision_shape')
            other_radius = (math.hypot(shape[0], shape[1]) if shape else
                _number(body.get('parking_radius'), math.hypot(3.5, 1.7)))
            if (abs(_number(body.get('y')) - height) <= max(3.0, radius) and
                    math.hypot(place[0]-_number(body.get('x')),
                               place[1]-_number(body.get('z'))) < radius + other_radius + 0.5):
                return True
        return False

    def _wait_parking(self, bot, state, route_id, index, places, now):
        """Lease one stable parking goal per hull, with individual arrival clocks."""
        bot_id = bot['id']
        radius = max(0.5, _number(bot.get('profile', {}).get('parking_radius'), math.hypot(3.5, 1.7)))
        stage = (bot['team'], route_id, index)
        completed = state.setdefault('parking_completed', set())
        if index in completed:return True, None
        key = next((key for key, claim in self._wait_claims.items()
                    if key[:3] == stage and claim['bot_id'] == bot_id), None)
        pose = bot['state']
        arrived = state.setdefault('parking_arrived', {}).get(index)
        arrival = state.get('parking_pose', {}).get(index)
        if arrived is not None and arrival is not None:
            # The six-metre disk admits the initial arrival. A small external shove
            # must not restart the clock or demand an exact coordinate return.
            displaced = math.hypot(_number(pose.get('x'))-arrival['x'],
                                   _number(pose.get('z'))-arrival['z'])
            safe = (not pose.get('airborne') and displaced <= radius * 2.0 and
                    abs(_number(pose.get('y'))-arrival['y']) <=
                    1.0 + displaced * math.tan(math.radians(27.5)))
            duration = state['parking_duration'][index]
            if duration >= 0 and now-arrived >= duration:
                completed.add(index)
                state.pop('parking_phase', None)
                state.pop('parking_slot', None)
                if key is not None:self._wait_claims[key]['departing'] = True
                return True, None
            if safe:
                state['holding'] = True
                state['parking_phase'] = 'waiting'
                if key is not None:self._wait_claims[key]['point'] = [_number(pose.get('x')), _number(pose.get('z'))]
                return False, _point(pose)
        if key is not None and self._wait_place_occupied(
                bot_id, places[key[3]], radius, _number(pose.get('y'))):
            self._wait_claims.pop(key, None)
            key = None
        if key is None:
            for slot, place in enumerate(places):
                candidate = stage + (slot,)
                if candidate in self._wait_claims:continue
                if self._wait_place_occupied(bot_id, place, radius, _number(pose.get('y'))):continue
                # Separate reservations also protect crossing class routes.
                if any(claim['bot_id'] != bot_id and
                       math.hypot(place[0]-claim['point'][0], place[1]-claim['point'][1]) < radius + claim['radius'] + 2.0
                       for claim in self._wait_claims.values()):continue
                key = candidate
                self._wait_claims[key] = dict(bot_id=bot_id, point=list(place[:2]), radius=radius)
                break
        if key is None:
            # No queue: this hull travels through the parent gate normally.
            # Do not reacquire a slot later while crossing this same gate.
            completed.add(index)
            state.setdefault('parking_skipped', set()).add(index)
            state['holding'] = False
            state.pop('parking_phase', None)
            state.pop('parking_slot', None)
            return True, None
        state['parking_slot'] = key[3]
        state['parking_phase'] = 'approach'
        place = places[key[3]]
        goal = dict(x=place[0], y=_number(bot['state'].get('y')), z=place[1])
        distance = math.hypot(goal['x']-_number(bot['state'].get('x')),
                              goal['z']-_number(bot['state'].get('z')))
        if (pose.get('airborne') or distance > ROUTE_ARRIVAL_RADIUS or
                (arrival is not None and abs(_number(pose.get('y'))-arrival['y']) >
                 1.0 + distance * math.tan(math.radians(27.5)))):return False, goal
        arrived = state.setdefault('parking_arrived', {}).setdefault(index, now)
        state.setdefault('parking_pose', {})[index] = _point(pose)
        duration = state.setdefault('parking_duration', {}).setdefault(index, place[2])
        if duration < 0 or now-arrived < duration:
            state['holding'] = True
            state['parking_phase'] = 'waiting'
            return False, goal
        completed.add(index)
        state.pop('parking_phase', None)
        state.pop('parking_slot', None)
        # Keep the lease until the hull has driven clear of the parking place.
        self._wait_claims[key]['departing'] = True
        return True, None

    def _apply_authored_route_order(self, order, bot, route_point, now=None):
        """Apply explicit parking/travel instructions without suppressing aim."""
        if bot['id'] in self._route_recoveries or bot['id'] in self._travel_tasks:
            return
        if order.get('defense_base_id') or order.get('combat_mode') == 'base_capture':
            return
        route = (self._route_assignments.get(bot['id']) or {}).get('route') or bot.get('route') or {}
        authored = bot_tactics.route_config(
            self.tactics, self.tactics_map, order.get('route_id'), bot['team'], route.get('waypoints'))
        if authored is None:
            return
        scripted = ((bot['profile'].get('class_tag') == 'SPG' and
                    (not authored.get('default') or authored.get('class_tag') == 'SPG')) or
                    any(len(point) > 3 for point in authored['points']))
        if not scripted:
            return
        holding = (self._route_states.get(bot['id']) or {}).get('holding', False)
        state = self._route_states.get(bot['id']) or {}
        phase = state.get('parking_phase')
        if (not holding and phase not in ('approach', 'waiting', 'queue') and
                bot['profile'].get('class_tag') != 'SPG'):
            # The authored route already supplies normal travel waypoints.
            # Once a wait ends, restore ordinary combat/retreat ownership;
            # replacing an engage order with route mode also disables the
            # worker's stationary fixed-gun hull laying.
            return
        order['move_position'] = dict(route_point)
        order['parking_phase'] = phase
        order['parking_slot'] = state.get('parking_slot')
        if phase == 'waiting':
            index=state.get('index',0);points=authored['points']
            places=bot_tactics.waiting_positions(points[index]);slot=state.get('parking_slot')
            done=state.setdefault('parking_heading_done',set())
            if slot is not None and slot<len(places) and index not in done:
                following=points[index+1] if index+1<len(points) else None
                heading=bot_tactics.waiting_heading(places[slot],following)
                elapsed=0 if now is None else now-state.get('parking_arrived',{}).get(index,now)
                if heading is None or order.get('target_id') is not None or elapsed>=5.0:
                    done.add(index)
                else:
                    angle=math.radians(heading);pose=bot['state']
                    delta=math.atan2(math.sin(angle-_number(pose.get('yaw'))),math.cos(angle-_number(pose.get('yaw'))))
                    if abs(delta)<0.05:done.add(index)
                    else:
                        order['parking_heading']=heading
                        order['face_position']=dict(x=_number(pose.get('x'))+math.sin(angle)*20,
                            y=_number(pose.get('y')),z=_number(pose.get('z'))+math.cos(angle)*20)
        order['arrival_radius'] = ROUTE_ARRIVAL_RADIUS if phase == 'approach' else None
        order['combat_mode'] = 'hold' if holding else 'parking_approach' if phase == 'approach' else 'route'
        order['throttle_override'] = 0.0 if holding else None

    def _retreat_point(self, bot, route_anchor):
        """Return the previous graph-validated route point when available."""
        assignment = self._route_assignments.get(bot["id"])
        route = assignment.get("route") if isinstance(
            assignment, dict) else None
        if not isinstance(route, dict):
            route = bot.get("route") if isinstance(bot.get("route"), dict) else {}
        waypoints = route.get("waypoints")
        route_state = self._route_states.get(bot["id"])
        if (not isinstance(waypoints, list) or not waypoints or
                not isinstance(route_state, dict)):
            return dict(route_anchor)
        index = min(max(0, _integer(route_state.get("index"))),
                    len(waypoints) - 1)
        if (route_state.get("join_index") == index and
                isinstance(route_state.get("join_anchor"), dict)):
            # An off-route vehicle has only proved the connector from its
            # actual join anchor.  Once it has made useful progress on that
            # connector, retreat along the proved segment rather than cutting
            # toward an unrelated macro point.
            join_anchor = _point(route_state["join_anchor"])
            if (math.hypot(
                    join_anchor["x"] - _number(bot["state"].get("x")),
                    join_anchor["z"] - _number(bot["state"].get("z"))) >
                    RETREAT_ARRIVAL_RADIUS):
                return join_anchor
        return _point(waypoints[max(0, index - 1)])

    @staticmethod
    def _flank_shooters(contact, team_bots):
        shooter_ids = set(_integer(value) for value in
                          (contact.get("shootable_by_bot_ids") or ()))
        assigned_ids = contact.get("assigned_shooter_ids")
        if isinstance(assigned_ids, (list, tuple)):
            shooter_ids.intersection_update(
                _integer(value) for value in assigned_ids)
        return [ally for ally in (team_bots or ())
                if ally["id"] in shooter_ids and
                BotPlanner._weapon_ready(ally)]

    @staticmethod
    def _should_flank(bot, contact, team_bots):
        """Keep a firing element in place and move only half the shooters."""
        shooters = BotPlanner._flank_shooters(contact, team_bots)
        if len(shooters) < 2:
            return False
        if bot["id"] in (contact.get("flank_suppressor_bot_ids") or ()):
            return False
        candidates = []
        for ally in shooters:
            profile = ally.get("profile") if isinstance(
                ally.get("profile"), dict) else {}
            roles = profile.get("roles") if isinstance(
                profile.get("roles"), dict) else {}
            initiative = BotPlanner._personality(ally["id"])["initiative"]
            flanker = _number(roles.get("flanker"))
            if flanker < 0.68 or initiative <= 0.42:
                continue
            candidates.append((flanker, initiative, -ally["id"], ally["id"]))
        if not candidates:
            return False
        moving_count = max(1, len(shooters) // 2)
        moving_ids = set(value[-1] for value in
                         sorted(candidates, reverse=True)[:moving_count])
        return bot["id"] in moving_ids and len(moving_ids) < len(shooters)

    @staticmethod
    def _flank_point(bot, contact, desired_range, team_bots=None):
        """Choose the side which opens the widest angle from current guns."""
        bx = _number(bot["state"].get("x"))
        bz = _number(bot["state"].get("z"))
        tx = contact["position"]["x"]
        tz = contact["position"]["z"]
        dx, dz = bx - tx, bz - tz
        length = math.hypot(dx, dz) or 1.0
        dx, dz = dx / length, dz / length
        offset = min(95.0, desired_range * 0.38)
        candidates = []
        for side in (-1.0, 1.0):
            point = _point({
                "x": tx + dx * desired_range * 0.72 + dz * offset * side,
                "y": contact["position"].get("y", 0.0),
                "z": tz + dz * desired_range * 0.72 - dx * offset * side,
            })
            bearing = math.atan2(point["x"] - tx, point["z"] - tz)
            separations = []
            for ally in BotPlanner._flank_shooters(contact, team_bots):
                if ally["id"] == bot["id"]:
                    continue
                state = ally.get("state") if isinstance(
                    ally.get("state"), dict) else {}
                ally_dx = _number(state.get("x")) - tx
                ally_dz = _number(state.get("z")) - tz
                if math.hypot(ally_dx, ally_dz) <= 1.0:
                    continue
                ally_bearing = math.atan2(ally_dx, ally_dz)
                separations.append(abs(
                    (bearing - ally_bearing + math.pi) %
                    (math.pi * 2.0) - math.pi))
            angle = min(separations) if separations else 0.0
            candidates.append((angle, -side, point))
        return max(candidates, key=lambda value: value[:2])[2]

    @staticmethod
    def _shell_index(profile, contact, personality, state=None,
                     plans_shell=True):
        """Use the round-owned result policy, independently of difficulty."""
        from gui.mods.offline_lan_0922.ammo_policy import ordered
        state = state or {}
        shells = ordered(profile, state.get('ammo_remaining'))
        indices = [int(shell['index']) for shell in shells]
        selected = state.get('ammo_policy_shell_index')
        return int(selected) if selected in indices else (indices[0] if indices else 0)

    def _cover_candidate(self, bot, focus, personality, now, urgent=False):
        report = self._affordances.get(bot["id"])
        target_key = (focus.get("target_kind"), focus["id"])
        if (report is None or report.get("target") != target_key or
                _number(now) - _number(report.get("reported_at")) > COVER_TTL_SECONDS):
            self._cover_states.pop(bot["id"], None)
            return None
        weights = {
            "enemy_occlusion": 26.0 + personality["caution"] * 18.0,
            "travel_distance": -0.035 - personality["caution"] * 0.035,
            "escape_feasible": 8.0 + personality["patience"] * 10.0,
            "peek_feasible": 6.0 + personality["aggression"] * 8.0,
        }
        if urgent:
            # A recently hit tank values nearby hard occlusion over a longer,
            # prettier firing position.  The client still proves every point.
            weights["enemy_occlusion"] += 22.0
            weights["exposure"] = -48.0
            weights["travel_distance"] -= 0.045
            weights["escape_feasible"] += 10.0
        ranked = score_candidates(report.get("candidates"), weights)
        usable = [candidate for candidate in ranked
                  if candidate["water"] < 0.5 and candidate["slope"] <= 24.0 and
                  candidate["enemy_occlusion"] >= 0.45 and
                  candidate["peek_feasible"] and candidate["escape_feasible"] and
                  candidate.get("peek_position") is not None]
        failures = self._cover_failures.get(bot["id"], {})
        usable = [candidate for candidate in usable
                  if _number(failures.get(candidate.get("id"))) <=
                  _number(now)]
        if not usable:
            self._cover_states.pop(bot["id"], None)
            return None
        current = self._cover_states.get(bot["id"])
        selected = None
        if (current is not None and current.get("target") == target_key and
                not current.pop("refresh_candidate", False)):
            current_id = current.get("candidate_id")
            for candidate in usable:
                if candidate.get("id") == current_id:
                    selected = candidate
                    current["candidate"] = candidate
                    break
        if selected is None:
            for candidate in usable:
                point = candidate["position"]
                reservation = (int(round(point["x"] / 8.0)),
                               int(round(point["z"] / 8.0)))
                if reservation not in self._cover_reservations:
                    selected = candidate
                    break
            if selected is None:
                selected = usable[0]
            current = {
                "target": target_key,
                "candidate_id": selected["id"],
                "candidate": selected,
                "phase": "approach",
                "phase_until": 0.0,
                "phase_started_at": _number(now),
                "best_distance": math.hypot(
                    selected["position"]["x"] -
                    _number(bot["state"].get("x")),
                    selected["position"]["z"] -
                    _number(bot["state"].get("z"))),
                "last_progress_at": _number(now),
            }
            self._cover_states[bot["id"]] = current
        point = selected["position"]
        self._cover_reservations.add((int(round(point["x"] / 8.0)),
                                      int(round(point["z"] / 8.0))))
        return selected, current

    @staticmethod
    def _begin_cover_phase(state, phase, now, distance=0.0):
        state["phase"] = phase
        state["phase_until"] = 0.0
        state["phase_started_at"] = _number(now)
        state["best_distance"] = max(0.0, _number(distance))
        state["last_progress_at"] = _number(now)

    @staticmethod
    def _cover_phase_timed_out(state, distance, now):
        if (distance + COVER_PROGRESS_EPSILON <
                _number(state.get("best_distance"), distance)):
            state["best_distance"] = distance
            state["last_progress_at"] = _number(now)
        return bool(
            _number(now) - _number(state.get("last_progress_at")) >=
            COVER_PROGRESS_TIMEOUT_SECONDS)

    def _reject_cover_candidate(self, bot_id, candidate_id, now):
        failures = self._cover_failures.setdefault(bot_id, {})
        failures[candidate_id] = (
            _number(now) + COVER_CANDIDATE_RETRY_SECONDS)
        self._cover_states.pop(bot_id, None)

    def _apply_cover_order(self, order, bot, focus, personality, now,
                           urgent=False, hold_only=False):
        # One engagement is one decision to use cover, so the answer cannot
        # change between the approach and the return and leave a Bot driving
        # in and out of the same position. Reaching for hard cover under fire
        # is a different, easier competence than choosing a firing position.
        capability = (bot_gunnery.CAPABILITY_URGENT_COVER
                      if urgent or hold_only
                      else bot_gunnery.CAPABILITY_TACTICAL_COVER)
        if not self._capable(bot, capability, focus.get("target_kind"),
                             focus.get("id")):
            self._cover_states.pop(bot["id"], None)
            return False
        selected_state = None
        for unused_attempt in range(2):
            selected_state = self._cover_candidate(
                bot, focus, personality, now, urgent=urgent or hold_only)
            if selected_state is None:
                return False
            candidate, state = selected_state
            bx = _number(bot["state"].get("x"))
            bz = _number(bot["state"].get("z"))
            cover = candidate["position"]
            peek = candidate["peek_position"]
            cover_distance = math.hypot(
                cover["x"] - bx, cover["z"] - bz)
            peek_distance = math.hypot(
                peek["x"] - bx, peek["z"] - bz)
            phase = state.get("phase", "approach")
            phase_distance = (peek_distance if phase == "peek"
                              else cover_distance)
            if (phase in ("approach", "return", "peek") and
                    phase_distance > 4.5 and
                    self._cover_phase_timed_out(
                        state, phase_distance, now)):
                self._reject_cover_candidate(
                    bot["id"], candidate["id"], now)
                selected_state = None
                continue
            break
        if selected_state is None:
            return False
        if (urgent or hold_only) and phase == "peek":
            phase = "return"
            self._begin_cover_phase(
                state, phase, now, cover_distance)
        if phase in ("approach", "return") and cover_distance <= 4.5:
            completed_return = phase == "return"
            phase = "hold"
            self._begin_cover_phase(state, phase, now, 0.0)
            if completed_return:
                state["refresh_candidate"] = True
            state["phase_until"] = (_number(now) + 0.65 +
                                    personality["patience"] * 1.35)
            state["face_position"] = _point(
                order.get("face_position") or focus["position"])
        elif (phase == "hold" and not urgent and not hold_only and
              _number(now) >= _number(state.get("phase_until")) and
              self._weapon_ready(bot) and
              self._capable(bot, bot_gunnery.CAPABILITY_COVER_PEEK,
                            candidate["id"])):
            phase = "peek"
            self._begin_cover_phase(state, phase, now, peek_distance)
            state["peek_fire_seq"] = _integer(
                bot.get("state", {}).get("fire_seq"))
        elif phase == "peek" and peek_distance <= 4.5:
            bot_state = bot.get("state") if isinstance(
                bot.get("state"), dict) else {}
            fire_seq = _integer(bot_state.get("fire_seq"))
            shot_advanced = fire_seq > _integer(
                state.get("peek_fire_seq"), fire_seq)
            if _number(state.get("phase_until")) <= 0.0:
                state["phase_until"] = (_number(now) + 1.0 +
                                        personality["aggression"] * 1.8)
            if shot_advanced and self._magazine_has_followup(bot):
                state["peek_fire_seq"] = fire_seq
                state["phase_until"] = (
                    _number(now) + max(
                        _number(bot_state.get("reload_time")),
                        1.0 + personality["aggression"] * 1.8))
            elif (shot_advanced or
                  (not bot_state.get("burst_active") and
                   _number(now) >= _number(state.get("phase_until")))):
                phase = "return"
                self._begin_cover_phase(
                    state, phase, now, cover_distance)
        order["cover_id"] = candidate["id"]
        # This flag is permission to shoot, not a claim that the current lane
        # is clear.  The authority client still performs the final per-bot LOS,
        # turret alignment and reload checks.  Keeping it enabled lets a bot
        # engage an exposed target while approaching, holding or leaving cover.
        can_fire = bool(order.get("fire_allowed"))
        if phase == "approach":
            order["combat_mode"] = "take_cover"
            order["move_position"] = dict(cover)
            order["throttle_override"] = 1.0
        elif phase == "hold":
            order["combat_mode"] = "cover_hold"
            order["move_position"] = dict(cover)
            order["face_position"] = dict(state.get(
                "face_position") or order.get("face_position") or cover)
            order["throttle_override"] = 0.0
            order["stable_hull_face"] = True
        elif phase == "peek":
            order["combat_mode"] = "cover_peek"
            order["move_position"] = dict(peek)
            order["throttle_override"] = 1.0 if peek_distance > 4.5 else 0.0
            order["fire_allowed"] = can_fire
        else:
            order["combat_mode"] = "cover_return"
            order["move_position"] = dict(cover)
            order["throttle_override"] = None
        return True

    def _apply_artillery_order(self, order, bot, team_axis):
        self._engage_anchors.pop(bot["id"], None)
        self._cover_states.pop(bot["id"], None)
        anchor = self._artillery_anchor(bot, team_axis)
        point = anchor["point"]
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        distance = math.hypot(point["x"] - _number(state.get("x")),
                              point["z"] - _number(state.get("z")))
        arrived = distance <= anchor.get("parking_radius", 15.0)
        order["combat_mode"] = (
            "artillery_hold" if arrived else "artillery_deploy")
        order["move_position"] = dict(point)
        order["route_index"] = anchor["index"]
        order["route_anchor"] = dict(point)
        order["route_join"] = False
        order["throttle_override"] = 0.0 if arrived else None
        if order.get("target_id") is None:
            order["face_position"] = dict(anchor["face"])

    def _set_target(self, order, bot, contact, profile, personality,
                    fire_allowed):
        order["target_id"] = contact["id"]
        order["target_kind"] = contact.get("target_kind")
        order["aim_position"] = dict(contact["position"])
        order["face_position"] = dict(contact["position"])
        order["fire_allowed"] = bool(
            fire_allowed and BotPlanner._weapon_ready(bot))
        # One engagement is one shell decision. Re-rolling per tick would
        # leave a Bot swapping rounds in front of the same tank.
        order["shell_index"] = BotPlanner._shell_index(
            profile, contact, personality, bot.get("state"),
            plans_shell=True)

    @staticmethod
    def _angled_face_point(bot, target, personality):
        """Return a 12-30 degree hull face point for a stationary turret."""
        bx = _number(bot["state"].get("x"))
        by = _number(bot["state"].get("y"))
        bz = _number(bot["state"].get("z"))
        dx = _number(target.get("x")) - bx
        dz = _number(target.get("z")) - bz
        if math.hypot(dx, dz) <= 0.1:
            return _point(target), 0.0
        degrees = 12.0 + personality["caution"] * 18.0
        if bot["id"] % 2:
            degrees = -degrees
        radians = math.radians(degrees)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        return _point({
            "x": bx + dx * cosine - dz * sine,
            "y": by,
            "z": bz + dx * sine + dz * cosine,
        }), round(degrees, 3)

    @staticmethod
    def _may_angle_hull(profile):
        roles = profile.get("roles") if isinstance(
            profile.get("roles"), dict) else {}
        return bool(
            str(profile.get("class_tag") or "") in (
                "heavyTank", "mediumTank", "lightTank") and
            (_number(profile.get("armor")) >= 60.0 or
             _number(roles.get("brawler")) >= 0.55))

    def _apply_stationary_angling(self, order, bot, profile, personality):
        # Adjacent stationary combat modes share one target-relative anchor.
        # Without this, support_hold and engage use different hull policies
        # and a one-metre range wobble turns into visible left/right pivots.
        if (order.get("combat_mode") not in (
                    "engage", "support_hold", "low_health_retreat",
                    "under_fire_withdraw", "crossfire_withdraw") or
                _number(order.get("throttle_override"), 1.0) != 0.0 or
                not order.get("fire_allowed") or
                not self._may_angle_hull(profile) or
                not self._capable(
                    bot, bot_gunnery.CAPABILITY_HULL_ANGLING)):
            return
        target_key = (order.get("target_kind"), order.get("target_id"))
        anchor = self._engage_anchors.get(bot["id"])
        if (not isinstance(anchor, dict) or
                anchor.get("target") != target_key or
                not isinstance(anchor.get("face_position"), dict)):
            point, degrees = self._angled_face_point(
                bot, order.get("aim_position") or {}, personality)
            anchor = {
                "target": target_key,
                "position": _point(bot["state"]),
                "face_position": point,
                "hull_angle_degrees": degrees,
            }
            self._engage_anchors[bot["id"]] = anchor
        point = anchor.get("face_position")
        degrees = _number(anchor.get("hull_angle_degrees"))
        if abs(degrees) <= 0.01:
            return
        order["move_position"] = dict(anchor["position"])
        order["face_position"] = point
        order["hull_angle_degrees"] = degrees
        # Current workers ignore this marker.  It is intentionally included in
        # the wire order so the live-pose overlay can preserve this server-
        # leased hull heading while still updating the turret aim position.
        order["stable_hull_face"] = True

    def _order_for(self, bot, index, count, focus, contacts, now,
                   travel_override=None, team_axis=None, team_bots=None,
                   capture_target=None, no_known_enemies=False, active_capture=False):
        route_id, route_index, move, route_anchor, route_join = self._route(bot, now)
        retreat_point = self._retreat_point(bot, route_anchor)
        profile = dict(bot["profile"])
        desired_range = max(10.0, _number(profile.get("desired_range"), 180.0))
        fire_range = max(desired_range, _number(profile.get("fire_range"), 500.0))
        personality = self._personality(bot["id"])
        state = bot.get("state") if isinstance(bot.get("state"), dict) else {}
        health_fraction = (_number(state.get("health"), 1.0) /
                           max(1.0, _number(state.get("max_health"), 1.0)))
        recent_hit = self._recent_hit(bot["id"], now)
        threat_contact = self._recent_threat_contact(bot, contacts, now)
        magazine_followup = self._magazine_has_followup(bot)
        magazine_reload = bool(
            _integer(state.get('clip_size'), 1) > 1 and
            _integer(state.get('clip')) <= 0 and
            _integer(state.get('fire_seq')) > 0 and
            self._weapon_can_recover(bot))
        retreat = self._retreat_states.get(bot['id'])
        retreat_before = dict(retreat or {})
        retreat_release = None
        if retreat is not None and (
                retreat.get('moving_mode') != 'magazine_reload_retreat' or
                not magazine_reload or active_capture):
            retreat_release = ('active_capture_reload' if active_capture else
                'magazine_ready_or_exhausted'
                if retreat.get('moving_mode') == 'magazine_reload_retreat' else
                'retreat_trigger_removed')
            self._retreat_states.pop(bot['id'], None)
        order = {
            "id": bot["id"],
            "team": bot["team"],
            "target_id": None,
            "aim_position": None,
            "face_position": None,
            "move_position": move,
            "fire_allowed": False,
            "combat_mode": "route",
            # The local driver owns safety and steering.  A normal route must
            # not replace its full throttle with a server-side cruise limit.
            "throttle_override": None,
            "desired_range": round(desired_range, 3),
            "fire_range": round(fire_range, 3),
            "route_id": route_id,
            "route_index": route_index,
            "route_anchor": dict(route_anchor),
            "route_join": bool(route_join),
            # Internal inputs for direct radio movement overlays. Tactical
            # roles may replace the public movement fields before that overlay.
            "_route_position": dict(move),
            "_turnback_position": dict(retreat_point),
            "personality": personality,
            "profile": profile,
            "shell_index": 0,
        }
        order['tactical_evidence'] = dict(at=now,
            clock_basis='server_monotonic_seconds',
            selection=dict(self._target_decisions.get(bot['id']) or
                dict(at=now, outcome='direct_order_call', candidates=[], selected=None)),
            focus=(focus.get('target_kind'), focus['id']) if focus is not None else None,
            recent_hit=dict(recent_hit or {}), withdraw_after_hit=False,
            withdrawal=dict(reason='empty_magazine_only',
                magazine_followup=magazine_followup, magazine_reload=magazine_reload,
                active_capture=bool(active_capture),
                released=retreat_release,
                clip=state.get('clip'), clip_size=state.get('clip_size'),
                reload_time=state.get('reload_time'), fire_seq=state.get('fire_seq')),
            threat=(threat_contact.get('target_kind'), threat_contact['id'])
                if threat_contact is not None else None,
            health_fraction=health_fraction,
            weapon_ready=self._weapon_ready(bot),
            retreat_before=retreat_before)
        if travel_override is not None:
            if focus is not None:
                observers = focus.get("shootable_by_bot_ids")
                self._set_target(
                    order, bot, focus, profile, personality,
                    bool(focus.get("visible") and
                         (bot["id"] in (observers or ()) or
                          str(profile.get('class_tag') or '') == 'SPG' and
                          self._inside_base(bot, travel_override))))
            self._apply_base_defense_order(order, bot, travel_override)
            self._firing_holds.pop(bot["id"], None)
            return order
        artillery_only = (str(profile.get('class_tag') or '') == 'SPG' and
            team_bots and all(str(b.get('profile', {}).get('class_tag') or '') == 'SPG'
                              for b in team_bots))
        route_state = self._route_states.get(bot['id']) or {}
        capture_wait = (route_state.get('holding') or
                        route_state.get('parking_phase') in ('approach', 'waiting', 'queue'))
        # Missing ordinary SPG routes are intentional, not completed attack
        # corridors. Only the artillery endgame admits its capture approach.
        if (no_known_enemies and capture_target is not None and not capture_wait and
                (artillery_only or str(profile.get('class_tag') or '') != 'SPG' and
                 self._capture_staged(bot, route_index, capture_target))):
            self._apply_base_capture_order(order, bot, capture_target)
            self._firing_holds.pop(bot["id"], None)
            return order
        if str(profile.get("class_tag") or "") == "SPG":
            if focus is not None:
                # This flag admits an attempt, not an unchecked launch. The
                # worker still requires a current family solution, alignment,
                # ammunition, exact native arc proof and friendly clearance.
                # An expired advisory must not cancel that pending proof.
                self._set_target(
                    order, bot, focus, profile, personality,
                    bool(focus.get("visible")))
            self._apply_artillery_order(order, bot, team_axis)
            self._firing_holds.pop(bot["id"], None)
            return order

        if active_capture and magazine_reload:
            # Canonical capture membership includes newly entered and hit-reset
            # contributors with zero points. Reload in place, retaining aim.
            if focus is not None:
                self._set_target(order, bot, focus, profile, personality, False)
            order.update(combat_mode='magazine_reload_hold',
                         move_position=_point(state), throttle_override=0.0)
            self._firing_holds.pop(bot['id'], None)
            return order

        if magazine_reload and (focus is not None or
                (self._retreat_states.get(bot['id']) or {}).get('moving_mode') ==
                'magazine_reload_retreat'):
            if focus is not None:
                self._set_target(order, bot, focus, profile, personality, False)
                # Return to an already proved cover position before using
                # the route retreat endpoint. Do not discard the cover owner.
                if (bot['id'] in self._cover_states and self._apply_cover_order(
                        order, bot, focus, personality, now, urgent=True)):
                    self._retreat_states.pop(bot['id'], None)
                    self._firing_holds.pop(bot['id'], None)
                    return order
            self._engage_anchors.pop(bot['id'], None)
            self._combat_states.pop(bot['id'], None)
            self._cover_states.pop(bot['id'], None)
            self._apply_retreat_order(order, bot, retreat_point,
                focus['position'] if focus is not None else
                self._retreat_states[bot['id']]['face'], now,
                'magazine_reload_retreat', 'magazine_reload_hold')
            self._firing_holds.pop(bot['id'], None)
            return order

        if focus is None:
            self._engage_anchors.pop(bot["id"], None)
            self._combat_states.pop(bot["id"], None)
            retreat = self._retreat_states.get(bot['id'])
            if retreat is not None and retreat.get('phase') in ('withdraw', 'hold'):
                self._apply_retreat_order(order, bot, retreat['target_point'],
                    retreat['face'], now, retreat['moving_mode'], retreat['hold_mode'])
                self._firing_holds.pop(bot['id'], None)
                return order
            self._cover_states.pop(bot["id"], None)
            self._retreat_states.pop(bot["id"], None)
            self._firing_holds.pop(bot["id"], None)
            return order

        observers = focus.get("shootable_by_bot_ids")
        locally_shootable = bool(focus.get("visible") and
                                 bot["id"] in (observers or ()))
        self._set_target(
            order, bot, focus, profile, personality, locally_shootable)
        retreat = self._retreat_states.get(bot['id'])
        if retreat is not None and retreat.get('phase') == 'withdraw':
            self._apply_retreat_order(order, bot, retreat['target_point'],
                focus['position'], now, retreat['moving_mode'], retreat['hold_mode'])
            self._firing_holds.pop(bot['id'], None)
            return order
        bx = _number(state.get("x"))
        bz = _number(state.get("z"))
        distance = math.hypot(focus["position"]["x"] - bx,
                              focus["position"]["z"] - bz)
        if distance > fire_range:
            order["fire_allowed"] = False
        dominant = str(profile.get("dominant_role") or "support")
        roles = profile.get("roles") if isinstance(profile.get("roles"), dict) else {}
        far_limit = desired_range * (1.08 + personality["caution"] * 0.18)
        close_limit = desired_range * (0.48 + personality["aggression"] * 0.10)
        support_score = self._ally_support_score(
            bot, team_bots or (), focus)

        if not locally_shootable:
            if focus.get("movement_lease"):
                if (bot["id"] in self._cover_states and
                        self._apply_cover_order(
                            order, bot, focus, personality, now)):
                    self._engage_anchors.pop(bot["id"], None)
                    self._combat_states.pop(bot["id"], None)
                    self._firing_holds.pop(bot["id"], None)
                    return order
                if self._apply_leased_movement_order(
                        order, bot, focus):
                    self._release_unproductive_firing_hold(
                        order, bot, move, route_anchor, now)
                    return order
            self._engage_anchors.pop(bot["id"], None)
            self._combat_states.pop(bot["id"], None)
            self._retreat_states.pop(bot["id"], None)
            self._cover_states.pop(bot["id"], None)
            # The selected, known enemy remains the objective. A blocked or
            # expired lane disables launch; it does not authorize route travel.
            # Native navigation, collision and final-fire checks still apply.
            self._combat_approach(order, focus['position'], 'local_lane_lost')
            self._firing_holds.pop(bot["id"], None)
            return order

        self._retreat_states.pop(bot["id"], None)
        if (distance > close_limit and distance <= fire_range and
                self._capable(bot, bot_gunnery.CAPABILITY_FLANK) and
                self._should_flank(bot, focus, team_bots or ())):
            self._engage_anchors.pop(bot["id"], None)
            self._combat_states.pop(bot["id"], None)
            self._cover_states.pop(bot["id"], None)
            order["combat_mode"] = "flank"
            order["move_position"] = self._flank_point(
                bot, focus, desired_range, team_bots or ())
            order["throttle_override"] = 1.0
            self._firing_holds.pop(bot["id"], None)
            return order
        advance_score = (
            personality["aggression"] * 0.85 +
            personality["initiative"] * 0.30 +
            support_score * (0.35 + personality["teamwork"] * 0.25) -
            personality["caution"] * 0.55)
        threshold = 0.24 if dominant == "brawler" else 0.34
        far_mode = ("advance_contact" if advance_score >= threshold
                    else "support_hold")
        range_mode = self._stable_range_mode(
            bot, focus, distance, far_limit, far_mode, fire_range, now)
        if (bot["id"] in self._cover_states and
              distance <= fire_range * 1.15 and
              self._apply_cover_order(
                  order, bot, focus, personality, now)):
            self._engage_anchors.pop(bot["id"], None)
            self._combat_states.pop(bot["id"], None)
        elif distance > far_limit or range_mode != "engage":
            self._cover_states.pop(bot["id"], None)
            if range_mode == "advance_contact":
                self._engage_anchors.pop(bot["id"], None)
                # Keep a distant contact as an aiming target while travelling
                # the assigned lane. Switching to the enemy's position and
                # back to the route repeatedly resets local navigation progress.
                order["combat_mode"] = "advance" if route_id else "advance_contact"
                order["move_position"] = dict(move if route_id else focus["position"])
                order["throttle_override"] = 1.0
            elif range_mode == "support_hold":
                order["combat_mode"] = "support_hold"
                order["move_position"] = _point(state)
                order["throttle_override"] = 0.0
            else:
                order["combat_mode"] = "engage"
                target_key = (focus.get("target_kind"), focus["id"])
                anchor_state = self._engage_anchors.get(bot["id"])
                if (anchor_state is None or
                        anchor_state["target"] != target_key):
                    anchor_state = {
                        "target": target_key,
                        "position": _point(bot["state"]),
                    }
                    self._engage_anchors[bot["id"]] = anchor_state
                order["move_position"] = dict(anchor_state["position"])
                order["throttle_override"] = 0.0
        elif (distance <= fire_range * 1.15 and
              self._apply_cover_order(order, bot, focus, personality, now)):
            self._engage_anchors.pop(bot["id"], None)
            self._combat_states.pop(bot["id"], None)
        elif distance <= min(fire_range, max(150.0, desired_range * 1.35)):
            # A visible enemy inside an effective firing envelope interrupts
            # route travel immediately when no client-probed cover manoeuvre is
            # active. Existing cover remains a higher-quality combat action.
            self._cover_states.pop(bot["id"], None)
            order["combat_mode"] = "engage"
            target_key = (focus.get("target_kind"), focus["id"])
            anchor_state = self._engage_anchors.get(bot["id"])
            if anchor_state is None or anchor_state["target"] != target_key:
                anchor_state = {
                    "target": target_key,
                    "position": _point(bot["state"]),
                }
                self._engage_anchors[bot["id"]] = anchor_state
            order["move_position"] = dict(anchor_state["position"])
            order["throttle_override"] = 0.0
        else:
            order["combat_mode"] = "engage"
            target_key = (focus.get("target_kind"), focus["id"])
            anchor_state = self._engage_anchors.get(bot["id"])
            if anchor_state is None or anchor_state["target"] != target_key:
                anchor_state = {
                    "target": target_key,
                    "position": _point(bot["state"]),
                }
                self._engage_anchors[bot["id"]] = anchor_state
            order["move_position"] = dict(anchor_state["position"])
            # Only the geometry-backed cover state machine may order a peek.
            # Periodic open-ground jiggle looked like a stuck-physics
            # oscillation and could reverse a tank toward an unprobed cliff or
            # traffic queue.
            order["throttle_override"] = 0.0
        self._apply_stationary_angling(
            order, bot, profile, personality)
        self._release_unproductive_firing_hold(
            order, bot, move, route_anchor, now)
        return order

    def _release_unproductive_firing_hold(self, order, bot, move, anchor, now):
        """A ready gun without a shot cannot lease an ordinary hold forever."""
        state = bot['state']
        bot_id = bot['id']
        active = self._firing_holds.get(bot_id)
        releasing = (order.get('combat_mode') == 'advance_contact' and
                     active is not None and active.get('destination') is not None)
        evidence = dict(sampled_at=now, mode=order.get('combat_mode'),
                        fire_seq=state.get('fire_seq'), reason='ineligible')
        order.setdefault('tactical_evidence', {})['firing_hold'] = evidence
        if (order.get('tactical_evidence', {}).get('blocked_hold_handoff', {}).get(
                'reason') == 'lane_refresh_pending'):
            # Waiting for geometry is not eight seconds of a proved ready lane
            # without a shot. Do not let the idle-shot timer undo this owner.
            self._firing_holds.pop(bot_id, None)
            evidence['reason'] = 'lane_refresh_pending'
            return
        if state.get('local_combat_manoeuvre', False):
            # The worker owns the complete bounded lane/angle manoeuvre.
            # Time spent turning/moving for that action is not idle aiming.
            # Its terminal publication clears the bit and starts a fresh hold.
            self._firing_holds.pop(bot_id, None)
            evidence['reason'] = 'local_combat_manoeuvre_active'
            return
        if ((not releasing and (order.get('combat_mode') not in ('engage', 'support_hold') or
                order.get('throttle_override') != 0.0)) or
                'fire_seq' not in state or not self._weapon_ready(bot)):
            self._firing_holds.pop(bot_id, None)
            return
        key = (order.get('target_kind'), order.get('target_id'))
        lease = self._target_assignments.get(bot_id)
        if (not releasing and isinstance(lease, dict) and lease.get('target') == key and
                not state.get('aim_feedback_aligned', False) and
                self._target_aim_in_progress(bot, lease, now)):
            self._firing_holds.pop(bot_id, None)
            evidence.update(reason='executed_aim_in_progress',
                            aim_progress_at=lease.get('aim_progress_at'))
            return
        position = _point(state)
        record = self._firing_holds.get(bot_id)
        sequence = _integer(state.get('fire_seq'))
        if (record is None or record['target'] != key or
                record['fire_seq'] != sequence or
                (not releasing and math.hypot(
                    position['x'] - record['position']['x'],
                    position['z'] - record['position']['z']) >= 2.0)):
            record = dict(target=key, fire_seq=sequence, position=position,
                          ready_since=_number(now))
            self._firing_holds[bot_id] = record
        evidence.update(ready_since=record['ready_since'],
                        ready_elapsed=_number(now)-record['ready_since'],
                        reason='ready_without_shot')
        if _number(now) - record['ready_since'] < 8.0:
            return
        destination = record.get('destination')
        if destination is None:
            point = order.get('aim_position')
            destination = dict(point) if isinstance(point, dict) and math.hypot(
                point['x'] - position['x'], point['z'] - position['z']) > 1.5 else None
            if destination is None:
                evidence['reason'] = 'no_combat_approach_destination'
                return
            record['destination'] = destination
            record['move_until'] = _number(now) + 4.0
        evidence.update(destination=dict(destination), move_until=record['move_until'])
        if _number(now) >= record['move_until']:
            evidence['reason'] = 'combat_approach_complete'
            if releasing and order.get('fire_allowed'):
                order.update(combat_mode='engage', throttle_override=0.0,
                             move_position=dict(position))
            self._firing_holds.pop(bot_id, None)
            return
        evidence['reason'] = 'combat_approach_active'
        # Reuse the existing contact-approach owner, never the ordinary route.
        self._combat_approach(order, destination, 'ready_without_shot')
        self._engage_anchors.pop(bot_id, None)

    @staticmethod
    def _personality(bot_id):
        # Stable JSON data, not a client object: no process-local RNG state.
        value = (int(bot_id) * 1103515245 + 12345) & 0x7fffffff
        return {
            "aggression": round(0.35 + (value % 41) / 100.0, 3),
            "caution": round(0.25 + ((value >> 8) % 41) / 100.0, 3),
            "teamwork": round(0.30 + ((value >> 12) % 51) / 100.0, 3),
            "patience": round(0.25 + ((value >> 16) % 56) / 100.0, 3),
            "initiative": round(0.25 + ((value >> 20) % 61) / 100.0, 3),
            "adaptability": round(0.30 + ((value >> 4) % 51) / 100.0, 3),
            "jiggle": round(0.18 + ((value >> 6) % 65) / 100.0, 3),
        }
