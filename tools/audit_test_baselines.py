#!/usr/bin/env python3
"""Inventory test inputs without mistaking old fixtures for product defaults.

This is static discovery, not a passing test gate. Calls through helpers or
nonliteral dictionaries require review; a missing keyword here is not proof
that the helper failed to supply it. Fixed historical regression inputs remain
useful for their isolated law, but do not certify shipping route selection.
"""
import argparse
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class Calls(ast.NodeVisitor):
    def __init__(self):
        self.stack, self.starts = [], []

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'battle_start':
            data = node.args[0] if node.args else None
            keys = [key.value for key in data.keys if isinstance(key, ast.Constant)] \
                if isinstance(data, ast.Dict) else None
            self.starts.append(dict(owner='.'.join(self.stack), line=node.lineno,
                                    literal_keys=keys,
                                    tactics_explicit=bool(keys and 'bot_tactics' in keys)))
        self.generic_visit(node)


def inventory(root=ROOT):
    records = []
    for directory in ('tests', 'launcher/tests'):
        for path in sorted((root / directory).glob('test_*.py')):
            source = path.read_text(encoding='utf-8-sig')
            tree = ast.parse(source)
            calls = Calls()
            calls.visit(tree)
            records.append(dict(file=path.relative_to(root).as_posix(),
                declared_test_methods=sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith('test_') for node in ast.walk(tree)),
                battle_starts=calls.starts,
                references_current_profile='default_profile(' in source,
                historical_lane_replay='route_scene_fixture' in source,
                json_references=sorted(set(re.findall(r'''['"]([^'"\n]+\.json)['"]''', source))),
                map_literals=sorted(set(re.findall(r'''['"](\d\d_[a-z0-9_]+)['"]''', source)))))
    return dict(evidence='AST inventory only; no tests executed', files=records,
        review_required=[row['file'] for row in records if row['historical_lane_replay'] or
                         any(not call['tactics_explicit'] for call in row['battle_starts'])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('%d files inventoried; %d require input-boundary review' %
          (len(result['files']), len(result['review_required'])))


if __name__ == '__main__':
    main()
