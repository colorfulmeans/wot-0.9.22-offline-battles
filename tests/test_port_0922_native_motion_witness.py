"""Run the captured collision-ownership corpus through reusable witnesses."""
from unittest import mock
import test_port_0922_compiled_collision as reference
from gui.mods.offline_lan_0922 import native_destructibles as native

sensor = reference.sensor


class _NativeWitnessMixin:
    def setUp(self):
        super().setUp()
        def witnesses(unused_sensor, boxes, point, start, end, normal):
            # Actual C++ rows are separately compared with these laws under
            # CPython 2.7. Here exercise their consumers and authority order.
            return tuple((sensor._point_in_world_box(point, box),
                sensor._segment_world_box_interval(start, end, box),
                sensor._projected_box_interval_1513(start, end, box),
                sensor._projected_box_interval_1513(point, point, box) is not None,
                sensor._original_side_face_1513(normal, box)) for box in boxes)
        patch = mock.patch.object(native, 'motion_witnesses', side_effect=witnesses)
        self.witnesses = patch.start()
        self.addCleanup(patch.stop)



class NativeWitnessCollisionTests(_NativeWitnessMixin, reference.CompiledCollisionTests):
    def test_report_corpus_enters_the_reusable_numeric_path(self):
        start, end, hit, candidate, alias = self.evidence(self.contacts[0])
        self.assertIsNone(self.query(start, end, [(hit, alias)]))
        self.assertGreater(self.witnesses.call_count, 0)


class NativeWitnessCrossMapTests(_NativeWitnessMixin, reference.CrossMapRailingCollisionTests):
    pass


class NativeWitnessFenceFollowupTests(_NativeWitnessMixin, reference.NativeFenceFollowupTests):
    pass
