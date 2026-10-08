# -*- coding: utf-8 -*-
"""Display-only names for the exact #1513 Bot editor.

Keys remain protocol identifiers, never translated configuration data. Chinese
map names use the mainland legacy names; Himmelsdorf's spelling is the project
owner's explicitly requested 锡默尔斯多夫. Winter and removed maps retain their
pre-1.0 identity rather than borrowing a modern replacement's title.
Built-in route names are editor translations, not official tactical routes.
"""
from __future__ import annotations

MAP_NAMES = {
    '01_karelia': ('卡累利阿', 'Karelia'),
    '02_malinovka': ('马利诺夫卡', 'Malinovka'),
    '04_himmelsdorf': ('锡默尔斯多夫', 'Himmelsdorf'),
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
    '28_desert': ('荒漠小镇', 'Sand River'),
    '29_el_hallouf': ('埃里-哈罗夫', 'El Halluf'),
    '31_airfield': ('阿拉曼机场', 'Airfield'),
    '33_fjord': ('北欧峡湾', 'Fjords'),
    '34_redshire': ('斯特拉特福', 'Redshire'),
    '35_steppes': ('荒蛮之地', 'Steppes'),
    '36_fishing_bay': ('费舍尔湾', "Fisherman's Bay"),
    '37_caucasus': ('胜利之门', 'Mountain Pass'),
    '38_mannerheim_line': ('极地冰原', 'Arctic Region'),
    '44_north_america': ('里夫奥克斯', 'Live Oaks'),
    '45_north_america': ('州际公路', 'Highway'),
    '47_canada_a': ('寂静海岸', 'Serene Coast'),
    '59_asia_great_wall': ('钢铁长城', "Empire's Border"),
    '63_tundra': ('喀秋莎', 'Tundra'),
    '73_asia_korea': ('神圣之谷', 'Sacred Valley'),
    '83_kharkiv': ('哈尔科夫', 'Kharkov'),
    '84_winter': ('飓风小镇', 'Windstorm'),
    '86_himmelsdorf_winter': ('锡默尔斯多夫（冬季）', 'Winter Himmelsdorf'),
    '92_stalingrad': ('斯大林格勒', 'Stalingrad'),
    '95_lost_city': ('失落小镇', 'Ghost Town'),
    '100_thepit': ('密特朗', 'Mittengard'),
    '101_dday': ('诺曼底', 'Overlord'),
    '103_ruinberg_winter': ('鲁别克（冬季）', 'Winterberg'),
    '112_eiffel_tower_ctf': ('巴黎', 'Paris'),
    '114_czech': ('布拉格', 'Pilsen'),
}

# Every distinct built-in route in the 41 pinned navigation resources.
_ROUTE_ZH = {
    'banana': '香蕉弯道', 'beach': '海滩', 'boulevard': '林荫大道',
    'center': '中央区域', 'center_blocks': '中央街区',
    'central_basin': '中央盆地', 'central_bowl': '中央洼地',
    'central_field': '中央旷野', 'central_gorge': '中央峡谷',
    'central_hills': '中央丘陵', 'central_hollow': '中央低洼地',
    'central_ridges': '中央山脊', 'central_road': '中央道路',
    'central_streets': '中央街道', 'central_village': '中央村庄',
    'city': '城区', 'cliff': '悬崖', 'east_city': '东侧城区',
    'east_coast': '东侧海岸', 'east_field': '东侧旷野',
    'east_fields': '东侧田野', 'east_hill_loop': '东侧山丘环线',
    'east_hills': '东侧丘陵', 'east_rail': '东侧铁路',
    'east_ridge': '东侧山脊', 'east_road': '东侧道路',
    'east_shelf': '东侧台地', 'east_shore': '东侧岸线',
    'east_town': '东侧城镇', 'east_valley': '东侧山谷',
    'east_village': '东侧村庄', 'embankment': '堤岸', 'factory': '工厂',
    'field': '旷野', 'fortification_line': '防御工事线',
    'harbor_edge': '港口外围', 'hill': '山丘', 'hills': '丘陵',
    'ice_road': '冰面道路', 'lake_north_edge': '湖泊北岸',
    'lake_road': '湖边道路', 'middle_crossing': '中央渡口',
    'middle_low': '中央低地', 'middle_road': '中路',
    'middle_village': '中部村庄', 'monastery_lane': '修道院通道',
    'north_bridge': '北侧桥梁', 'north_dunes': '北侧沙丘',
    'north_ridge': '北侧山脊', 'north_road': '北侧道路',
    'north_runway': '北侧跑道', 'outskirts': '城郊', 'park': '公园',
    'pit': '深坑', 'plateau': '高原', 'rail': '铁路线',
    'rail_line': '铁路沿线', 'railway': '铁路', 'rear_guard': '后方守备',
    'ridge': '山脊', 'rim_east': '东侧边缘', 'rim_west': '西侧边缘',
    'river': '河流', 'river_crossing': '渡河点', 'river_town': '河畔城镇',
    'south_bridge': '南侧桥梁', 'south_coast': '南侧海岸',
    'south_rocks': '南侧岩石区', 'south_town': '南侧城镇',
    'south_towns': '南侧村镇群', 'south_valley': '南侧山谷',
    'southwest_road': '西南道路', 'square': '广场', 'temple': '寺庙',
    'tower_east': '铁塔东侧', 'tower_west': '铁塔西侧',
    'town': '城镇', 'valley': '山谷', 'village': '村庄',
    'village_road': '村庄道路', 'wall_pass': '城墙隘口', 'waterfall': '瀑布',
    'west_city': '西侧城区', 'west_coast': '西侧海岸',
    'west_field': '西侧旷野', 'west_fields': '西侧田野',
    'west_hills': '西侧丘陵', 'west_lake_road': '西侧湖滨道路',
    'west_lakeside': '西侧湖岸', 'west_pass': '西侧山口',
    'west_ridge': '西侧山脊', 'west_rocks': '西侧岩石区',
    'west_streets': '西侧街道', 'west_town': '西侧城镇',
    'west_valley': '西侧山谷', 'west_woods': '西侧树林',
}
ROUTE_NAMES = {key: (value, key.replace('_', ' ').capitalize())
               for key, value in _ROUTE_ZH.items()}
ROUTE_NAMES.update({
    'banana': ('香蕉弯道', 'Banana bend'), 'rear_guard': ('后方守备', 'Rear guard'),
    'rail': ('铁路线', 'Rail line'), 'rim_east': ('东侧边缘', 'Eastern rim'),
    'rim_west': ('西侧边缘', 'Western rim'),
    'tower_east': ('铁塔东侧', 'East of the tower'),
    'tower_west': ('铁塔西侧', 'West of the tower'),
})

ENUM_NAMES = {
    'class_tag': {
        'total': ('总路线', 'All class routes'),
        'all': ('全部车型', 'All vehicle classes'),
        'lightTank': ('轻型坦克', 'Light tank'),
        'mediumTank': ('中型坦克', 'Medium tank'),
        'heavyTank': ('重型坦克', 'Heavy tank'),
        'AT-SPG': ('坦克歼击车', 'Tank destroyer'),
        'SPG': ('自行火炮', 'Self-propelled gun'),
    },
    'skill': {'': ('继承上级设置', 'Inherit'),
              'rookie': ('新手', 'Rookie'), 'regular': ('普通', 'Regular'),
              'veteran': ('老兵', 'Veteran'), 'elite': ('精英', 'Elite')},
    'policy': {'preferred': ('优先路线', 'Preferred route'),
               'fixed': ('固定路线', 'Fixed route')},
    'crew_level': {'': ('继承上级设置', 'Inherit'),
                   '75': ('75%', '75%'), '90': ('90%', '90%'), '100': ('100%', '100%')},
    'team': {'0': ('全部队伍', 'All teams'), '1': ('队伍 1', 'Team 1'), '2': ('队伍 2', 'Team 2')},
    'slot': {'': ('全部槽位', 'All slots')},
}
PARAM_NAMES = {
    'skill': ('难度', 'Difficulty'), 'crew_level': ('乘员等级', 'Crew level'),
    'reaction_seconds': ('反应时间（秒）', 'Reaction delay (s)'),
    'patience_seconds': ('首次开火缩圈等待上限（秒）', 'Opening aim patience (s)'),
    'converged_factor': ('接受的缩圈倍数', 'Accepted dispersion factor'),
    'aim_bias_factor': ('瞄准点偏差系数', 'Aim-point bias factor'),
    'lead_error': ('移动目标提前量误差', 'Lead error fraction'),
}
VALIDATION_NAMES = {
    'navigation_cells_clear': ('导航格检查：节点及直线连接未发现问题', 'Grid check: nodes and straight connections clear'),
    'navigation_cells_issues': ('导航格检查：发现以下问题', 'Grid check: issues below'),
    'no_navigation_links': ('该导航格没有相邻连接', 'Navigation cell has no neighbour links'),
    'navigation_link_missing': ('直线经过的相邻导航格缺少此方向连接，可能需要绕行', 'Straight segment lacks a directed link; a detour may be needed'),
    'baked_route_connected': ('烘焙导航图上路线连通', 'Baked route connected'),
    'generic_parking_found': ('存在通用停车空间', 'Generic parking space found'),
    'no_generic_parking': ('没有通用停车空间', 'No generic parking space'),
    'connected': ('路线连通', 'Route connected'),
    'waypoint_unusable': ('路径点不可用', 'Waypoint unusable'),
    'wait_place_unusable': ('等待点不可用', 'Wait place unusable'),
    'wait_place_disconnected': ('等待点与路线不连通', 'Wait place disconnected from route'),
    'wait_place_exit_disconnected': ('等待点无法连通后续路线点', 'Wait place cannot reach the next route node'),
    'waypoints_disconnected': ('路径点之间不连通', 'Waypoints disconnected'),
    'outside_bounds': ('超出地图或导航栅格边界', 'Outside arena or navigation grid'),
    'missing_ground': ('该导航格缺少地面高度', 'Navigation cell has no ground height'),
    'navigation_hazard': ('该导航格被标为水域或边界危险区', 'Navigation cell has a water or boundary hazard'),
    'parking_exit_disconnected': ('停车区域内没有连通后续点的位置', 'No parking candidate connects to the next point'),
    'parking_available': ('存在可用停车空间', 'Parking space available'),
    'no_parking_space': ('没有可用停车空间', 'No parking space'),
}


def _label(table, key, language):
    return table.get(key, (str(key), str(key)))[language != 'zh']


def map_label(key, language):
    return _label(MAP_NAMES, key, language)


def route_label(key, language):
    return _label(ROUTE_NAMES, key, language)


def enum_label(kind, key, language):
    return _label(ENUM_NAMES.get(kind, {}), str(key), language)


def parameter_label(key, language):
    return _label(PARAM_NAMES, key, language)


def parameter_value(key, value, language):
    if key in ('skill', 'crew_level'):
        return enum_label(key, value, language)
    return str(value)


def parameter_summary(values, language):
    return '; '.join('%s: %s' % (parameter_label(key, language),
                               parameter_value(key, value, language))
                     for key, value in values.items())


def validation_label(value, language):
    return _label(VALIDATION_NAMES, value, language)


# Display aliases for the adopted author baseline; stored labels remain data.
TACTIC_NAMES = {'香蕉弯道': ('香蕉弯道', 'Banana bend'), 'banana bend': ('香蕉弯道', 'Banana bend'), '海滩': ('海滩', 'Beach'), 'beach': ('海滩', 'Beach'), '林荫大道': ('林荫大道', 'Boulevard'), 'boulevard': ('林荫大道', 'Boulevard'), '中央区域': ('中央区域', 'Center'), 'center': ('中央区域', 'Center'), '中央街区': ('中央街区', 'Center blocks'), 'center blocks': ('中央街区', 'Center blocks'), '中央盆地': ('中央盆地', 'Central basin'), 'central basin': ('中央盆地', 'Central basin'), '中央洼地': ('中央洼地', 'Central bowl'), 'central bowl': ('中央洼地', 'Central bowl'), '中央旷野': ('中央旷野', 'Central field'), 'central field': ('中央旷野', 'Central field'), '中央峡谷': ('中央峡谷', 'Central gorge'), 'central gorge': ('中央峡谷', 'Central gorge'), '中央丘陵': ('中央丘陵', 'Central hills'), 'central hills': ('中央丘陵', 'Central hills'), '中央低洼地': ('中央低洼地', 'Central hollow'), 'central hollow': ('中央低洼地', 'Central hollow'), '中央山脊': ('中央山脊', 'Central ridges'), 'central ridges': ('中央山脊', 'Central ridges'), '中央道路': ('中央道路', 'Central road'), 'central road': ('中央道路', 'Central road'), '中央街道': ('中央街道', 'Central streets'), 'central streets': ('中央街道', 'Central streets'), '中央村庄': ('中央村庄', 'Central village'), 'central village': ('中央村庄', 'Central village'), '城区': ('城区', 'City'), 'city': ('城区', 'City'), '悬崖': ('悬崖', 'Cliff'), 'cliff': ('悬崖', 'Cliff'), '东侧城区': ('东侧城区', 'East city'), 'east city': ('东侧城区', 'East city'), '东侧海岸': ('东侧海岸', 'East coast'), 'east coast': ('东侧海岸', 'East coast'), '东侧旷野': ('东侧旷野', 'East field'), 'east field': ('东侧旷野', 'East field'), '东侧田野': ('东侧田野', 'East fields'), 'east fields': ('东侧田野', 'East fields'), '东侧山丘环线': ('东侧山丘环线', 'East hill loop'), 'east hill loop': ('东侧山丘环线', 'East hill loop'), '东侧丘陵': ('东侧丘陵', 'East hills'), 'east hills': ('东侧丘陵', 'East hills'), '东侧铁路': ('东侧铁路', 'East rail'), 'east rail': ('东侧铁路', 'East rail'), '东侧山脊': ('东侧山脊', 'East ridge'), 'east ridge': ('东侧山脊', 'East ridge'), '东侧道路': ('东侧道路', 'East road'), 'east road': ('东侧道路', 'East road'), '东侧台地': ('东侧台地', 'East shelf'), 'east shelf': ('东侧台地', 'East shelf'), '东侧岸线': ('东侧岸线', 'East shore'), 'east shore': ('东侧岸线', 'East shore'), '东侧城镇': ('东侧城镇', 'East town'), 'east town': ('东侧城镇', 'East town'), '东侧山谷': ('东侧山谷', 'East valley'), 'east valley': ('东侧山谷', 'East valley'), '东侧村庄': ('东侧村庄', 'East village'), 'east village': ('东侧村庄', 'East village'), '堤岸': ('堤岸', 'Embankment'), 'embankment': ('堤岸', 'Embankment'), '工厂': ('工厂', 'Factory'), 'factory': ('工厂', 'Factory'), '旷野': ('旷野', 'Field'), 'field': ('旷野', 'Field'), '防御工事线': ('防御工事线', 'Fortification line'), 'fortification line': ('防御工事线', 'Fortification line'), '港口外围': ('港口外围', 'Harbor edge'), 'harbor edge': ('港口外围', 'Harbor edge'), '山丘': ('山丘', 'Hill'), 'hill': ('山丘', 'Hill'), '丘陵': ('丘陵', 'Hills'), 'hills': ('丘陵', 'Hills'), '冰面道路': ('冰面道路', 'Ice road'), 'ice road': ('冰面道路', 'Ice road'), '湖泊北岸': ('湖泊北岸', 'Lake north edge'), 'lake north edge': ('湖泊北岸', 'Lake north edge'), '湖边道路': ('湖边道路', 'Lake road'), 'lake road': ('湖边道路', 'Lake road'), '中央渡口': ('中央渡口', 'Middle crossing'), 'middle crossing': ('中央渡口', 'Middle crossing'), '中央低地': ('中央低地', 'Middle low'), 'middle low': ('中央低地', 'Middle low'), '中路': ('中路', 'Middle road'), 'middle road': ('中路', 'Middle road'), '中部村庄': ('中部村庄', 'Middle village'), 'middle village': ('中部村庄', 'Middle village'), '修道院通道': ('修道院通道', 'Monastery lane'), 'monastery lane': ('修道院通道', 'Monastery lane'), '北侧桥梁': ('北侧桥梁', 'North bridge'), 'north bridge': ('北侧桥梁', 'North bridge'), '北侧沙丘': ('北侧沙丘', 'North dunes'), 'north dunes': ('北侧沙丘', 'North dunes'), '北侧山脊': ('北侧山脊', 'North ridge'), 'north ridge': ('北侧山脊', 'North ridge'), '北侧道路': ('北侧道路', 'North road'), 'north road': ('北侧道路', 'North road'), '北侧跑道': ('北侧跑道', 'North runway'), 'north runway': ('北侧跑道', 'North runway'), '城郊': ('城郊', 'Outskirts'), 'outskirts': ('城郊', 'Outskirts'), '公园': ('公园', 'Park'), 'park': ('公园', 'Park'), '深坑': ('深坑', 'Pit'), 'pit': ('深坑', 'Pit'), '高原': ('高原', 'Plateau'), 'plateau': ('高原', 'Plateau'), '铁路线': ('铁路线', 'Rail line'), 'rail line': ('铁路沿线', 'Rail line'), '铁路沿线': ('铁路沿线', 'Rail line'), '铁路': ('铁路', 'Railway'), 'railway': ('铁路', 'Railway'), '后方守备': ('后方守备', 'Rear guard'), 'rear guard': ('后方守备', 'Rear guard'), '山脊': ('山脊', 'Ridge'), 'ridge': ('山脊', 'Ridge'), '东侧边缘': ('东侧边缘', 'Eastern rim'), 'eastern rim': ('东侧边缘', 'Eastern rim'), '西侧边缘': ('西侧边缘', 'Western rim'), 'western rim': ('西侧边缘', 'Western rim'), '河流': ('河流', 'River'), 'river': ('河流', 'River'), '渡河点': ('渡河点', 'River crossing'), 'river crossing': ('渡河点', 'River crossing'), '河畔城镇': ('河畔城镇', 'River town'), 'river town': ('河畔城镇', 'River town'), '南侧桥梁': ('南侧桥梁', 'South bridge'), 'south bridge': ('南侧桥梁', 'South bridge'), '南侧海岸': ('南侧海岸', 'South coast'), 'south coast': ('南侧海岸', 'South coast'), '南侧岩石区': ('南侧岩石区', 'South rocks'), 'south rocks': ('南侧岩石区', 'South rocks'), '南侧城镇': ('南侧城镇', 'South town'), 'south town': ('南侧城镇', 'South town'), '南侧村镇群': ('南侧村镇群', 'South towns'), 'south towns': ('南侧村镇群', 'South towns'), '南侧山谷': ('南侧山谷', 'South valley'), 'south valley': ('南侧山谷', 'South valley'), '西南道路': ('西南道路', 'Southwest road'), 'southwest road': ('西南道路', 'Southwest road'), '广场': ('广场', 'Square'), 'square': ('广场', 'Square'), '寺庙': ('寺庙', 'Temple'), 'temple': ('寺庙', 'Temple'), '铁塔东侧': ('铁塔东侧', 'East of the tower'), 'east of the tower': ('铁塔东侧', 'East of the tower'), '铁塔西侧': ('铁塔西侧', 'West of the tower'), 'west of the tower': ('铁塔西侧', 'West of the tower'), '城镇': ('城镇', 'Town'), 'town': ('城镇', 'Town'), '山谷': ('山谷', 'Valley'), 'valley': ('山谷', 'Valley'), '村庄': ('村庄', 'Village'), 'village': ('村庄', 'Village'), '村庄道路': ('村庄道路', 'Village road'), 'village road': ('村庄道路', 'Village road'), '城墙隘口': ('城墙隘口', 'Wall pass'), 'wall pass': ('城墙隘口', 'Wall pass'), '瀑布': ('瀑布', 'Waterfall'), 'waterfall': ('瀑布', 'Waterfall'), '西侧城区': ('西侧城区', 'West city'), 'west city': ('西侧城区', 'West city'), '西侧海岸': ('西侧海岸', 'West coast'), 'west coast': ('西侧海岸', 'West coast'), '西侧旷野': ('西侧旷野', 'West field'), 'west field': ('西侧旷野', 'West field'), '西侧田野': ('西侧田野', 'West fields'), 'west fields': ('西侧田野', 'West fields'), '西侧丘陵': ('西侧丘陵', 'West hills'), 'west hills': ('西侧丘陵', 'West hills'), '西侧湖滨道路': ('西侧湖滨道路', 'West lake road'), 'west lake road': ('西侧湖滨道路', 'West lake road'), '西侧湖岸': ('西侧湖岸', 'West lakeside'), 'west lakeside': ('西侧湖岸', 'West lakeside'), '西侧山口': ('西侧山口', 'West pass'), 'west pass': ('西侧山口', 'West pass'), '西侧山脊': ('西侧山脊', 'West ridge'), 'west ridge': ('西侧山脊', 'West ridge'), '西侧岩石区': ('西侧岩石区', 'West rocks'), 'west rocks': ('西侧岩石区', 'West rocks'), '西侧街道': ('西侧街道', 'West streets'), 'west streets': ('西侧街道', 'West streets'), '西侧城镇': ('西侧城镇', 'West town'), 'west town': ('西侧城镇', 'West town'), '西侧山谷': ('西侧山谷', 'West valley'), 'west valley': ('西侧山谷', 'West valley'), '西侧树林': ('西侧树林', 'West woods'), 'west woods': ('西侧树林', 'West woods'), '丘陵地带': ('丘陵地带', 'Hilly terrain'), 'hilly terrain': ('丘陵地带', 'Hilly terrain'), '东侧支援': ('东侧支援', 'Eastern support'), 'eastern support': ('东侧支援', 'Eastern support'), '东侧林地': ('东侧林地', 'Eastern woods'), 'eastern woods': ('东侧林地', 'Eastern woods'), '东岛': ('东岛', 'Eastern island'), 'eastern island': ('东岛', 'Eastern island'), '中路后方': ('中路后方', 'Behind the central lane'), 'behind the central lane': ('中路后方', 'Behind the central lane'), '中部山脊': ('中部山脊', 'Central ridge'), 'central ridge': ('中部山脊', 'Central ridge'), '出生后方': ('出生后方', 'Behind the spawn'), 'behind the spawn': ('出生后方', 'Behind the spawn'), '北侧后方': ('北侧后方', 'Northern rear'), 'northern rear': ('北侧后方', 'Northern rear'), '北侧支援': ('北侧支援', 'Northern support'), 'northern support': ('北侧支援', 'Northern support'), '南侧半岛': ('南侧半岛', 'Southern peninsula'), 'southern peninsula': ('南侧半岛', 'Southern peninsula'), '后方支援': ('后方支援', 'Rear support'), 'rear support': ('后方支援', 'Rear support'), '坡道': ('坡道', 'Ramp'), 'ramp': ('坡道', 'Ramp'), '城区后方': ('城区后方', 'Behind the city'), 'behind the city': ('城区后方', 'Behind the city'), '城镇支援': ('城镇支援', 'Town support'), 'town support': ('城镇支援', 'Town support'), '基地后方': ('基地后方', 'Behind the base'), 'behind the base': ('基地后方', 'Behind the base'), '平原': ('平原', 'Plain'), 'plain': ('平原', 'Plain'), '新炮位': ('新炮位', 'Artillery position'), 'artillery position': ('新炮位', 'Artillery position'), '旷野后方': ('旷野后方', 'Behind the fields'), 'behind the fields': ('旷野后方', 'Behind the fields'), '林地': ('林地', 'Woods'), 'woods': ('林地', 'Woods'), '树林': ('树林', 'Forest'), 'forest': ('树林', 'Forest'), '桥梁': ('桥梁', 'Bridge'), 'bridge': ('桥梁', 'Bridge'), '沙滩': ('沙滩', 'Sandy beach'), 'sandy beach': ('沙滩', 'Sandy beach'), '海岸': ('海岸', 'Coast'), 'coast': ('海岸', 'Coast'), '西侧山丘': ('西侧山丘', 'Western hills'), 'western hills': ('西部山丘', 'Western hills'), '西侧山坡': ('西侧山坡', 'Western slope'), 'western slope': ('西侧山坡', 'Western slope'), '西侧支援': ('西侧支援', 'Western support'), 'western support': ('西侧支援', 'Western support'), '西侧桥梁': ('西侧桥梁', 'Western bridge'), 'western bridge': ('西侧桥梁', 'Western bridge'), '西島': ('西島', 'Western island'), 'western island': ('西岛', 'Western island'), '西岛': ('西岛', 'Western island'), '西部山丘': ('西部山丘', 'Western hills'), '铁路后方': ('铁路后方', 'Behind the railway'), 'behind the railway': ('铁路后方', 'Behind the railway')}

def tactic_name(value, language):
    pair = TACTIC_NAMES.get(value) or TACTIC_NAMES.get(value.lower())
    return pair[0 if language == "zh" else 1] if pair else value
