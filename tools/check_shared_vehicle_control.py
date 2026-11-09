#!/usr/bin/env python3
"""Verify single shared control ownership and its actor-state integration."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Run source and integration contracts')
    parser.parse_args()
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name)
        for name in ('test_shared_vehicle_control', 'test_shared_mission_control',
                     'test_shared_order_planning'))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        print(captured.getvalue()[-12000:])
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    raise SystemExit(main())
