"""Check the persistent C++ candidate grader, independently of route strategy.

The retained full navigation harness has an older route-submission fixture.
This gate directly exercises the changed grid API with the current source
and native extension; async A* is separately covered by check_native_workers.
"""
from __future__ import print_function
import imp
import json
import os
import sys
import types
from check_native_simulation_navigation import load_sources, graph, ReceiptPlanner, equal


def main():
    scripts=sys.argv[2] if len(sys.argv)>2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'src','res','scripts','client')
    source,facade=load_sources(scripts)
    backend=imp.load_dynamic('offline_math_batch_native',os.path.abspath(sys.argv[1]))
    from gui.mods.offline_lan_0922 import native_navigation
    source.NativeNavigation.create=classmethod(
        lambda cls,grid:ReceiptPlanner(grid,native_navigation))
    checks=0
    for gx,gz in ((0.,0.),(.05,0.),(0.,.05),(.03,.04),(.0,.10)):
        baked=graph()
        baked['hazards']=[0]*len(baked['hazards'])
        baked['heights_mm']=[int(1000.*(gx*(-60.+4*x)+gz*(-60.+4*z)))
            for z in range(31) for x in range(31)]
        reference=source.TerrainNavigator(lambda x,z,h:gx*x+gz*z,
            lambda *args:False,baked_graph=baked)
        original=source.TerrainNavigator(lambda x,z,h:gx*x+gz*z,
            lambda *args:False,baked_graph=baked)
        runtime=types.ModuleType('nested_grade_fixture')
        runtime.navigator=original
        handle=backend.sim_open(82,1)
        native=facade.NativeNavigationCore.install(runtime,backend,handle)
        try:
            for x,z in ((40.,0.),(0.,40.),(40.,40.),(-40.,40.),(-40.,0.)):
                goal=(x,gx*x+gz*z,z)
                for side in (-1.,1.):
                    expected=reference.grid.safe_local_target((0.,0.,0.),goal,.1,side_preference=side)
                    actual=native.grid.safe_local_target((0.,0.,0.),goal,.1,side_preference=side)
                    equal(expected,actual,'nested persistent local grading')
                    assert actual is not None, 'A legal slope became unroutable'
                    checks+=1
            if gx == 0. and gz == .10:
                # Equal-distance side candidates straddle the boundary
                # between a flat side and a legal rising side. Excluding
                # the straight candidate makes the second key observable.
                native.detach()
                reference.close()
                original.close()
                backend.sim_close(handle)
                baked['heights_mm']=[int(100.*max(-60.+4*z,0.))
                    for z in range(31) for x in range(31)]
                reference=source.TerrainNavigator(lambda x,z,h:.1*max(z,0.),
                    lambda *args:False,baked_graph=baked)
                original=source.TerrainNavigator(lambda x,z,h:.1*max(z,0.),
                    lambda *args:False,baked_graph=baked)
                runtime.navigator=original
                handle=backend.sim_open(82,2)
                native=facade.NativeNavigationCore.install(runtime,backend,handle)
                for side in (-1.,1.):
                    expected=reference.grid.safe_local_target((0.,0.,0.),(40.,0.,0.),.1,
                        side_preference=side,minimum_offset=1.)
                    actual=native.grid.safe_local_target((0.,0.,0.),(40.,0.,0.),.1,
                        side_preference=side,minimum_offset=1.)
                    equal(expected,actual,'equal-progress flatter-side selection')
                    assert actual[2]<0., 'A rising side won equal progress against flat ground'
                    checks+=1
        finally:
            native.detach()
            reference.close()
            original.close()
            backend.sim_close(handle)
    print(json.dumps(dict(checks=checks,status='native distance/grade strict parity passed')))


if __name__=='__main__':main()
