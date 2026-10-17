"""Temporary bridge-drop fixture. Enabled only by START_ROOF_CRUSH_TEST.bat.

This module belongs to the isolated test branch, never the release branch.
It changes initial placement and voluntary Bot orders, not physical laws.
"""
from __future__ import print_function
import math
import os

ENV = 'WOT_OFFLINE_ROOF_CRUSH_TEST'
SHOT_ENV = 'WOT_OFFLINE_ROOF_SHOT_DROP'
MAP = '37_caucasus'
VEHICLE = 'china:Ch01_Type59'


def enabled():
    return os.environ.get(ENV) == '1'


def shot_drop_enabled():
    return enabled() and os.environ.get(SHOT_ENV) == '1'


def enemy_seed(slot):
    """Fifteen close targets below one edge of the bridge's lower corridor.

    Y is only a below-deck query hint. The real native surface owns spawn Y.
    """
    if shot_drop_enabled():
        index = int(slot)
        if not 0 <= index < 15:
            raise ValueError('shot drop supports fifteen enemy slots')
        row, column = divmod(index, 2)
        return _deck_seed(-8.0-row*6.4, (column-.5)*3.5)
    row, column = divmod(int(slot), 5)
    if not 0 <= row < 3:
        raise ValueError('roof test supports fifteen enemy slots')
    sideways = 6.0+row*3.5
    yaw = math.atan2(10.0, -7.0)
    along = column*6.4
    return (2.0+math.sin(yaw)*along+math.cos(yaw)*sideways, -14.0,
            105.0+math.cos(yaw)*along-math.sin(yaw)*sideways), yaw


DECK_FRIENDLIES = 6


def _deck_seed(along, sideways):
    yaw = math.atan2(10.0, -7.0)
    return (2.0+math.sin(yaw)*along+math.cos(yaw)*sideways,
            1.0, 105.0+math.cos(yaw)*along-math.sin(yaw)*sideways), yaw


def player_seed():
    """Bridge centre lane, behind the first parked hull with room to turn."""
    if shot_drop_enabled():
        # Windows340 report 175512: the first two drops contact at lateral
        # 12.775m and 12.207m. Centre the player there, not at the exit ray.
        point, yaw = _deck_seed(4.0, 12.5)
        return (point[0], -14.0, point[2]), yaw
    return _deck_seed(-14.0, -.7)


def friendly_seed(slot):
    """Six broadside targets along the edge; overflow parks at the bridgehead.

    The hull axes follow the bridge, presenting their sides to the drop.
    Every Y remains a native surface-query hint, never a fabricated floor.
    """
    index = int(slot)-1
    if not 0 <= index < 14:
        raise ValueError('roof test friendly row uses slots one to fourteen')
    if index < DECK_FRIENDLIES:
        return _deck_seed(index*6.4-3.2, 2.25)
    row, column = divmod(index-DECK_FRIENDLIES, 2)
    return _deck_seed(-32.0-row*7.0, -.5+column*3.6)


def hold_command(command, position):
    command = dict(command)
    command.update(throttle=0.0, turn=0.0, brake=True,
        movement_intent=False, fire_allowed=False, target_id=None,
        combat_mode='hold', recovery_mode='roof_crush_test',
        move_position=tuple(position), aim_position=tuple(position),
        face_position=tuple(position))
    return command


class ShotDropQueue(object):
    """Fixture-only orders, driven by acknowledged player shot sequences.

    Never changes poses, velocities, contacts, support or damage. Each Bot
    drives through the same clear apron and off the same edge under ordinary
    physics. A new instance belongs to one Bot runtime / battle round.
    """
    def __init__(self):
        self.sequences = {}
        self.released = set()
        self.routes = {}
        self.events = []

    def observe(self, players, states):
        for player in sorted(players, key=lambda p: int(p.get('id', 0))):
            identity = int(player['id'])
            sequence = max(0, int(player.get('fire_seq', 0)))
            previous = self.sequences.get(identity, 0)
            self.sequences[identity] = max(previous, sequence)
            for shot in range(previous+1, sequence+1):
                waiting = [s for s in states.values() if s.get('alive', True)
                           and int(s['id']) not in self.released]
                waiting.sort(key=lambda s: int(s['id']))
                if not waiting:
                    self.events.append(dict(phase='exhausted', player=identity, shot=shot))
                    continue
                bot = waiting[0]
                bot_id = int(bot['id'])
                self.released.add(bot_id)
                yaw = math.atan2(10., -7.)
                lateral = (bot['x']-2.)*math.cos(yaw)-(bot['z']-105.)*math.sin(yaw)
                # All parked rows end behind along=-8. The apron ahead of
                # them is reserved for turning, not occupied by another Bot.
                self.routes[bot_id] = [
                    _deck_seed(4., lateral)[0],
                    _deck_seed(4., 2.25)[0],
                    _deck_seed(4., 14.)[0]]
                self.events.append(dict(phase='release', player=identity,
                    shot=shot, bot=bot_id, position=(bot['x'], bot['y'], bot['z']),
                    landing_target=player_seed()[0]))

    def command(self, incoming, state):
        position = (state['x'], state['y'], state['z'])
        result = hold_command(incoming, position)
        route = self.routes.get(int(state['id']))
        if not route:
            return result
        if state['y'] < -3.0:
            del self.routes[int(state['id'])]
            self.events.append(dict(phase='falling', bot=int(state['id']), position=position))
            return result
        while len(route) > 1 and math.hypot(
                state['x']-route[0][0], state['z']-route[0][2]) < .8:
            route.pop(0)
            self.events.append(dict(phase='waypoint', bot=int(state['id']),
                position=position, remaining=len(route), goal=route[0]))
        goal = route[0]
        desired = math.atan2(goal[0]-state['x'], goal[2]-state['z'])
        delta = (desired-state['yaw']+math.pi) % (2.*math.pi)-math.pi
        speed = float(state.get('speed', 0.))
        aligned = abs(delta) < .35
        result.update(turn=max(-1., min(1., delta/.5)),
            throttle=max(0., min(.8, (3.0-speed)*.5)) if aligned else 0.,
            brake=not aligned or speed > 3.3, movement_intent=True,
            move_position=goal, face_position=goal, aim_position=goal,
            recovery_mode='roof_shot_drop')
        return result

    def drain_events(self):
        events, self.events = self.events, []
        return events


def install_server(battle_class, planner_class):
    if not enabled() or getattr(battle_class, '_roof_crush_test_installed', False):
        return
    original_init = battle_class.__init__
    original_start = battle_class.request_start

    def initialize(self, map_name=MAP, max_players=30, clock=None,
                   team_size=15, **kwargs):
        shot_drop = shot_drop_enabled()
        kwargs.update(team1_size=1 if shot_drop else 15, team2_size=15,
            bot_lineup=[dict(team=team,slot=slot,vehicle=VEHICLE)
                for team in ((2,) if shot_drop else (1,2)) for slot in range(15)],
            bot_excluded_vehicles=None, bot_tactics_path=None)
        original_init(self, map_name=MAP, max_players=max_players,
            clock=clock, team_size=15, **kwargs)
        print('[ROOF CRUSH TEST] temporary fixture; map=37_caucasus '
              'humans=team1 enemies=15_Type59 mode=%s' %
              ('shot_releases_one_Bot' if shot_drop else 'all_Bots_hold_and_no_fire'))

    def start(self, player_id, requested_map=None, requested_round_seconds=None,
              battle_mode='regular', training_bots=False):
        return original_start(self, player_id, requested_map=MAP,
            requested_round_seconds=requested_round_seconds,
            battle_mode=battle_mode, training_bots=training_bots)

    def orders(self, manifest, bot_states, players, now, defense=None,
               team_orders=None):
        states = dict((row['id'],row) for row in bot_states or ())
        result=[]
        for row in manifest or ():
            state=states.get(row['id'],row)
            if not state.get('alive',True):
                continue
            point=dict((key,float(state.get(key,0.0))) for key in ('x','y','z'))
            result.append(dict(id=row['id'],team=row['team'],
                target_id=None,aim_position=None,face_position=None,
                move_position=point,fire_allowed=False,combat_mode='hold',
                throttle_override=0.0,route_id=None,route_index=0,
                route_anchor=dict(point),route_join=False,shell_index=0))
        payload=dict(orders=result)
        if payload != self._last_order_signature:
            self.revision+=1
            self._last_order_signature=payload
        self._last_orders=payload
        return dict(revision=self.revision,orders=result)

    battle_class.__init__=initialize
    battle_class.request_start=start
    battle_class._requested_team_for_player=staticmethod(lambda player:1)
    battle_class._roof_crush_test_installed=True
    planner_class.build_orders=orders
