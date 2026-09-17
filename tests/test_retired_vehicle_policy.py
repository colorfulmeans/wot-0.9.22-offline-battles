"""Retired hidden vehicles stay player-accessible but never enter Bot lineups."""
import unittest
from unittest import mock

from launcher import bot_lineup_profiles, gold_shop, retired_vehicles


RETIRED = retired_vehicles.RETIRED_BOT_VEHICLES_0922


class RetiredVehiclePolicyTests(unittest.TestCase):
    def test_exact_bot_lineup_drops_retired_vehicle_but_keeps_skill(self):
        store = {
            "schema": bot_lineup_profiles.SCHEMA,
            "profiles": [{
                "name": "legacy",
                "assignments": [{
                    "team": 1,
                    "slot": 3,
                    "vehicle": "germany:G98_Waffentrager_E100",
                    "skill": "veteran",
                }],
            }],
        }
        normalized = bot_lineup_profiles.normalize_store(store)
        self.assertEqual([{
            "team": 1, "slot": 3, "skill": "veteran",
        }], normalized["profiles"][0]["assignments"])

    def test_retired_vehicles_are_not_bot_candidates(self):
        for type_name in RETIRED:
            nation, vehicle = type_name.split(":", 1)
            with self.subTest(type_name=type_name):
                self.assertFalse(bot_lineup_profiles.vehicle_choice_is_eligible({
                    "nation": nation,
                    "vehicle": vehicle,
                    "tags": ["mediumTank"],
                }))

    def test_garage_catalogue_adds_all_retired_definitions(self):
        choices = []
        for index, type_name in enumerate(sorted(RETIRED)):
            nation, vehicle = type_name.split(":", 1)
            choices.append({
                "nation": nation,
                "vehicle": vehicle,
                "label": "Retired %d" % index,
                "vehicleClass": "mediumTank",
                "level": 7 + index % 4,
            })
        with mock.patch.object(
                gold_shop, "_ORIGINAL_LIST_GOLD_VEHICLES",
                return_value=[{
                    "name": "germany:G01_Normal",
                    "label": "Normal",
                    "nation": "germany",
                    "vehicleClass": "heavyTank",
                    "level": 10,
                }]), mock.patch.object(
                    gold_shop.vehicle_overlays, "list_vehicle_choices",
                    return_value=choices):
            offers = gold_shop._list_garage_vehicles("unused")
        by_name = dict((row["name"], row) for row in offers)
        self.assertTrue(RETIRED.issubset(by_name))
        for type_name in RETIRED:
            self.assertTrue(by_name[type_name]["retired"])
        self.assertIn("germany:G01_Normal", by_name)

    def test_non_retired_hidden_vehicle_is_not_excluded_by_name_policy(self):
        self.assertTrue(bot_lineup_profiles.vehicle_choice_is_eligible({
            "nation": "germany",
            "vehicle": "G98_Waffentrager_E100_P",
            "tags": ["AT-SPG", "secret"],
        }))


if __name__ == "__main__":
    unittest.main()
