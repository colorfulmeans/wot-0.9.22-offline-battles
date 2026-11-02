"""Diagnostic-only legal default-fitting targets; no invented damage laws."""
import os

ENV = 'WOT_OFFLINE_EQUIPMENT_TEST'
VEHICLES = ('ussr:R45_IS-7', 'usa:A11_T29', 'germany:G16_PzVIB_Tiger_II',
            'germany:G67_VK4502A', 'uk:GB72_AT15', 'uk:GB23_Centurion',
            'france:F17_AMX_13_90', 'usa:A21_T14', 'germany:G25_PzII_Luchs',
            'ussr:R77_KV2', 'usa:A83_T110E4', 'uk:GB11_Caernarvon',
            'usa:A69_T110E5', 'germany:G98_Waffentrager_E100_P', 'france:F28_105_leFH18B2')


def enabled():
    return os.environ.get('WOT_OFFLINE_DIAGNOSTICS') == '1' and os.environ.get(ENV) in ('1', '2', '3', '4')


def matrix_mode():
    return os.environ.get(ENV) if enabled() and os.environ.get(ENV) in ('3', '4') else None


# Same vehicles/modules in both scenes. One legal fitting per vehicle, rather
# than installing mutually exclusive equipment or every directive at once.
MATRIX = (
    (('antifragmentationLining_heavy',), None),
    (('toolbox',), 'toolboxBattleBooster'),
    (('wetCombatPack_class2',), None),
    (('carbonDioxide',), None),
    (('stereoscope', 'camouflageNet'), None),
    (('enhancedAimDrives',), 'enhancedAimDrivesBattleBooster'),
    ((), 'camouflageBattleBooster'),
    ((), 'smoothTurretBattleBooster'),
    ((), 'virtuosoBattleBooster'),
    (('toolbox',), 'smoothDrivingBattleBooster'),
    ((), 'fireFightingBattleBooster'),
    ((), 'sixthSenseBattleBooster'),
    ((), 'rancorousBattleBooster'),
    ((), 'pedantBattleBooster'),
    ((), 'lastEffortBattleBooster'),
)


def fitting(vehicle, plan):
    mode = matrix_mode()
    if mode is None or vehicle not in VEHICLES:
        return plan
    devices, directive = MATRIX[VEHICLES.index(vehicle)]
    plan.update(devices=list(devices) if mode == '4' else [],
                directive=directive if mode == '4' else None, crew=100)
    return plan


def skill_mask(default, tankmen):
    # Grant skill-directive effects to an untrained crew in the matrix. The
    # baseline therefore proves that the item, not learned skills, owns them.
    return tankmen.getSkillsMask(()) if matrix_mode() else default


def governor_mode():
    return enabled() and os.environ.get(ENV) == '2'


def consumables(cache, defaults):
    """Diagnostic-only three-slot governor test, using the native descriptor."""
    if not governor_mode():
        return tuple(defaults)
    from .equipment_mechanics import project_equipment
    descriptor = cache.equipments().get(cache.equipmentIDs().get('removedRpmLimiter'))
    if descriptor is None:
        raise ValueError('Diagnostic governor is unavailable in the native item cache')
    return tuple(defaults[:2]) + (project_equipment(descriptor),)


def install_server(battle_class, planner_class):
    if not enabled() or getattr(battle_class, '_equipment_test_installed', False):
        return
    original_init = battle_class.__init__
    original_start = battle_class.request_start
    def initialize(self, map_name=None, max_players=30, clock=None, team_size=15, **kwargs):
        kwargs.update(team1_size=15, team2_size=15, bot_tier_mode='same',
                      bot_skill_mode='brutal', bot_excluded_vehicles=None,
                      bot_tactics_path=None,
                      bot_lineup=[dict(team=team, slot=slot, vehicle=vehicle, skill='elite')
                                  for team in (1, 2) for slot, vehicle in enumerate(VEHICLES)])
        original_init(self, map_name='100_thepit', max_players=max_players,
                      clock=clock, team_size=15, **kwargs)
        print('[EQUIPMENT TEST] ' + ('native governor driving fixture' if governor_mode()
              else 'legal native fittings; stationary targets; mouse-fire acceptance'))
        if matrix_mode():
            print('[EQUIPMENT TEST] matrix=%s; identical modules; 100%% main qualification; no learned secondary skills' % matrix_mode())
    def start(self, player_id, requested_map=None, requested_round_seconds=None,
              battle_mode='regular', training_bots=False):
        # The room UI can replay its saved mixed/random settings after init.
        self.bot_tier_mode = 'same'
        self.bot_skill_mode = 'brutal'
        return original_start(self, player_id, requested_map='100_thepit',
                              requested_round_seconds=requested_round_seconds,
                              battle_mode=battle_mode, training_bots=training_bots)
    def orders(self, manifest, bot_states, players, now, defense=None, team_orders=None):
        states = dict((row['id'], row) for row in bot_states or ())
        result = []
        for row in manifest or ():
            state = states.get(row['id'], row)
            if not state.get('alive', True):
                continue
            point = dict((key, float(state.get(key, 0))) for key in ('x', 'y', 'z'))
            result.append(dict(id=row['id'], team=row['team'], target_id=None,
                aim_position=None, face_position=None, move_position=point,
                fire_allowed=False, combat_mode='hold', throttle_override=0.,
                route_id=None, route_index=0, route_anchor=dict(point), route_join=False, shell_index=0))
        payload = dict(orders=result)
        if payload != self._last_order_signature:
            self.revision += 1
            self._last_order_signature = payload
        self._last_orders = payload
        return dict(revision=self.revision, orders=result)
    battle_class.__init__ = initialize
    battle_class.request_start = start
    battle_class._equipment_test_installed = True
    if not governor_mode():
        planner_class.build_orders = orders
