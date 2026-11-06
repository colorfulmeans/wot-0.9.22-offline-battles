"""Observed-front transfers must improve departure and arrival together.

These tests call the player-owned strategy with real observation shapes. They
prove the local allocation rule, not the native feasibility of a route change.
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.strategy import Strategy
from gui.mods.offline_lan_0922 import bot_tactics
from test_player_navigation_completion import RealNavigationCase, pose


ROUTES = [dict(id='a', waypoints=[(-100., -100.), (-100., 400.)]),
          dict(id='b', waypoints=[(100., -100.), (100., 400.)])]
OWN_ENGINE = 900
OWN_ACTOR = ('player', 1)


def opponent(identity, lane, **values):
    result = dict(id=identity, position=(ROUTES[lane]['waypoints'][0][0], 0., 50.),
                  alive=True, health=1000, max_health=1000)
    result.update(values)
    return result


def friendly(identity, lane, **values):
    result = dict(id=identity, position=(ROUTES[lane]['waypoints'][0][0], 0., 0.),
                  alive=True, health=1000, max_health=1000, class_tag='mediumTank')
    result.update(values)
    return result


def own_state(own, now):
    result = dict(id=1, engine_id=own['id'], now=float(now), position=own['position'],
                  health=own['health'], max_health=own['max_health'],
                  alive=own['alive'], class_tag=own['class_tag'])
    if own.get('actor_key') is not None:
        result['actor_key'] = own['actor_key']
    return result


def observe(strategy, now, current, contacts, own=None, others=(), duplicate_own=False):
    own = own if own is not None else friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR)
    allies = [own] + list(others)
    if duplicate_own:
        allies.append(dict(own))
    return strategy.decide(float(now), ROUTES, current, contacts, allies, {}, None,
                           state=own_state(own, now))


class PlayerStrategyTransferTests(unittest.TestCase):
    def test_equivalent_exchange_cannot_repeat_when_contacts_are_unchanged(self):
        contacts = [opponent(21, 0), opponent(22, 1)]
        for starting_lane in (0, 1):
            with self.subTest(starting_lane=starting_lane):
                strategy = Strategy()
                current = ROUTES[starting_lane]
                changes = []
                for now in range(145):
                    lane = ROUTES.index(current)
                    own = friendly(OWN_ENGINE, lane, actor_key=OWN_ACTOR)
                    redirect = observe(strategy, now, current, contacts, own)
                    if redirect:
                        changes.append((now, current['id'], redirect[0]['id']))
                        # Observe arrival on the accepted lane. The old rule
                        # then reassigns the same hull back at 48, 84, 120s.
                        current = redirect[0]
                self.assertEqual([], changes)
                self.assertEqual('no_pressure_improvement', strategy.receipt['outcome'])
                self.assertAlmostEqual(1.25, strategy.receipt['before_transfer'])
                self.assertAlmostEqual(1.25, strategy.receipt['after_transfer'])

    def test_real_pressure_improvement_survives_departure_transit_and_arrival(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1), opponent(23, 1)]
        current, changes, accepted = ROUTES[0], [], None
        for now in range(145):
            own = friendly(OWN_ENGINE, 0 if now < 20 else 1, actor_key=OWN_ACTOR)
            if 20 <= now < 70:
                own['position'] = (0., 0., -200.)
            redirect = observe(strategy, now, current, contacts, own)
            if redirect:
                changes.append((now, current['id'], redirect[0]['id']))
                current = redirect[0]
                accepted = dict(strategy.receipt)
        self.assertEqual([(12, 'a', 'b')], changes)
        self.assertEqual('a', accepted['source_route'])
        self.assertAlmostEqual(.65, accepted['own_contribution'])
        self.assertAlmostEqual(.65, accepted['transfer_contribution'])
        self.assertAlmostEqual(2.5, accepted['before_transfer'])
        self.assertAlmostEqual(1.85, accepted['after_transfer'])

    def test_new_stronger_pressure_can_reverse_a_completed_transfer(self):
        strategy = Strategy()
        current, changes = ROUTES[0], []
        for now in range(85):
            contacts = [opponent(22, 1)]
            if now >= 50:
                contacts.extend([opponent(21, 0), opponent(23, 0)])
            own = friendly(OWN_ENGINE, ROUTES.index(current), actor_key=OWN_ACTOR)
            redirect = observe(strategy, now, current, contacts, own)
            if redirect:
                changes.append((now, current['id'], redirect[0]['id']))
                current = redirect[0]
        self.assertEqual([(12, 'a', 'b'), (60, 'b', 'a')], changes)
        self.assertLess(strategy.receipt['after_transfer'], strategy.receipt['before_transfer'])

    def test_current_physical_front_cannot_receive_the_same_hull_twice(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 0), opponent(23, 1)]
        own = friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR)
        # A selected-route hint is not an acknowledged pressure transfer.
        # While the observed hull is on a, evaluating a cannot add a second
        # copy of it there. An accepted transfer needs its own projected
        # departure/arrival owner before it can change this baseline.
        for now in range(49):
            self.assertIsNone(observe(strategy, now, ROUTES[1], contacts, own))
        self.assertEqual('a', strategy.receipt['source_route'])
        self.assertEqual('b', strategy.receipt['current_route'])
        self.assertAlmostEqual(1.85, strategy.receipt['before_transfer'])
        self.assertAlmostEqual(1.85, strategy.receipt['after_transfer'])

    def test_player_network_id_cannot_steal_another_hulls_contribution(self):
        for actor_keys in (False, True):
            with self.subTest(actor_keys=actor_keys):
                strategy = Strategy()
                own = friendly(OWN_ENGINE, 0)
                other = friendly(1, 1)
                if actor_keys:
                    own['actor_key'] = OWN_ACTOR
                    other['actor_key'] = ('bot', 1)
                contacts = [opponent(21, 0), opponent(22, 1), opponent(23, 1)]
                for now in range(13):
                    redirect = observe(strategy, now, ROUTES[0], contacts, own, [other])
                self.assertEqual([ROUTES[1]], redirect)
                self.assertEqual('a', strategy.receipt['source_route'])
                self.assertAlmostEqual(.6, strategy.receipt['scores']['a'])
                self.assertAlmostEqual(1.85, strategy.receipt['scores']['b'])
                self.assertAlmostEqual(1.25, strategy.receipt['after_transfer'])

    def test_duplicate_self_observations_do_not_create_an_improving_transfer(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1)]
        for now in range(13):
            self.assertIsNone(observe(strategy, now, ROUTES[0], contacts, duplicate_own=True))
        self.assertAlmostEqual(.6, strategy.receipt['scores']['a'])
        self.assertAlmostEqual(.65, strategy.receipt['own_contribution'])
        self.assertAlmostEqual(1.25, strategy.receipt['after_transfer'])
        self.assertEqual([], strategy.recent_losses)

    def test_state_supplies_self_when_roster_contains_only_other_players(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1)]
        own = friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR)
        for now in range(13):
            self.assertIsNone(strategy.decide(float(now), ROUTES, ROUTES[0], contacts,
                [], {}, None, state=own_state(own, now)))
        self.assertAlmostEqual(.6, strategy.receipt['scores']['a'])
        self.assertAlmostEqual(.65, strategy.receipt['own_contribution'])

    def test_damaged_player_transfers_only_its_remaining_contribution(self):
        strategy = Strategy()
        own = friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR, health=500)
        contacts = [opponent(21, 0), opponent(22, 1), opponent(23, 1)]
        for now in range(13):
            redirect = observe(strategy, now, ROUTES[0], contacts, own)
        self.assertEqual([ROUTES[1]], redirect)
        self.assertAlmostEqual(.325, strategy.receipt['own_contribution'])
        self.assertAlmostEqual(.325, strategy.receipt['transfer_contribution'])
        self.assertAlmostEqual(2.175, strategy.receipt['after_transfer'])

    def test_dead_player_cannot_offer_a_future_contribution(self):
        strategy = Strategy()
        own = friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR, alive=False, health=0)
        contacts = [opponent(22, 1), opponent(23, 1)]
        for now in range(49):
            self.assertIsNone(observe(strategy, now, ROUTES[0], contacts, own))
        self.assertEqual(0., strategy.receipt['transfer_contribution'])
        self.assertEqual(strategy.receipt['before_transfer'], strategy.receipt['after_transfer'])

    def test_damage_and_death_follow_actor_identity_once_across_entity_changes(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1)]
        own = friendly(OWN_ENGINE, 0, actor_key=OWN_ACTOR)
        ally = friendly(700, 1, actor_key=('bot', 4))
        for now in range(13):
            self.assertIsNone(observe(strategy, now, ROUTES[0], contacts, own, [ally, dict(ally)]))
        ally = dict(ally, id=701, health=400)
        observe(strategy, 13, ROUTES[0], contacts, own, [ally, dict(ally)])
        self.assertEqual(1, len(strategy.recent_losses))
        self.assertAlmostEqual(.6, strategy.recent_losses[0][2])
        ally = dict(ally, alive=False, health=0)
        for now in range(14, 25):
            redirect = observe(strategy, now, ROUTES[0], contacts, own, [ally, dict(ally)])
        self.assertEqual(2, len(strategy.recent_losses))
        self.assertAlmostEqual(1., sum(loss[2] for loss in strategy.recent_losses))
        self.assertEqual([ROUTES[1]], redirect)
        self.assertAlmostEqual(4.25, strategy.receipt['before_transfer'])
        self.assertAlmostEqual(3.6, strategy.receipt['after_transfer'])

    def test_entity_number_reuse_does_not_invent_damage_for_a_different_actor(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1)]
        first = friendly(700, 1, actor_key=('bot', 4))
        replacement = friendly(700, 1, actor_key=('player', 4), health=200)
        observe(strategy, 0, ROUTES[0], contacts, others=[first])
        observe(strategy, 1, ROUTES[0], contacts, others=[replacement])
        self.assertEqual([], strategy.recent_losses)
        observe(strategy, 2, ROUTES[0], contacts, others=[dict(replacement, health=100)])
        self.assertEqual(1, len(strategy.recent_losses))
        self.assertAlmostEqual(.1, strategy.recent_losses[0][2])

    def test_dead_or_positionless_contacts_neither_attract_nor_cover_a_front(self):
        strategy = Strategy()
        contacts = [opponent(21, 0), opponent(22, 1, alive=False),
                    opponent(23, 1, health=0), opponent(24, 1, position=None)]
        for now in range(49):
            self.assertIsNone(observe(strategy, now, ROUTES[0], contacts))
        self.assertEqual({'a'}, set(strategy.pressure_seen))


class PlayerStrategyMapTransferTests(RealNavigationCase):
    def test_thepit_fixed_contacts_cannot_retask_back_to_spawn_entry(self):
        nav = self.navigation('100_thepit', 'mediumTank', bot_tactics.default_profile())
        east = next(route for route in nav.routes if 'east' in route['id'])
        pit = next(route for route in nav.routes if route['id'].endswith('_pit'))
        nav.route, nav.index = east, 6
        contacts = [dict(id=21, position=(east['waypoints'][6][0], 0., east['waypoints'][6][1]),
                         health=1000, max_health=1000, alive=True),
                    dict(id=22, position=(pit['waypoints'][4][0], 0., pit['waypoints'][4][1]),
                         health=1000, max_health=1000, alive=True)]
        strategy = Strategy()
        observed, pending, changes = (84.98, -19.59), None, []
        # Real map, pathfinder, local route modifier and Driver consume each
        # Strategy proposal. Only the two reported native poses and world
        # clearance are supplied seams; this does not simulate the intervening
        # suspension or guarantee its driving time on the Windows client.
        with mock.patch('gui.mods.offline_lan_0922.player_control.pathfinding.write_json_record'):
            for now in range(145):
                if pending is not None and now >= pending[0]:
                    observed, pending = pending[1], None
                position = (observed[0], nav._height(observed, 0.), observed[1])
                sample = pose(float(now), position)
                sample.update(engine_id=900, actor_key=('player', 17),
                              health=1000, max_health=1000)
                own = dict(id=900, actor_key=('player', 17), position=position,
                    health=1000, max_health=1000, alive=True, class_tag='mediumTank')
                nav.set_context(dict(now=float(now), supported=True, contacts=contacts,
                                     allies=[own], base={}))
                redirect = strategy.decide(float(now), nav.routes, nav.route,
                    contacts, [own], {}, None, state=sample)
                if redirect is not None:
                    changes.append((now, nav.route['id'], nav.index, redirect[0]['id']))
                    self.assertTrue(nav.retask(redirect, 'route'))
                    destination = ((-15.53, -39.) if redirect[0]['id'] == pit['id']
                                   else (84.98, -19.59))
                    pending = now + 8, destination
                nav.decide(sample, lambda *args: True)
        self.assertEqual([], changes)
        self.assertEqual(east['id'], nav.route['id'])
        self.assertEqual(6, nav.index)


if __name__ == '__main__':
    unittest.main()
