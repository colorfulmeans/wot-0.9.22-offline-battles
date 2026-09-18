"""Edit regular personal-mission completion without issuing rewards.

The four #1513 operations each have five chains of fifteen missions. Values
are 1 (main conditions) or 2 (main and additional conditions); omission means
incomplete. Selection, daily goals and the rest of the garage are preserved.
"""

import os
import gettext
import time

try:
    from . import core, save_ledger, save_slots, vehicle_overlays
except ImportError:
    import core
    import save_ledger
    import save_slots
    import vehicle_overlays


INITIAL_KEY = "initial_personal_missions"
OPERATIONS = ("StuG IV", "T28 Concept", "T 55A", "Object 260")
CHAINS = ("LT", "HT", "MT", "TD", "SPG")


def mission_ids(operation, chain):
    if operation not in range(4) or chain not in range(5):
        raise ValueError("Invalid personal-mission operation or chain.")
    start = operation * 75 + chain * 15 + 1
    return tuple(range(start, start + 15))


def normalize(progress):
    result = {}
    if not isinstance(progress, dict):
        return result
    for key, value in progress.items():
        try:
            mission = int(key)
        except (TypeError, ValueError):
            continue
        if 1 <= mission <= 300 and type(value) is int and value in (1, 2):
            result[str(mission)] = value
    return result


def _target(slot_id, game_root=None, environment=None, root=None):
    path = save_ledger.ledger_path(slot_id, game_root, environment, root)
    state = save_ledger._read_state(path)
    if state is not None:
        ledger = state.get("ledger", {})
        if not isinstance(ledger, dict):
            raise save_ledger.SaveLedgerError("The save is not in the expected format.")
        missions = ledger.get("personalMissions", {})
        if not isinstance(missions, dict):
            raise save_ledger.SaveLedgerError("The save is not in the expected format.")
        return path, state, missions.get("completed", {}), True
    path = save_slots.metadata_path(slot_id, game_root, environment, root)
    state = save_ledger._read_state(path) or {}
    return path, state, state.get(INITIAL_KEY, {}), False


def read_progress(slot_id, game_root=None, environment=None, root=None):
    return normalize(_target(slot_id, game_root, environment, root)[2])


def write_progress(slot_id, progress, game_root=None, environment=None,
                   root=None, is_running=None):
    if (is_running or core.game_is_running)():
        raise save_ledger.SaveLedgerError(
            "Close World of Tanks before editing personal missions.")
    normalized = normalize(progress)
    if normalized != progress:
        raise save_ledger.SaveLedgerError("Invalid personal-mission progress.")
    path, state, unused, has_garage = _target(
        slot_id, game_root, environment, root)
    if has_garage:
        missions = state.setdefault("ledger", {}).setdefault("personalMissions", {})
        missions["completed"] = normalized
        # A fully completed mission cannot remain active in the native UI.
        missions["regular"] = [qid for qid in missions.get("regular", ())
                               if normalized.get(str(qid)) != 2]
    else:
        state[INITIAL_KEY] = normalized
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_ledger._write_state(path, state)
    return normalized


def read_account_fields(slot_id, game_root=None, environment=None, root=None):
    unused, state, unused_progress, has_garage = _target(slot_id, game_root, environment, root)
    if has_garage:
        ledger = state.get("ledger", {})
        orders = ledger.get("personalMissions", {}).get("orders", 0)
        badges = ledger.get("accountBadges", {})
    else:
        orders = state.get("initial_personal_orders", 0)
        badges = state.get("initial_account_badges", {})
    return {"orders": max(0, min(21, int(orders))),
            "badges": dict(badges) if isinstance(badges, dict) else {}}


def write_account_fields(slot_id, game_root=None, orders=None, badges=None,
                         environment=None, root=None, is_running=None):
    if (is_running or core.game_is_running)():
        raise save_ledger.SaveLedgerError("Close World of Tanks before editing personal missions.")
    if orders is not None and (type(orders) is not int or not 0 <= orders <= 21):
        raise save_ledger.SaveLedgerError("Orders must be a whole number from 0 to 21.")
    if badges is not None:
        available = {row["id"] for row in badge_catalogue(game_root)}
        if any(type(value) is not int or value not in available for value in badges):
            raise save_ledger.SaveLedgerError("Unknown account badge.")
    path, state, unused, has_garage = _target(slot_id, game_root, environment, root)
    container = state.setdefault("ledger", {}) if has_garage else state
    if orders is not None:
        if has_garage:
            container.setdefault("personalMissions", {})["orders"] = orders
        else:
            container["initial_personal_orders"] = orders
    if badges is not None:
        key = "accountBadges" if has_garage else "initial_account_badges"
        previous = container.get(key, {})
        previous = previous if isinstance(previous, dict) else {}
        container[key] = {str(badge): previous.get(str(badge), int(time.time()))
                          for badge in badges}
        if has_garage:
            services = container.get("offlineServices", {})
            if isinstance(services, dict):
                services["selectedBadges"] = [badge for badge in services.get("selectedBadges", ())
                                              if badge in badges]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_ledger._write_state(path, state)


def badge_catalogue(game_root):
    """Read actual badge IDs/names from the installed client's packed data."""
    status, package = vehicle_overlays._require_target(game_root)
    unused, tree = vehicle_overlays._read_source_member(package, "scripts/item_defs/badges.xml")

    def child(node, name):
        values = [value for key, value in node.children if key == name.encode("ascii")]
        if len(values) != 1:
            raise save_ledger.SaveLedgerError("The badge catalogue is not in the expected format.")
        return values[0].value

    translator = None
    path = os.path.join(status["path"], "res", "text", "LC_MESSAGES", "badge.mo")
    if os.path.isfile(path):
        with open(path, "rb") as stream:
            translator = gettext.GNUTranslations(stream)
    rows = []
    for name, value in child(tree, "badges").children:
        if name != b"badge":
            continue
        badge = value.value
        fields = {}
        for unused, item in child(badge, "value").children:
            field = item.value
            fields[child(field, "name").decode("utf-8").strip()] = field.value.value
        badge_id = int(fields["id"])
        key = "badge_%d" % badge_id
        label = translator.gettext(key) if translator else key
        if label == key:
            label = child(badge, "name").decode("utf-8").strip()
        rows.append({"id": badge_id, "label": label, "weight": float(fields.get("weight", 0))})
    return sorted(rows, key=lambda row: (row["weight"], row["id"]))
