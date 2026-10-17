"""Temporary bridge-drop fixture. Enabled only by START_ROOF_CRUSH_TEST.bat.

This module belongs to the isolated test branch, never the release branch.
It changes initial placement and voluntary Bot orders, not physical laws.
"""
from __future__ import print_function
import math
import os

ENV = 'WOT_OFFLINE_ROOF_CRUSH_TEST'
MAP = '37_caucasus'
VEHICLE = 'china:Ch01_Type59'


def enabled():
    return os.environ.get(ENV) == '1'


def enemy_seed(slot):
    """Fifteen close targets below one edge of the bridge's lower corridor.

    Y is only a below-deck query hint. The real native surface owns spawn Y.
    """
    row, column = divmod(int(slot), 5)
    if not 0 <= row < 3:
        raise ValueError('roof test supports fifteen enemy slots')
    sideways = 6.0+row*3.5
    yaw = math.atan2(10.0, -7.0)
    along = column*6.4
    return (2.0+math.sin(yaw)*along+math.cos(yaw)*sideways, -14.0,
            105.0+math.cos(yaw)*along-math.sin(yaw)*sideways), yaw


def hold_command(command, position):
    command = dict(command)
    command.update(throttle=0.0, turn=0.0, brake=True,
        movement_intent=False, fire_allowed=False, target_id=None,
        combat_mode='hold', recovery_mode='roof_crush_test',
        move_position=tuple(position), aim_position=tuple(position),
        face_position=tuple(position))
    return command


def install_server(battle_class, planner_class):
    if not enabled() or getattr(battle_class, '_roof_crush_test_installed', False):
        return
    original_init = battle_class.__init__
    original_start = battle_class.request_start

    def initialize(self, map_name=MAP, max_players=30, clock=None,
                   team_size=15, **kwargs):
        kwargs.update(team1_size=15, team2_size=15,
            bot_lineup=[dict(team=team,slot=slot,vehicle=VEHICLE)
                for team in (1,2) for slot in range(15)],
            bot_excluded_vehicles=None, bot_tactics_path=None)
        original_init(self, map_name=MAP, max_players=max_players,
            clock=clock, team_size=15, **kwargs)
        print('[ROOF CRUSH TEST] temporary fixture; map=37_caucasus '
              'humans=team1 enemies=15_Type59 all_Bots_hold_and_no_fire')

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
