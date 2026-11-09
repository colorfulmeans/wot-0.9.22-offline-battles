# -*- coding: utf-8 -*-
"""Map bounds and route allocation metadata for the #1513 Bot director."""


from gui.mods.offline_lan_0922.player_control.copied import bot_tactics


_MAP_METADATA = {
    '01_karelia': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_ridge', 'capacity': 5, 'risk': 0.62, 'hold': True, 'role_weights': {'brawler': 0.35, 'support': 0.78, 'flanker': 0.82, 'sniper': 0.72, 'scout': 0.24, 'artillery': 0.0}, 'class_weights': {'heavyTank': 0.35, 'mediumTank': 1.0, 'lightTank': 0.1, 'AT-SPG': 0.85, 'SPG': 0.0}},
            {'id': 'middle_road', 'capacity': 4, 'risk': 0.56, 'hold': True, 'role_weights': {'brawler': 0.02, 'support': 0.28, 'flanker': 0.5, 'sniper': 0.22, 'scout': 1.0, 'artillery': 0.0}, 'class_weights': {'heavyTank': 0.02, 'mediumTank': 0.3, 'lightTank': 1.0, 'AT-SPG': 0.25, 'SPG': 0.0}},
            {'id': 'east_shelf', 'capacity': 6, 'risk': 0.74, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.72, 'flanker': 0.62, 'sniper': 0.25, 'scout': 0.12, 'artillery': 0.0}, 'class_weights': {'heavyTank': 1.0, 'mediumTank': 0.7, 'lightTank': 0.12, 'AT-SPG': 0.35, 'SPG': 0.0}},
        ),
    }),
    '02_malinovka': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_lake_road', 'capacity': 3, 'risk': 0.62, 'role_weights': {'brawler': 1.0, 'support': 0.7, 'flanker': 0.35, 'sniper': 0.22, 'scout': 0.24, 'artillery': 0.0}},
            {'id': 'central_field', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 0.16, 'support': 0.86, 'flanker': 0.46, 'sniper': 1.0, 'scout': 0.62, 'artillery': 0.18}},
            {'id': 'east_hill_loop', 'capacity': 6, 'risk': 0.78, 'role_weights': {'brawler': 0.32, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.42, 'scout': 0.86, 'artillery': 0.02}},
        ),
    }),
    '04_himmelsdorf': ((-300.0, -300.0, 400.0, 400.0), {
        1: (
            {'id': 'banana', 'capacity': 6, 'risk': 0.62, 'role_weights': {'brawler': 1.0, 'support': 0.58, 'flanker': 0.3, 'sniper': 0.1, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'hill', 'capacity': 4, 'risk': 0.78, 'role_weights': {'brawler': 0.35, 'support': 0.58, 'flanker': 1.0, 'sniper': 0.18, 'scout': 0.72, 'artillery': 0.0}},
            {'id': 'rail', 'capacity': 4, 'risk': 0.42, 'role_weights': {'brawler': 0.18, 'support': 0.62, 'flanker': 0.58, 'sniper': 1.0, 'scout': 0.88, 'artillery': 0.12}},
            {'id': 'rear_guard', 'capacity': 2, 'risk': 0.08, 'role_weights': {'brawler': 0.0, 'support': 0.18, 'flanker': 0.0, 'sniper': 0.28, 'scout': 0.0, 'artillery': 1.0}},
        ),
    }),
    '05_prohorovka': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_ridge', 'capacity': 4, 'risk': 0.78, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
            {'id': 'central_field', 'capacity': 5, 'risk': 0.66, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'rail_line', 'capacity': 5, 'risk': 0.7, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
        ),
    }),
    '06_ensk': ((-300.0, -300.0, 300.0, 300.0), {
        1: (
            {'id': 'west_city', 'capacity': 7, 'risk': 0.64, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'east_field', 'capacity': 7, 'risk': 0.73, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '07_lakeville': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'west_valley', 'capacity': 5, 'risk': 0.63, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'lake_road', 'capacity': 4, 'risk': 0.62, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'east_town', 'capacity': 5, 'risk': 0.74, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '08_ruinberg': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'west_city', 'capacity': 6, 'risk': 0.66, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'central_streets', 'capacity': 4, 'risk': 0.67, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'east_fields', 'capacity': 5, 'risk': 0.72, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '100_thepit': ((-250.0, -300.0, 350.0, 300.0), {
        1: (
            {'id': 'rim_west', 'capacity': 5, 'risk': 0.6, 'role_weights': {'brawler': 0.8, 'support': 0.5, 'flanker': 0.5, 'sniper': 0.3, 'scout': 0.3, 'artillery': 0.0}},
            {'id': 'pit', 'capacity': 5, 'risk': 0.75, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'rim_east', 'capacity': 5, 'risk': 0.4, 'role_weights': {'brawler': 0.2, 'support': 0.6, 'flanker': 0.9, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '101_dday': ((-400.0, -500.0, 600.0, 500.0), {
        1: (
            {'id': 'beach', 'capacity': 5, 'risk': 0.55, 'role_weights': {'brawler': 0.7, 'support': 0.8, 'flanker': 0.5, 'sniper': 0.3, 'scout': 0.4, 'artillery': 0.0}},
            {'id': 'village', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'cliff', 'capacity': 5, 'risk': 0.42, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.9, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '103_ruinberg_winter': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'city', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'field', 'capacity': 5, 'risk': 0.38, 'role_weights': {'brawler': 0.1, 'support': 0.6, 'flanker': 0.9, 'sniper': 1, 'scout': 0.9, 'artillery': 0.0}},
            {'id': 'rail', 'capacity': 5, 'risk': 0.52, 'role_weights': {'brawler': 0.5, 'support': 1, 'flanker': 0.7, 'sniper': 0.5, 'scout': 0.5, 'artillery': 0.0}},
        ),
    }),
    '10_hills': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'southwest_road', 'capacity': 5, 'risk': 0.66, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'central_hills', 'capacity': 4, 'risk': 0.72, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'east_coast', 'capacity': 4, 'risk': 0.77, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '112_eiffel_tower_ctf': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'tower_west', 'capacity': 5, 'risk': 0.65, 'role_weights': {'brawler': 0.9, 'support': 0.7, 'flanker': 0.3, 'sniper': 0.2, 'scout': 0.2, 'artillery': 0.0}},
            {'id': 'center', 'capacity': 5, 'risk': 0.78, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'tower_east', 'capacity': 5, 'risk': 0.4, 'role_weights': {'brawler': 0.1, 'support': 0.6, 'flanker': 0.9, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '114_czech': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'town', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'valley', 'capacity': 5, 'risk': 0.5, 'role_weights': {'brawler': 0.4, 'support': 1, 'flanker': 0.8, 'sniper': 0.5, 'scout': 0.7, 'artillery': 0.0}},
            {'id': 'ridge', 'capacity': 5, 'risk': 0.4, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.8, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '11_murovanka': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_woods', 'capacity': 5, 'risk': 0.66, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'central_field', 'capacity': 4, 'risk': 0.65, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'east_village', 'capacity': 4, 'risk': 0.74, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '13_erlenberg': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_bridge', 'capacity': 5, 'risk': 0.72, 'hold': True, 'role_weights': {'brawler': 1.0, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.18, 'artillery': 0.0}},
            {'id': 'middle_crossing', 'capacity': 4, 'risk': 0.76, 'hold': True, 'role_weights': {'brawler': 0.16, 'support': 0.82, 'flanker': 0.52, 'sniper': 1.0, 'scout': 0.64, 'artillery': 0.12}},
            {'id': 'south_bridge', 'capacity': 4, 'risk': 0.74, 'hold': True, 'role_weights': {'brawler': 0.26, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.4, 'scout': 0.82, 'artillery': 0.0}},
        ),
    }),
    '14_siegfried_line': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_field', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 0.32, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.42, 'scout': 0.86, 'artillery': 0.02}},
            {'id': 'fortification_line', 'capacity': 4, 'risk': 0.66, 'role_weights': {'brawler': 0.16, 'support': 0.86, 'flanker': 0.46, 'sniper': 1.0, 'scout': 0.62, 'artillery': 0.18}},
            {'id': 'east_city', 'capacity': 6, 'risk': 0.64, 'role_weights': {'brawler': 1.0, 'support': 0.7, 'flanker': 0.35, 'sniper': 0.22, 'scout': 0.24, 'artillery': 0.0}},
        ),
    }),
    '17_munchen': ((-300.0, -300.0, 300.0, 300.0), {
        1: (
            {'id': 'west_streets', 'capacity': 5, 'risk': 0.61, 'role_weights': {'brawler': 0.9, 'support': 0.65, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.22, 'artillery': 0.0}, 'hold': (-55, 195, 0)},
            {'id': 'east_rail', 'capacity': 4, 'risk': 0.48, 'role_weights': {'brawler': 0.25, 'support': 0.72, 'flanker': 0.65, 'sniper': 1.0, 'scout': 0.62, 'artillery': 0.12}, 'hold': (100, 180, 0)},
            {'id': 'center_blocks', 'capacity': 3, 'risk': 0.78, 'role_weights': {'brawler': 0.75, 'support': 1.0, 'flanker': 0.42, 'sniper': 0.22, 'scout': 0.3, 'artillery': 0.0}, 'hold': (60, 185, 0)},
        ),
        2: (
            {'id': 'west_streets', 'capacity': 5, 'risk': 0.61, 'role_weights': {'brawler': 0.9, 'support': 0.65, 'flanker': 0.3, 'sniper': 0.12, 'scout': 0.22, 'artillery': 0.0}, 'hold': (-80, -190, 0)},
            {'id': 'east_rail', 'capacity': 4, 'risk': 0.48, 'role_weights': {'brawler': 0.25, 'support': 0.72, 'flanker': 0.65, 'sniper': 1.0, 'scout': 0.62, 'artillery': 0.12}, 'hold': (-55, -190, 0)},
            {'id': 'center_blocks', 'capacity': 3, 'risk': 0.78, 'role_weights': {'brawler': 0.75, 'support': 1.0, 'flanker': 0.42, 'sniper': 0.22, 'scout': 0.3, 'artillery': 0.0}, 'hold': (-80, -175, 0)},
        ),
    }),
    '18_cliff': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_coast', 'capacity': 4, 'risk': 0.58, 'role_weights': {'brawler': 0.55, 'support': 0.88, 'flanker': 0.6, 'sniper': 0.72, 'scout': 0.48, 'artillery': 0.08}, 'hold': (-285, 390, 0)},
            {'id': 'central_road', 'capacity': 5, 'risk': 0.73, 'role_weights': {'brawler': 0.92, 'support': 0.7, 'flanker': 0.35, 'sniper': 0.15, 'scout': 0.22, 'artillery': 0.0}, 'hold': (-240, 385, 0)},
            {'id': 'east_ridge', 'capacity': 3, 'risk': 0.76, 'role_weights': {'brawler': 0.32, 'support': 0.68, 'flanker': 1.0, 'sniper': 0.66, 'scout': 0.9, 'artillery': 0.0}, 'hold': (-120, 340, 0)},
        ),
        2: (
            {'id': 'west_coast', 'capacity': 4, 'risk': 0.58, 'role_weights': {'brawler': 0.55, 'support': 0.88, 'flanker': 0.6, 'sniper': 0.72, 'scout': 0.48, 'artillery': 0.08}, 'hold': (-290, -420, 0)},
            {'id': 'central_road', 'capacity': 5, 'risk': 0.73, 'role_weights': {'brawler': 0.92, 'support': 0.7, 'flanker': 0.35, 'sniper': 0.15, 'scout': 0.22, 'artillery': 0.0}, 'hold': (-280, -420, 0)},
            {'id': 'east_ridge', 'capacity': 3, 'risk': 0.76, 'role_weights': {'brawler': 0.32, 'support': 0.68, 'flanker': 1.0, 'sniper': 0.66, 'scout': 0.9, 'artillery': 0.0}, 'hold': (-270, -420, 0)},
        ),
    }),
    '19_monastery': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_field', 'capacity': 4, 'risk': 0.51, 'role_weights': {'brawler': 0.48, 'support': 0.78, 'flanker': 0.64, 'sniper': 0.86, 'scout': 0.54, 'artillery': 0.1}, 'hold': (-80, 345, 0)},
            {'id': 'monastery_lane', 'capacity': 5, 'risk': 0.79, 'role_weights': {'brawler': 1.0, 'support': 0.72, 'flanker': 0.28, 'sniper': 0.1, 'scout': 0.15, 'artillery': 0.0}, 'hold': (-5, 350, 0)},
            {'id': 'east_hills', 'capacity': 3, 'risk': 0.7, 'role_weights': {'brawler': 0.34, 'support': 0.68, 'flanker': 1.0, 'sniper': 0.76, 'scout': 0.88, 'artillery': 0.0}, 'hold': (55, 350, 0)},
        ),
        2: (
            {'id': 'west_field', 'capacity': 4, 'risk': 0.51, 'role_weights': {'brawler': 0.48, 'support': 0.78, 'flanker': 0.64, 'sniper': 0.86, 'scout': 0.54, 'artillery': 0.1}, 'hold': (15, -370, 0)},
            {'id': 'monastery_lane', 'capacity': 5, 'risk': 0.79, 'role_weights': {'brawler': 1.0, 'support': 0.72, 'flanker': 0.28, 'sniper': 0.1, 'scout': 0.15, 'artillery': 0.0}, 'hold': (20, -370, 0)},
            {'id': 'east_hills', 'capacity': 3, 'risk': 0.7, 'role_weights': {'brawler': 0.34, 'support': 0.68, 'flanker': 1.0, 'sniper': 0.76, 'scout': 0.88, 'artillery': 0.0}, 'hold': (35, -370, 0)},
        ),
    }),
    '22_slough': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_ridge', 'capacity': 4, 'risk': 0.57, 'role_weights': {'brawler': 0.48, 'support': 0.78, 'flanker': 0.72, 'sniper': 0.82, 'scout': 0.5, 'artillery': 0.1}, 'hold': (345, 400, 0)},
            {'id': 'middle_low', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 0.95, 'support': 0.76, 'flanker': 0.36, 'sniper': 0.15, 'scout': 0.22, 'artillery': 0.0}, 'hold': (350, 400, 0)},
            {'id': 'east_ridge', 'capacity': 3, 'risk': 0.69, 'role_weights': {'brawler': 0.35, 'support': 0.65, 'flanker': 1.0, 'sniper': 0.7, 'scout': 0.94, 'artillery': 0.0}, 'hold': (360, 395, 0)},
        ),
        2: (
            {'id': 'west_ridge', 'capacity': 4, 'risk': 0.57, 'role_weights': {'brawler': 0.48, 'support': 0.78, 'flanker': 0.72, 'sniper': 0.82, 'scout': 0.5, 'artillery': 0.1}, 'hold': (-385, -405, 0)},
            {'id': 'middle_low', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 0.95, 'support': 0.76, 'flanker': 0.36, 'sniper': 0.15, 'scout': 0.22, 'artillery': 0.0}, 'hold': (-385, -405, 0)},
            {'id': 'east_ridge', 'capacity': 3, 'risk': 0.69, 'role_weights': {'brawler': 0.35, 'support': 0.65, 'flanker': 1.0, 'sniper': 0.7, 'scout': 0.94, 'artillery': 0.0}, 'hold': (-380, -405, 0)},
        ),
    }),
    '23_westfeld': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.67, 'role_weights': {'brawler': 0.34, 'support': 0.75, 'flanker': 1.0, 'sniper': 0.82, 'scout': 0.82, 'artillery': 0.0}, 'hold': (339, 300, 0)},
            {'id': 'central_village', 'capacity': 5, 'risk': 0.75, 'role_weights': {'brawler': 0.95, 'support': 0.72, 'flanker': 0.34, 'sniper': 0.12, 'scout': 0.2, 'artillery': 0.0}, 'hold': (339, 300, 0)},
            {'id': 'east_fields', 'capacity': 4, 'risk': 0.5, 'role_weights': {'brawler': 0.45, 'support': 0.88, 'flanker': 0.58, 'sniper': 1.0, 'scout': 0.46, 'artillery': 0.16}, 'hold': (339, 300, 0)},
        ),
        2: (
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.67, 'role_weights': {'brawler': 0.34, 'support': 0.75, 'flanker': 1.0, 'sniper': 0.82, 'scout': 0.82, 'artillery': 0.0}, 'hold': (-300, -340, 0)},
            {'id': 'central_village', 'capacity': 5, 'risk': 0.75, 'role_weights': {'brawler': 0.95, 'support': 0.72, 'flanker': 0.34, 'sniper': 0.12, 'scout': 0.2, 'artillery': 0.0}, 'hold': (-300, -340, 0)},
            {'id': 'east_fields', 'capacity': 4, 'risk': 0.5, 'role_weights': {'brawler': 0.45, 'support': 0.88, 'flanker': 0.58, 'sniper': 1.0, 'scout': 0.46, 'artillery': 0.16}, 'hold': (-300, -340, 0)},
        ),
    }),
    '28_desert': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_dunes', 'capacity': 3, 'risk': 0.69, 'role_weights': {'brawler': 0.3, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.76, 'scout': 0.92, 'artillery': 0.0}, 'hold': (-405, 138, 0)},
            {'id': 'village_road', 'capacity': 5, 'risk': 0.78, 'role_weights': {'brawler': 0.92, 'support': 0.78, 'flanker': 0.36, 'sniper': 0.14, 'scout': 0.24, 'artillery': 0.0}, 'hold': (-405, 138, 0)},
            {'id': 'south_rocks', 'capacity': 4, 'risk': 0.56, 'role_weights': {'brawler': 0.5, 'support': 0.86, 'flanker': 0.6, 'sniper': 1.0, 'scout': 0.46, 'artillery': 0.12}, 'hold': (-405, 138, 0)},
        ),
        2: (
            {'id': 'north_dunes', 'capacity': 3, 'risk': 0.69, 'role_weights': {'brawler': 0.3, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.76, 'scout': 0.92, 'artillery': 0.0}, 'hold': (373, -179, 0)},
            {'id': 'village_road', 'capacity': 5, 'risk': 0.78, 'role_weights': {'brawler': 0.92, 'support': 0.78, 'flanker': 0.36, 'sniper': 0.14, 'scout': 0.24, 'artillery': 0.0}, 'hold': (373, -179, 0)},
            {'id': 'south_rocks', 'capacity': 4, 'risk': 0.56, 'role_weights': {'brawler': 0.5, 'support': 0.86, 'flanker': 0.6, 'sniper': 1.0, 'scout': 0.46, 'artillery': 0.12}, 'hold': (373, -179, 0)},
        ),
    }),
    '29_el_hallouf': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'south_valley', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 0.94, 'support': 0.78, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.2, 'artillery': 0.0}, 'hold': (410, 270, 0)},
            {'id': 'central_bowl', 'capacity': 4, 'risk': 0.77, 'role_weights': {'brawler': 0.76, 'support': 0.92, 'flanker': 0.48, 'sniper': 0.36, 'scout': 0.42, 'artillery': 0.0}, 'hold': (410, 270, 0)},
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.65, 'role_weights': {'brawler': 0.3, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.92, 'scout': 0.88, 'artillery': 0.0}, 'hold': (410, 275, 0)},
        ),
        2: (
            {'id': 'south_valley', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 0.94, 'support': 0.78, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.2, 'artillery': 0.0}, 'hold': (-270, -380, 0)},
            {'id': 'central_bowl', 'capacity': 4, 'risk': 0.77, 'role_weights': {'brawler': 0.76, 'support': 0.92, 'flanker': 0.48, 'sniper': 0.36, 'scout': 0.42, 'artillery': 0.0}, 'hold': (-270, -380, 0)},
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.65, 'role_weights': {'brawler': 0.3, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.92, 'scout': 0.88, 'artillery': 0.0}, 'hold': (-270, -375, 0)},
        ),
    }),
    '31_airfield': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_runway', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 0.32, 'support': 0.62, 'flanker': 1.0, 'sniper': 0.42, 'scout': 0.86, 'artillery': 0.02}},
            {'id': 'central_ridges', 'capacity': 4, 'risk': 0.68, 'role_weights': {'brawler': 0.16, 'support': 0.86, 'flanker': 0.46, 'sniper': 1.0, 'scout': 0.62, 'artillery': 0.18}},
            {'id': 'south_towns', 'capacity': 5, 'risk': 0.65, 'role_weights': {'brawler': 1.0, 'support': 0.7, 'flanker': 0.35, 'sniper': 0.22, 'scout': 0.24, 'artillery': 0.0}},
        ),
    }),
    '33_fjord': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.66, 'role_weights': {'brawler': 0.32, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.88, 'scout': 0.86, 'artillery': 0.0}, 'hold': (-365, 110, 0)},
            {'id': 'middle_village', 'capacity': 5, 'risk': 0.8, 'role_weights': {'brawler': 0.96, 'support': 0.78, 'flanker': 0.32, 'sniper': 0.14, 'scout': 0.18, 'artillery': 0.0}, 'hold': (-365, 110, 0)},
            {'id': 'south_coast', 'capacity': 4, 'risk': 0.55, 'role_weights': {'brawler': 0.46, 'support': 0.88, 'flanker': 0.62, 'sniper': 1.0, 'scout': 0.42, 'artillery': 0.14}, 'hold': (-365, 105, 0)},
        ),
        2: (
            {'id': 'north_ridge', 'capacity': 3, 'risk': 0.66, 'role_weights': {'brawler': 0.32, 'support': 0.7, 'flanker': 1.0, 'sniper': 0.88, 'scout': 0.86, 'artillery': 0.0}, 'hold': (380, -35, 0)},
            {'id': 'middle_village', 'capacity': 5, 'risk': 0.8, 'role_weights': {'brawler': 0.96, 'support': 0.78, 'flanker': 0.32, 'sniper': 0.14, 'scout': 0.18, 'artillery': 0.0}, 'hold': (380, -40, 0)},
            {'id': 'south_coast', 'capacity': 4, 'risk': 0.55, 'role_weights': {'brawler': 0.46, 'support': 0.88, 'flanker': 0.62, 'sniper': 1.0, 'scout': 0.42, 'artillery': 0.14}, 'hold': (380, -50, 0)},
        ),
    }),
    '34_redshire': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'east_ridge', 'capacity': 4, 'risk': 0.57, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
            {'id': 'river_town', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'west_fields', 'capacity': 4, 'risk': 0.49, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
        ),
    }),
    '35_steppes': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'east_ridge', 'capacity': 4, 'risk': 0.55, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
            {'id': 'central_hollow', 'capacity': 5, 'risk': 0.74, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'west_rocks', 'capacity': 4, 'risk': 0.52, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
        ),
    }),
    '36_fishing_bay': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_fields', 'capacity': 5, 'risk': 0.51, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
            {'id': 'central_road', 'capacity': 5, 'risk': 0.69, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'harbor_edge', 'capacity': 3, 'risk': 0.63, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
        ),
    }),
    '37_caucasus': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_pass', 'capacity': 5, 'risk': 0.71, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'central_basin', 'capacity': 4, 'risk': 0.61, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
            {'id': 'east_road', 'capacity': 3, 'risk': 0.58, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
        ),
    }),
    '38_mannerheim_line': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'east_ridge', 'capacity': 4, 'risk': 0.56, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
            {'id': 'central_gorge', 'capacity': 5, 'risk': 0.76, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'west_lakeside', 'capacity': 3, 'risk': 0.64, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
        ),
    }),
    '44_north_america': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_town', 'capacity': 5, 'risk': 0.73, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'east_valley', 'capacity': 4, 'risk': 0.65, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
            {'id': 'lake_north_edge', 'capacity': 3, 'risk': 0.52, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
        ),
    }),
    '45_north_america': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_road', 'capacity': 4, 'risk': 0.55, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
            {'id': 'river_crossing', 'capacity': 5, 'risk': 0.76, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'south_town', 'capacity': 4, 'risk': 0.63, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
        ),
    }),
    '47_canada_a': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'west_hills', 'capacity': 4, 'risk': 0.61, 'role_weights': {'brawler': 0.42, 'support': 0.64, 'flanker': 1.0, 'sniper': 0.44, 'scout': 0.78, 'artillery': 0.08}},
            {'id': 'central_road', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1.0, 'support': 0.62, 'flanker': 0.38, 'sniper': 0.16, 'scout': 0.28, 'artillery': 0.0}},
            {'id': 'east_shore', 'capacity': 3, 'risk': 0.54, 'role_weights': {'brawler': 0.22, 'support': 0.92, 'flanker': 0.55, 'sniper': 1.0, 'scout': 0.52, 'artillery': 0.2}},
        ),
    }),
    '59_asia_great_wall': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'wall_pass', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 1, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.2, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'valley', 'capacity': 5, 'risk': 0.55, 'role_weights': {'brawler': 0.4, 'support': 0.8, 'flanker': 0.8, 'sniper': 0.4, 'scout': 0.7, 'artillery': 0.0}},
            {'id': 'ridge', 'capacity': 5, 'risk': 0.38, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.7, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '63_tundra': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'waterfall', 'capacity': 5, 'risk': 0.68, 'role_weights': {'brawler': 0.8, 'support': 0.6, 'flanker': 0.4, 'sniper': 0.2, 'scout': 0.2, 'artillery': 0.0}},
            {'id': 'plateau', 'capacity': 5, 'risk': 0.44, 'role_weights': {'brawler': 0.2, 'support': 0.7, 'flanker': 0.8, 'sniper': 0.8, 'scout': 0.9, 'artillery': 0.0}},
            {'id': 'village', 'capacity': 5, 'risk': 0.57, 'role_weights': {'brawler': 0.7, 'support': 1, 'flanker': 0.4, 'sniper': 0.5, 'scout': 0.3, 'artillery': 0.0}},
        ),
    }),
    '73_asia_korea': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'temple', 'capacity': 5, 'risk': 0.66, 'role_weights': {'brawler': 0.9, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.2, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'river', 'capacity': 5, 'risk': 0.52, 'role_weights': {'brawler': 0.4, 'support': 0.9, 'flanker': 0.8, 'sniper': 0.5, 'scout': 0.7, 'artillery': 0.0}},
            {'id': 'hills', 'capacity': 5, 'risk': 0.43, 'role_weights': {'brawler': 0.1, 'support': 0.4, 'flanker': 0.8, 'sniper': 1, 'scout': 1, 'artillery': 0.0}},
        ),
    }),
    '83_kharkiv': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'factory', 'capacity': 5, 'risk': 0.71, 'role_weights': {'brawler': 1, 'support': 0.7, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'square', 'capacity': 5, 'risk': 0.61, 'role_weights': {'brawler': 0.7, 'support': 1, 'flanker': 0.5, 'sniper': 0.5, 'scout': 0.3, 'artillery': 0.0}},
            {'id': 'rail', 'capacity': 5, 'risk': 0.35, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.8, 'sniper': 1, 'scout': 0.8, 'artillery': 0.0}},
        ),
    }),
    '84_winter': ((-500.0, -500.0, 500.0, 500.0), {
        1: (
            {'id': 'north_ridge', 'capacity': 5, 'risk': 0.48, 'role_weights': {'brawler': 0.3, 'support': 0.6, 'flanker': 0.9, 'sniper': 0.9, 'scout': 1, 'artillery': 0.0}},
            {'id': 'ice_road', 'capacity': 5, 'risk': 0.58, 'role_weights': {'brawler': 0.5, 'support': 0.9, 'flanker': 0.7, 'sniper': 0.5, 'scout': 0.6, 'artillery': 0.0}},
            {'id': 'town', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
        ),
    }),
    '86_himmelsdorf_winter': ((-300.0, -300.0, 400.0, 400.0), {
        1: (
            {'id': 'banana', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1, 'support': 0.6, 'flanker': 0.3, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'hill', 'capacity': 5, 'risk': 0.75, 'role_weights': {'brawler': 0.3, 'support': 0.5, 'flanker': 1, 'sniper': 0.2, 'scout': 0.8, 'artillery': 0.0}},
            {'id': 'rail', 'capacity': 5, 'risk': 0.4, 'role_weights': {'brawler': 0.1, 'support': 0.6, 'flanker': 0.6, 'sniper': 1, 'scout': 0.8, 'artillery': 0.0}},
        ),
    }),
    '92_stalingrad': ((-500.0, -500.0, 450.0, 450.0), {
        1: (
            {'id': 'city', 'capacity': 5, 'risk': 0.72, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'railway', 'capacity': 5, 'risk': 0.5, 'role_weights': {'brawler': 0.4, 'support': 1, 'flanker': 0.7, 'sniper': 0.7, 'scout': 0.6, 'artillery': 0.0}},
            {'id': 'embankment', 'capacity': 5, 'risk': 0.38, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.8, 'sniper': 1, 'scout': 0.9, 'artillery': 0.0}},
        ),
    }),
    '95_lost_city': ((-400.0, -400.0, 400.0, 400.0), {
        1: (
            {'id': 'boulevard', 'capacity': 5, 'risk': 0.7, 'role_weights': {'brawler': 1, 'support': 0.8, 'flanker': 0.2, 'sniper': 0.1, 'scout': 0.1, 'artillery': 0.0}},
            {'id': 'park', 'capacity': 5, 'risk': 0.5, 'role_weights': {'brawler': 0.3, 'support': 1, 'flanker': 0.8, 'sniper': 0.6, 'scout': 0.7, 'artillery': 0.0}},
            {'id': 'outskirts', 'capacity': 5, 'risk': 0.35, 'role_weights': {'brawler': 0.1, 'support': 0.5, 'flanker': 0.8, 'sniper': 1, 'scout': 0.9, 'artillery': 0.0}},
        ),
    }),
}


def _build_tactical_maps():
    document = bot_tactics.default_profile()
    for name, (bounds, metadata) in _MAP_METADATA.items():
        settings = bot_tactics.map_settings(document, name)
        shared = bot_tactics.shared_route_points(settings)
        routes = {}
        for team in (1, 2):
            rows = metadata.get(team, metadata[1])
            routes[team] = tuple(dict(row, waypoints=tuple(tuple(p[:3]) for p in
                                 shared[(team, row['id'])])) for row in rows)
        yield name, dict(name=name, bounds=bounds, routes=routes, _routes_are_baked=True)


TACTICAL_MAPS = dict(_build_tactical_maps())


def normalize_map_name(map_name):
    name = str(map_name or '').replace('\\', '/').split('/')[-1]
    if name.endswith('.xml'):
        name = name[:-4]
    return name.lower()


def get_tactical_map(map_name):
    return TACTICAL_MAPS.get(normalize_map_name(map_name))


def default_route_catalog(map_name):
    """Return the reviewed Default, never geometry from an older graph.

    The graph supplies terrain and links, not another tactical-route source.
    Keep the same allocation fields emitted by the physical baker and give
    each caller independent mutable records. Class variants are applied by
    bot_tactics_runtime from the same owner-authored document.
    """
    import copy
    tactical = get_tactical_map(map_name)
    if tactical is None:
        raise bot_tactics.TacticsError('Unknown Default map: %s' % map_name)
    result = {}
    for team in (1, 2):
        rows = []
        for source in tactical['routes'][team]:
            row = dict((key, copy.deepcopy(source[key])) for key in
                       ('id', 'capacity', 'risk', 'role_weights'))
            row['waypoints'] = [list(point[:2]) + [bool(point[2])]
                                for point in source['waypoints']]
            rows.append(row)
        result[str(team)] = rows
    return result
