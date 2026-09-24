# -*- coding: utf-8 -*-
"""Presentation-only names for the exact #1513 editor. Never serialize labels.

The main launcher's resolved language is the only locale authority. Map keys,
route IDs and enum values stay identical in active.json and network messages.
Chinese uses full mainland-client-era names; Himmelsdorf follows the user's
explicit spelling, 锡莫尔斯多夫. These are UI names, not new map resources.
"""
from __future__ import annotations

# (Chinese display name, English display name). Exact keys from bot_editor_maps.
MAP_NAMES = {
    '01_karelia': ('卡累利阿', 'Karelia'),
    '02_malinovka': ('马利诺夫卡', 'Malinovka'),
    '04_himmelsdorf': ('锡莫尔斯多夫', 'Himmelsdorf'),
    '05_prohorovka': ('普罗霍洛夫卡', 'Prokhorovka'),
    '06_ensk': ('安斯克', 'Ensk'),
    '07_lakeville': ('拉斯威利', 'Lakeville'),
    '08_ruinberg': ('鲁别克', 'Ruinberg'),
    '10_hills': ('湖边的角逐', 'Mines'),
    '11_murovanka': ('穆勒万卡', 'Murovanka'),
    '13_erlenberg': ('埃勒斯堡', 'Erlenberg'),
    '14_siegfried_line': ('齐格菲防线', 'Siegfried Line'),
    '17_munchen': ('慕尼黑', 'Widepark'),
    '18_cliff': ('海岸争霸', 'Cliff'),
    '19_monastery': ('小镇争夺战', 'Abbey'),
    '22_slough': ('黑暗沼泽', 'Swamp'),
    '23_westfeld': ('韦斯特菲尔德', 'Westfield'),
    '28_desert': ('沙漠小镇', 'Sand River'),
    '29_el_hallouf': ('埃里-哈罗夫', 'El Halluf'),
    '31_airfield': ('阿拉曼机场', 'Airfield'),
    '33_fjord': ('北欧峡湾', 'Fjords'),
    '34_redshire': ('斯特拉特福', 'Redshire'),
    '35_steppes': ('荒蛮之地', 'Steppes'),
    '36_fishing_bay': ('费舍尔湾', "Fisherman's Bay"),
    '37_caucasus': ('胜利之门', 'Mountain Pass'),
    # Preserve the pre-1.0 name, rather than inferring a name from the file ID.
    '38_mannerheim_line': ('极地冰原', 'Arctic Region'),
    '44_north_america': ('里夫奥克斯', 'Live Oaks'),
    '45_north_america': ('州际公路', 'Highway'),
    '47_canada_a': ('寂静海岸', 'Serene Coast'),
    '59_asia_great_wall': ('长城', 'Great Wall'),
    '63_tundra': ('喀秋莎', 'Tundra'),
    '73_asia_korea': ('神圣之谷', 'Sacred Valley'),
    '83_kharkiv': ('哈尔科夫', 'Kharkov'),
    '84_winter': ('飓风小镇', 'Windstorm'),
    '86_himmelsdorf_winter': ('锡莫尔斯多夫（冬季）', 'Winter Himmelsdorf'),
    '92_stalingrad': ('斯大林格勒', 'Stalingrad'),
    '95_lost_city': ('失落小镇', 'Ghost Town'),
    '100_thepit': ('密特朗', 'Mittengard'),
    '101_dday': ('诺曼底', 'Overlord'),
    '103_ruinberg_winter': ('鲁别克（冬季）', 'Winterberg'),
    '112_eiffel_tower_ctf': ('巴黎', 'Paris'),
    '114_czech': ('布拉格', 'Pilsen'),
}

# Tactical authoring labels, not official map-location names. Every built-in
# route in the 41 shipped navigation resources is covered explicitly.
ROUTE_NAMES = {
    'banana': ('香蕉道', 'Banana Road'),
    'beach': ('海滩', 'Beach'),
    'boulevard': ('林荫大道', 'Boulevard'),
    'center': ('中央区域', 'Center'),
    'center_blocks': ('中央街区', 'Central Blocks'),
    'central_basin': ('中央盆地', 'Central Basin'),
    'central_bowl': ('中央洼地', 'Central Bowl'),
    'central_field': ('中央开阔地', 'Central Field'),
    'central_gorge': ('中央峡谷', 'Central Gorge'),
    'central_hills': ('中央丘陵', 'Central Hills'),
    'central_hollow': ('中央低洼地', 'Central Hollow'),
    'central_ridges': ('中央山脊', 'Central Ridges'),
    'central_road': ('中央道路', 'Central Road'),
    'central_streets': ('中央街道', 'Central Streets'),
    'central_village': ('中央村庄', 'Central Village'),
    'city': ('城区', 'City'),
    'cliff': ('悬崖', 'Cliff'),
    'east_city': ('东侧城区', 'Eastern City'),
    'east_coast': ('东侧海岸', 'Eastern Coast'),
    'east_field': ('东侧开阔地', 'Eastern Field'),
    'east_fields': ('东侧田野', 'Eastern Fields'),
    'east_hill_loop': ('东侧山丘环线', 'Eastern Hill Loop'),
    'east_hills': ('东侧丘陵', 'Eastern Hills'),
    'east_rail': ('东侧铁路', 'Eastern Rail'),
    'east_ridge': ('东侧山脊', 'Eastern Ridge'),
    'east_road': ('东侧道路', 'Eastern Road'),
    'east_shelf': ('东侧台地', 'Eastern Shelf'),
    'east_shore': ('东侧岸线', 'Eastern Shore'),
    'east_town': ('东侧城镇', 'Eastern Town'),
    'east_valley': ('东侧山谷', 'Eastern Valley'),
    'east_village': ('东侧村庄', 'Eastern Village'),
    'embankment': ('堤岸', 'Embankment'),
    'factory': ('工厂', 'Factory'),
    'field': ('开阔地', 'Field'),
    'fortification_line': ('防御工事线', 'Fortification Line'),
    'harbor_edge': ('港口外围', 'Harbor Edge'),
    'hill': ('山丘', 'Hill'),
    'hills': ('丘陵', 'Hills'),
    'ice_road': ('冰面道路', 'Ice Road'),
    'lake_north_edge': ('湖泊北岸', 'Northern Lakeshore'),
    'lake_road': ('湖边道路', 'Lakeside Road'),
    'middle_crossing': ('中央通道', 'Middle Crossing'),
    'middle_low': ('中部低地', 'Middle Low Ground'),
    'middle_road': ('中路', 'Middle Road'),
    'middle_village': ('中部村庄', 'Middle Village'),
    'monastery_lane': ('修道院通道', 'Monastery Lane'),
    'north_bridge': ('北侧桥梁', 'Northern Bridge'),
    'north_dunes': ('北侧沙丘', 'Northern Dunes'),
    'north_ridge': ('北侧山脊', 'Northern Ridge'),
    'north_road': ('北侧道路', 'Northern Road'),
    'north_runway': ('北侧跑道', 'Northern Runway'),
    'outskirts': ('城郊', 'Outskirts'),
    'park': ('公园', 'Park'),
    'pit': ('采坑', 'Pit'),
    'plateau': ('高地', 'Plateau'),
    'rail': ('铁路', 'Rail'),
    'rail_line': ('铁路线', 'Rail Line'),
    'railway': ('铁路沿线', 'Railway'),
    'rear_guard': ('后方警戒', 'Rear Guard'),
    'ridge': ('山脊', 'Ridge'),
    'rim_east': ('东侧边缘', 'Eastern Rim'),
    'rim_west': ('西侧边缘', 'Western Rim'),
    'river': ('河道', 'River'),
    'river_crossing': ('渡河通道', 'River Crossing'),
    'river_town': ('河畔城镇', 'Riverside Town'),
    'south_bridge': ('南侧桥梁', 'Southern Bridge'),
    'south_coast': ('南侧海岸', 'Southern Coast'),
    'south_rocks': ('南侧岩区', 'Southern Rocks'),
    'south_town': ('南侧城镇', 'Southern Town'),
    'south_towns': ('南侧城镇群', 'Southern Towns'),
    'south_valley': ('南侧山谷', 'Southern Valley'),
    'southwest_road': ('西南道路', 'Southwestern Road'),
    'square': ('广场', 'Square'),
    'temple': ('寺庙', 'Temple'),
    'tower_east': ('塔楼东侧', 'East of Tower'),
    'tower_west': ('塔楼西侧', 'West of Tower'),
    'town': ('城镇', 'Town'),
    'valley': ('山谷', 'Valley'),
    'village': ('村庄', 'Village'),
    'village_road': ('村庄道路', 'Village Road'),
    'wall_pass': ('城墙通道', 'Wall Passage'),
    'waterfall': ('瀑布', 'Waterfall'),
    'west_city': ('西侧城区', 'Western City'),
    'west_coast': ('西侧海岸', 'Western Coast'),
    'west_field': ('西侧开阔地', 'Western Field'),
    'west_fields': ('西侧田野', 'Western Fields'),
    'west_hills': ('西侧丘陵', 'Western Hills'),
    'west_lake_road': ('西侧湖边道路', 'Western Lakeside Road'),
    'west_lakeside': ('西侧湖岸', 'Western Lakeshore'),
    'west_pass': ('西侧通道', 'Western Passage'),
    'west_ridge': ('西侧山脊', 'Western Ridge'),
    'west_rocks': ('西侧岩区', 'Western Rocks'),
    'west_streets': ('西侧街道', 'Western Streets'),
    'west_town': ('西侧城镇', 'Western Town'),
    'west_valley': ('西侧山谷', 'Western Valley'),
    'west_woods': ('西侧树林', 'Western Woods'),
}

ENUM_NAMES = {
    'class_tag': {
        'all': ('全部车型', 'All vehicle classes'),
        'lightTank': ('轻型坦克', 'Light tank'),
        'mediumTank': ('中型坦克', 'Medium tank'),
        'heavyTank': ('重型坦克', 'Heavy tank'),
        'AT-SPG': ('坦克歼击车', 'Tank destroyer'),
        'SPG': ('自行火炮', 'Self-propelled gun'),
    },
    'skill': {
        '': ('继承', 'Inherit'),
        'rookie': ('新手', 'Rookie'),
        'regular': ('普通', 'Regular'),
        'veteran': ('老兵', 'Veteran'),
        'elite': ('精英', 'Elite'),
    },
    'policy': {
        'preferred': ('优先路线', 'Preferred route'),
        'fixed': ('固定路线', 'Fixed route'),
    },
    'team': {'0': ('全部队伍', 'All teams'), '1': ('队伍 1', 'Team 1'), '2': ('队伍 2', 'Team 2')},
    'slot': {'': ('全部槽位', 'All slots')},
    'crew_level': {'': ('继承', 'Inherit'), '75': ('75%', '75%'), '90': ('90%', '90%'), '100': ('100%', '100%')},
}
PARAM_NAMES = {
    'skill': ('难度', 'Skill'), 'crew_level': ('乘员等级', 'Crew level'),
    'reaction_seconds': ('反应时间（秒）', 'Reaction delay (s)'),
    'patience_seconds': ('首次开火缩圈等待上限（秒）', 'Opening aim patience (s)'),
    'converged_factor': ('接受的缩圈倍数', 'Accepted dispersion factor'),
    'aim_bias_factor': ('瞄准点偏差系数', 'Aim-point bias factor'),
    'lead_error': ('移动目标提前量误差', 'Lead error fraction'),
}
STATUS_NAMES = {
    'baked_route_connected': ('烘焙导航路线连通', 'Baked route connected'),
    'generic_parking_found': ('找到通用停车空间', 'Generic parking space found'),
    'no_generic_parking': ('没有通用停车空间', 'No generic parking space'),
    'waypoint_unusable': ('路径点不可通行', 'Route point is not walkable'),
    'waypoints_disconnected': ('路线不连通', 'Route is disconnected'),
}

def text(pair, language):
    return pair[0 if language == 'zh' else 1]


def map_label(map_id, language):
    # A missing entry must be caught at source/build time, not hidden by an ID.
    return text(MAP_NAMES[map_id], language)


def route_label(route_id, language):
    return text(ROUTE_NAMES[route_id], language)


def enum_label(kind, value, language):
    code = str(value)
    return text(ENUM_NAMES.get(kind, {}).get(code, (code, code)), language)


def parameter_label(name, language):
    return text(PARAM_NAMES.get(name, (name, name)), language)


def parameter_value(name, value, language):
    if name in ENUM_NAMES:
        return enum_label(name, value, language)
    return '%g' % value if isinstance(value, (int, float)) else str(value)


def summary(values, language, separator='; '):
    return separator.join('%s: %s' % (parameter_label(key, language), parameter_value(key, value, language))
                          for key, value in values.items())
