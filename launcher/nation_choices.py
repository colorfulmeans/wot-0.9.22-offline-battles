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
