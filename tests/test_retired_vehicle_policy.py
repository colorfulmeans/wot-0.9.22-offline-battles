"""Retired hidden vehicles stay player-accessible but never enter Bot lineups."""
import unittest

from launcher import bot_lineup_profiles, retired_vehicles


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
                choice = {
                    "nation": nation,
                    "vehicle": vehicle,
                    "tags": ["mediumTank"],
                }
                self.assertFalse(bot_lineup_profiles.vehicle_choice_is_eligible(choice))
                self.assertTrue(bot_lineup_profiles.vehicle_choice_is_standard(choice))

    def test_non_retired_hidden_vehicle_is_not_excluded_by_name_policy(self):
        self.assertTrue(bot_lineup_profiles.vehicle_choice_is_eligible({
            "nation": "germany",
            "vehicle": "G98_Waffentrager_E100_P",
            "tags": ["AT-SPG", "secret"],
        }))


if __name__ == "__main__":
    unittest.main()
