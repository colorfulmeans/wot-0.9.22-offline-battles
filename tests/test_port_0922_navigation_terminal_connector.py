"""The captured near-goal graph endpoint is not the actual macro goal."""
import unittest
from unittest import mock
import test_port_0922_navigation_reached_corner as corner_fixture


class TerminalConnectorTests(unittest.TestCase):
    def test_captured_short_terminal_connector_enters_existing_safe_fallback(self):
        fixture=corner_fixture.ReachedCornerTests()
        corner=(-10.,-14.681,18.)
        nav,state,unused,path_key,unused_key,unused_path=fixture.scene(corner)
        goal=(0.,0.,18.)
        key=nav._cache_key(path_key,goal)
        path=[corner]
        state.update(request_key=key,planned_goal=goal,path_key=key)
        nav.paths[key]=path
        current=(-10.26,-14.714,17.735)
        next_safe=(-6.54,-13.65,19.15)
        with fixture.seams(nav,key,path),mock.patch.object(nav,'_fallback_target',return_value=next_safe) as fallback:
            self.assertEqual(next_safe,nav.next_target(3,current,goal,path_key,1.))
            fallback.assert_called_once()

    def test_actual_goal_keeps_normal_arrival_without_escape(self):
        fixture=corner_fixture.ReachedCornerTests()
        corner=(-10.,-14.681,18.)
        nav,state,goal,path_key,key,path=fixture.scene(corner)
        goal=corner;path=[corner];key=nav._cache_key(path_key,goal)
        state.update(request_key=key,planned_goal=goal,path_key=key)
        nav.paths[key]=path
        with fixture.seams(nav,key,path),mock.patch.object(nav,'_fallback_target') as fallback:
            self.assertEqual(corner,nav.next_target(3,corner,goal,path_key,1.))
            fallback.assert_not_called()


if __name__=='__main__':unittest.main()
