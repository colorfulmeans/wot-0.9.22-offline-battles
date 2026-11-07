"""Old Chinese PC special base XP, separate from premium settlement XP.

Gold Type 59: https://wotgame.cn/zh-cn/news/event/Sales-Gold-59/
Type 62: 2016 player account and the original author's historical review:
https://games.sina.cn/yxbk/wy/2016-05-18/detail-ifxsktkp8939460.d.html
https://www.bilibili.com/read/cv16374084/
WZ111T: 2016-12-20 original version FAQ republished by Sina:
https://games.sina.com.cn/o/z/wot/2016-12-20/fxytqaw0011401.shtml
The historical review identifies its bonus as base XP. This is explicitly
the old Chinese rule; modern global vehicles are not evidence for removing it.
Churchill III: PC community base-XP reports support a special bonus. Adopt 1.5
as an explicit reconstruction, not an extracted #1513 server constant:
https://steamcommunity.com/app/1407200/discussions/0/4130430927307016968/
Ordinary WZ111: historical Chinese PC accounts identify an extra base-XP bonus:
https://xvm.garphy.com/?page_id=4552
https://games.sina.cn/yxbk/wy/2016-05-18/detail-ifxsktkp8939460.d.html
Adopt 1.5 for that historical regional vehicle (community reconstruction).
Neither factor is the native 1.5 CREW factor shared by premium vehicles.
"""

SPECIAL_BASE_XP_100 = {
    'china:Ch01_Type59_Gold': 200,
    'china:Ch02_Type62': 200,
    'china:Ch03_WZ_111_A': 200,
    'ussr:R33_Churchill_LL': 150,
    'china:Ch03_WZ-111': 150,
}
UNRESOLVED_BASE_XP = ()

# Exact #1513 type compact descriptors; only these base-XP exceptions differ
# from the captured EU award population. Churchill's own EU row already
# incorporates its special bonus; Chinese regional bonuses do not.
SPECIAL_VEHICLES_BY_CD = {
    561: 'china:Ch01_Type59_Gold', 305: 'china:Ch02_Type62',
    65073: 'china:Ch03_WZ_111_A', 51713: 'ussr:R33_Churchill_LL',
    817: 'china:Ch03_WZ-111',
}


def mastery_scale(vehicle_cd, has_reference_row=True):
    vehicle = SPECIAL_VEHICLES_BY_CD.get(int(vehicle_cd), '')
    reference = 150 if has_reference_row and vehicle == 'ussr:R33_Churchill_LL' else 100
    return base_factor(vehicle), reference


def base_factor(vehicle):
    return SPECIAL_BASE_XP_100.get(vehicle, 100)


def settlement_factor(vehicle_type):
    """Native premium eligibility; owner's IX/X common +5% policy."""
    if 'premium' not in (getattr(vehicle_type, 'tags', ()) or ()):
        return 0
    level = int(getattr(vehicle_type, 'level', 0))
    if level in (9, 10):
        return 5
    return max(0, int(round(float(getattr(vehicle_type, 'premiumVehicleXPFactor', 0.0)) * 100)))
