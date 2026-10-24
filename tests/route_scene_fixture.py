"""Keep physical traffic regression inputs independent of the lane lottery.

IDs were recorded from reviewed build 506 / commit 41d88897 with seed 0x0922.
New authoritative-allocation tests run without this replay input.
"""
import copy
import json
from pathlib import Path

SCENES=json.loads((Path(__file__).parent/'fixtures/traffic-scene-routes-506.json').read_text())


def allocate(profile,name,graph,states,catalog,seed):
    plans={};outcomes={};usage={}
    for state in states:
        identity=SCENES[name][str(state['id'])]
        route=next((r for r in catalog.get(state['team'],catalog.get(str(state['team']),())) if r['id']==identity),None)
        assert identity is None or route is not None,(name,identity)
        plans[state['id']]=copy.deepcopy(route);outcomes[state['id']]='fixed_traffic_scene'
        key=(state['team'],('spg:' if state['profile'].get('class_tag')=='SPG' else '')+str(identity),state['profile'].get('class_tag'))
        usage[key]=usage.get(key,0)+1
    return plans,outcomes,usage
