"""Fitting-only difficulty contract after artificial gunnery retirement."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = (
    ROOT / 'src' / 'res' / 'scripts' / 'client' / 'gui' / 'mods' /
    'offline_lan_0922')
sys.path.insert(0, str(ROOT / 'launcher'))


def _load(module_name):
    for name in ('gui', 'gui.mods', 'gui.mods.offline_lan_0922'):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(PACKAGE_ROOT)]
            sys.modules[name] = module
    full_name = 'gui.mods.offline_lan_0922.%s' % module_name
    sys.modules.pop(full_name, None)
    spec = importlib.util.spec_from_file_location(
        full_name, PACKAGE_ROOT / ('%s.py' % module_name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


gunnery = _load('bot_gunnery')


class FittingTierTableTests(unittest.TestCase):
    def test_native_crew_levels_follow_the_existing_fitting_tiers(self):
        self.assertEqual(
            [50, 75, 100, 100],
            [gunnery.crew_level(skill) for skill in gunnery.SKILL_TIERS])

    def test_retired_gunnery_effects_and_random_strategy_gates_are_deleted(self):
        retired = (
            'rating_parameters', 'skill_parameters', 'bias_epoch',
            'engagement_error', 'aim_offset_metres', 'may_fire',
            'capability_onset', 'capability_probability', 'capability_allowed',
            'CAPABILITIES', 'TARGET_CAPABILITIES', 'LATCHED_CAPABILITIES',
            'CAPABILITY_ONSETS', 'CAPABILITY_EXPONENT', 'AIM_BIAS_SECONDS',
            'VERTICAL_BIAS_SHARE', 'MAX_AIM_OFFSET_METRES', '_PARAMETERS')
        for name in retired:
            with self.subTest(name=name):
                self.assertFalse(hasattr(gunnery, name))
        self.assertFalse(any(name.startswith('CAPABILITY_')
                             for name in vars(gunnery)))

    def test_two_full_crews_still_have_different_native_fittings(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        veteran = bot_fittings.plan('ussr:R04_T-34', 'veteran')
        elite = bot_fittings.plan('ussr:R04_T-34', 'elite')
        self.assertEqual(100, veteran['crew'])
        self.assertEqual(100, elite['crew'])
        self.assertNotEqual(veteran['devices'], elite['devices'])
        self.assertIsNone(veteran['directive'])
        self.assertEqual('rammerBattleBooster', elite['directive'])

    def test_stock_and_full_vehicle_modules_remain_distinct(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        stock = bot_fittings.plan('ussr:R04_T-34', 'rookie')
        full = bot_fittings.plan('ussr:R04_T-34', 'elite')
        self.assertEqual('_76mm_L-11', stock['modules']['gun'])
        self.assertEqual('_76mm_S-54', full['modules']['gun'])
        self.assertEqual([], stock['devices'])
        self.assertEqual(3, len(full['devices']))

    def test_independent_fitting_overrides_are_not_collapsed_into_crew(self):
        from gui.mods.offline_lan_0922 import bot_fittings, bot_tactics
        values = dict(development='full', equipment='improved',
                      crew_preset='50', consumables='large',
                      outfit='on', ammo_ratios=[3, 2, 1], ammo_limit=40)
        self.assertEqual(values, bot_tactics.normalize_values(values))
        actual = bot_fittings.plan('ussr:R04_T-34', 'rookie', values)
        self.assertEqual(50, actual['crew'])
        self.assertEqual('_76mm_S-54', actual['modules']['gun'])
        self.assertEqual(3, len(actual['devices']))
        self.assertEqual('rammerBattleBooster', actual['directive'])
        self.assertIsNotNone(actual['style'])

    def test_unknown_names_keep_the_existing_fitting_default(self):
        for value in (None, '', 'perfect', 7, object()):
            self.assertEqual(gunnery.DEFAULT_SKILL,
                             gunnery.normalize_skill(value))
            self.assertEqual(gunnery.DEFAULT_SKILL_MODE,
                             gunnery.normalize_skill_mode(value))

    def test_every_preset_is_a_usable_rating_distribution(self):
        for mode in gunnery.SKILL_MODES:
            points = gunnery._MODE_RATING_POINTS[mode]
            self.assertEqual(5, len(points), mode)
            self.assertTrue(all(0.0 <= point <= 1.0 for point in points), mode)
            self.assertEqual(sorted(points), list(points), mode)

    def test_each_preset_preserves_its_existing_mean_rating(self):
        expected = {'easy': 0.10, 'relaxed': 0.30, 'mixed': 0.60,
                    'hard': 0.80, 'brutal': 1.00}
        for mode in gunnery.SKILL_MODES:
            self.assertAlmostEqual(
                expected[mode], gunnery._mode_mean(mode), places=6, msg=mode)

    def test_the_mixed_preset_keeps_the_widest_fitting_distribution(self):
        spans = dict((mode, points[-1] - points[0])
                     for mode, points in gunnery._MODE_RATING_POINTS.items())
        self.assertEqual('mixed', max(spans, key=lambda mode: spans[mode]))
        self.assertEqual(0.0, spans['brutal'])


class FittingResolutionTests(unittest.TestCase):
    def _roster(self, mode, round_id=5):
        return [gunnery.resolve_skill(mode, round_id, team, slot)
                for team in (1, 2) for slot in range(15)]

    def test_seeded_slot_assignments_survive_removing_the_gunner_model(self):
        expected = {
            'easy': 0.0866027172861106,
            'relaxed': 0.26420333558654996,
            'mixed': 0.5466412293927252,
            'hard': 0.8434346083690549,
            'brutal': 1.0,
        }
        for mode, rating in expected.items():
            self.assertEqual(rating, gunnery.resolve_rating(mode, 9, 2, 4))
            self.assertEqual(
                gunnery.skill_for_rating(rating),
                gunnery.resolve_skill(mode, 9, 2, 4))

    def test_the_brutal_preset_is_every_bot_elite(self):
        self.assertEqual(set(['elite']), set(self._roster('brutal')))

    def test_easy_does_not_assign_the_top_two_fitting_presets(self):
        for round_id in range(1, 40):
            self.assertFalse(set(self._roster('easy', round_id)) &
                             set(('veteran', 'elite')))

    def test_the_mixed_roster_still_uses_every_fitting_tier(self):
        seen = set()
        for round_id in range(1, 20):
            seen.update(self._roster('mixed', round_id))
        self.assertEqual(set(gunnery.SKILL_TIERS), seen)

    def test_a_preset_samples_the_mean_rating_it_specifies(self):
        for mode in gunnery.SKILL_MODES:
            drawn = [gunnery.resolve_rating(mode, round_id, team, slot)
                     for round_id in range(400)
                     for team in (1, 2) for slot in range(15)]
            self.assertAlmostEqual(
                gunnery._mode_mean(mode), sum(drawn) / float(len(drawn)),
                delta=0.01, msg=mode)
            self.assertTrue(all(0.0 <= value <= 1.0 for value in drawn), mode)

    def test_an_unknown_preset_resolves_a_supported_fitting_tier(self):
        self.assertIn(gunnery.resolve_skill('impossible', 3, 1, 0),
                      gunnery.SKILL_TIERS)

    def test_each_anchor_retains_its_fitting_and_crew(self):
        for skill in gunnery.SKILL_TIERS:
            rating = gunnery.rating_for_skill(skill)
            self.assertEqual(skill, gunnery.skill_for_rating(rating))
            self.assertEqual(gunnery.crew_level(skill),
                             gunnery.rating_crew_level(rating))

    def test_midpoint_ties_keep_the_lower_fitting_tier(self):
        for index in range(len(gunnery.RATING_ANCHORS) - 1):
            middle = sum(gunnery.RATING_ANCHORS[index:index + 2]) * 0.5
            self.assertEqual(gunnery.SKILL_TIERS[index],
                             gunnery.skill_for_rating(middle))

    def test_only_native_crew_presets_are_selected_across_the_rating_axis(self):
        levels = [gunnery.rating_crew_level(index / 100.0)
                  for index in range(101)]
        self.assertEqual(sorted(levels), levels)
        self.assertEqual(set(gunnery.PROVEN_CREW_LEVELS), set(levels))

    def test_unusable_ratings_keep_existing_normalization(self):
        for value in (None, '', 'elite', float('nan'), float('inf'), object()):
            self.assertEqual(gunnery.DEFAULT_RATING,
                             gunnery.normalize_rating(value))
        self.assertEqual(0.0, gunnery.normalize_rating(-3.0))
        self.assertEqual(1.0, gunnery.normalize_rating(9.0))

    def test_easy_preserves_the_reviewed_upper_rating_bound(self):
        ceiling = gunnery._MODE_RATING_POINTS['easy'][-1]
        for round_id in range(60):
            for team in (1, 2):
                for slot in range(15):
                    self.assertLessEqual(
                        gunnery.resolve_rating('easy', round_id, team, slot),
                        ceiling)

    def test_brutal_preserves_complete_fitting_ratings(self):
        for round_id in range(20):
            for slot in range(15):
                self.assertEqual(
                    1.0, gunnery.resolve_rating('brutal', round_id, 1, slot))


class SkillVocabularyParityTests(unittest.TestCase):
    def test_launcher_and_worker_share_the_fitting_tier_vocabulary(self):
        import bot_lineup_profiles
        self.assertEqual(tuple(gunnery.SKILL_TIERS),
                         tuple(bot_lineup_profiles.BOT_SKILL_TIERS_0922))

    def test_waiting_room_presets_remain_available_in_the_existing_order(self):
        waiting_room_ui = _load('waiting_room_ui')
        self.assertEqual(
            ('mixed', 'easy', 'relaxed', 'hard', 'brutal'),
            tuple(value for value, unused_label
                  in waiting_room_ui.BOT_SKILL_OPTIONS))
        self.assertEqual(set(gunnery.SKILL_MODES),
                         set(value for value, label
                             in waiting_room_ui.BOT_SKILL_OPTIONS))

    def test_wire_still_accepts_exactly_the_supported_presets(self):
        lan_client = _load('lan_client')
        self.assertEqual(frozenset(gunnery.SKILL_MODES),
                         lan_client.BOT_SKILL_MODES)


if __name__ == '__main__':
    unittest.main()
