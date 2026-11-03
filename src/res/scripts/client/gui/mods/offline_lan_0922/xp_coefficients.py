"""Old Chinese PC special base XP, separate from premium settlement XP.

Gold Type 59: https://wotgame.cn/zh-cn/news/event/Sales-Gold-59/
Type 62: 2016 player account and the original author's historical review:
https://games.sina.cn/yxbk/wy/2016-05-18/detail-ifxsktkp8939460.d.html
https://www.bilibili.com/read/cv16374084/
WZ111T: 2016-12-20 original version FAQ republished by Sina:
https://games.sina.com.cn/o/z/wot/2016-12-20/fxytqaw0011401.shtml
The historical review identifies its bonus as base XP. This is explicitly
the old Chinese rule; modern global vehicles are not evidence for removing it.
Churchill III and ordinary WZ111 special base bonuses are not implemented here;
the current fallback is 1.0, not a verified original coefficient. Their unresolved
status must not block evaluation of PC community evidence or reasonable labelled
reconstruction compatible with the selected base under CLAUDE.md. Missing official
confirmation is not a requirement to retain this fallback. This comment changes
policy documentation only; the values below have not been changed or validated.
"""

SPECIAL_BASE_XP_100 = {
    'china:Ch01_Type59_Gold': 200,
    'china:Ch02_Type62': 200,
    'china:Ch03_WZ_111_A': 200,
}
UNRESOLVED_BASE_XP = ('ussr:R33_Churchill_LL', 'china:Ch03_WZ-111')


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
