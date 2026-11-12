#!/usr/bin/env python3
"""Verify single shared control ownership and its actor-state integration."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_MODULES = (
    'test_shared_vehicle_control',
    'test_shared_mission_control',
    'test_shared_order_planning',
    'test_shared_route_combat_ownership',
    'test_shared_combat_movement_receipts',
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Run source and integration contracts')
    parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name)
        for name in CONTRACT_MODULES)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        print(captured.getvalue()[-12000:])
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    raise SystemExit(main())
