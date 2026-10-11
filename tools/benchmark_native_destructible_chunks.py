"""Complete adapter/query medians; these fixtures are not game frame timings."""
from __future__ import print_function
import json
import math
import os
import sys
import time
from check_native_destructible_chunks import box, fixture, load_extension


def main():
    from gui.mods.offline_lan_0922 import native_math
    from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
    native_math._backend = load_extension('offline_math_batch_native', sys.argv[1])
    native_math._attempted = True
    for name, module in zip(('DestructiblesCache', 'AreaDestructibles', 'Math'), fixture()):
        sys.modules[name] = module
    clock = getattr(time, 'perf_counter', getattr(time, 'clock', time.time))
    cases = [
        ('single-hull', [box(10., 20., 3.5, 1.7, .5)], 2500),
        ('boundary-eight-slices', [box(97. + i*.8, -100. + i*.4,
            3.5, 1.7, .2 + i*.03, fourth=(1., .1, 1.5)) for i in range(8)], 1200),
        ('maximum-128-slices', [box(80. + i*.7, 90. - i*.3,
            4., 2., .1 + i*.008, fourth=(1., .2, .5)) for i in range(128)], 120),
        ('empty-sweep', [], 2500),
        ('oversized-hard', [box(0., 0., 1700., 3.)], 2500),
    ]
    results = []
    for name, values, loops in cases:
        reference = sensor._reference_tree_motion_required_chunks_1513
        current = sensor._tree_motion_required_chunks_1513
        expected = reference(values)
        assert current(values) == expected
        measurements = [[], []]
        for sample in range(7):
            # Alternate measurement order rather than always warming native last.
            for index in ((0, 1) if sample % 2 == 0 else (1, 0)):
                function = (reference, current)[index]
                start = clock()
                for unused in range(loops):
                    function(values)
                measurements[index].append((clock() - start) * 1.e6 / loops)
        previous, current = [sorted(samples)[3] for samples in measurements]
        results.append(dict(fixture=name, previous_us=previous, current_us=current,
            ratio=previous/current, samples_us=measurements, expected=expected))
    print('Complete chunk-query incremental medians:', json.dumps(results, sort_keys=True))
    with open(sys.argv[2], 'w') as out:
        json.dump(results, out, indent=2, sort_keys=True)
        out.write('\n')


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [os.path.join(root, 'tools'), os.path.join(root, 'src/res/scripts/client')]
    main()
