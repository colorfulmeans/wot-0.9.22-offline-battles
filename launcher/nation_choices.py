"""Shared launcher nation captions and native garage display order."""
ORDER = ('china','ussr','usa','germany','czech','france','uk','japan','poland','sweden')
EN_NAMES = dict(china='China',ussr='USSR',usa='USA',germany='Germany',czech='Czech',
                france='France',uk='UK',japan='Japan',poland='Poland',sweden='Sweden')

def ordered(nations):
    available=set(nations)
    return [nation for nation in ORDER if nation in available]

def caption(nation,translate):
    text=translate(nation)
    return EN_NAMES.get(nation,nation) if text==nation else text


def vehicle_key(row):
    """Native nation order, then tier and unambiguous vehicle name."""
    nation = row.get('nation', '')
    return (ORDER.index(nation) if nation in ORDER else len(ORDER),
            int(row.get('level') or 99), str(row.get('label', row.get('vehicle', ''))).casefold(),
            str(row.get('vehicle', row.get('name', ''))))
