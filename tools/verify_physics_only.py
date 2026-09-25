"""Keep Bot decisions frozen while reviewing the 107084fa physics fixes.

Run from any directory: python3 tools/verify_physics_only.py [--target REV].
The allowlist is a review boundary, not proof that an allowed change is sound.
"""
import argparse
import ast
import copy
import pathlib
import subprocess
import sys

BASELINE = '107084faa92cfec7df9d6a3986103b5ff5d4511a'
PREFIX = 'src/res/scripts/client/gui/mods/offline_lan_0922/'
BOT = PREFIX + 'bot_runtime.py'
BATTLE = PREFIX + 'battle_runtime.py'
# This list permits physical implementation changes for independent review.
# It never permits the mixed decision/integration loop or hard-contact steering.
PHYSICAL = set('''
BotRuntime._passive_motion_status
BotRuntime._apply_bot_fall_damage
BotRuntime._apply_bot_landing_impact
BotRuntime._apply_world_contact_impact
BotRuntime._apply_tank_contact_response
BotRuntime._bleed_contact_push
BotRuntime._wreck_tracks_absorb
BotRuntime._apply_wreck_contact_response
BotRuntime._update_wreck_vertical_motion
BotRuntime._resolve_tank_contacts
BotRuntime._player_collision_profile
BotRuntime._resolve_human_ram_receipts
BotRuntime._integrate_vertical_motion
BotRuntime._update_vertical_motion
BotRuntime._update_suspension_vertical_motion
BotRuntime._suspension_ground_samples
BotRuntime._suspension_pseudo_ground_samples
BotRuntime._suspension_probe_height_for_motion
BotRuntime._straddled_terrain_support
BotRuntime._terrain_support
BotRuntime._update_slope_pose
'''.split())

FROZEN_ADAPTERS = set('''
BattleRuntime._direction_probe
BattleRuntime._direction_world_receipt
BattleRuntime._navigation_ground
BattleRuntime._navigation_obstacle
BattleRuntime._prepare_bot_vehicle_assignments
BattleRuntime._select_bot_vehicle
BattleRuntime._formation_pose
'''.split())


def same_tree(first, second):
    return ast.dump(first, include_attributes=False) == ast.dump(
        second, include_attributes=False)


def physical_callback_init(old, new):
    """Permit exactly the trailing callback argument and direct assignment."""
    if same_tree(old, new):
        return True
    new = copy.deepcopy(new)
    if (len(new.args.args) != len(old.args.args) + 1 or
            new.args.args[-1].arg != 'contact_motion_probe' or
            not new.args.defaults or
            not same_tree(new.args.defaults[-1], ast.parse('None').body[0].value)):
        return False
    new.args.args.pop()
    new.args.defaults.pop()
    assignment = ast.parse(
        'self.contact_motion_probe = contact_motion_probe').body[0]
    matches = [index for index, node in enumerate(new.body)
               if same_tree(node, assignment)]
    if len(matches) != 1:
        return False
    del new.body[matches[0]]
    return same_tree(old, new)


def physical_callback_injection(old, new):
    """Permit only the reviewed keyword in the existing BotRuntime call."""
    if same_tree(old, new):
        return True
    new = copy.deepcopy(new)
    expected = ast.parse('self._bot_contact_motion_is_clear').body[0].value
    removed = 0
    for node in ast.walk(new):
        if not (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name) and node.func.id == 'BotRuntime'):
            continue
        for keyword in list(node.keywords):
            if keyword.arg == 'contact_motion_probe' and same_tree(keyword.value, expected):
                node.keywords.remove(keyword)
                removed += 1
    return removed == 1 and same_tree(old, new)


def audit(repo, target=None):
    repo = pathlib.Path(repo).resolve()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo)] + list(args))

    def read(path, ref=None):
        return git('show', ref + ':' + path) if ref else (repo / path).read_bytes()

    paths = git('ls-tree', '-r', '--name-only', BASELINE, PREFIX + 'ai',
                'server/server_bot_ai.py').decode().splitlines()
    if target:
        current_paths = set(git('ls-tree', '-r', '--name-only', target,
                               PREFIX + 'ai', 'server/server_bot_ai.py').decode().splitlines())
    else:
        current_paths = set(str(path.relative_to(repo))
                            for path in (repo / PREFIX / 'ai').rglob('*.py'))
        if (repo / 'server/server_bot_ai.py').is_file():
            current_paths.add('server/server_bot_ai.py')
    violations = []
    if set(paths) != current_paths:
        violations.append('FROZEN FILE SET: ' + ', '.join(sorted(set(paths) ^ current_paths)))
    for path in sorted(set(paths) & current_paths):
        if read(path, BASELINE) != read(path, target):
            violations.append('FROZEN FILE: ' + path)
    old_tree, old, old_nodes = functions(read(BOT, BASELINE))
    new_tree, new, new_nodes = functions(read(BOT, target))
    changed = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) == new.get(name):
            continue
        changed.append(name)
        if name not in new:
            violations.append('REMOVED FUNCTION: ' + name)
            continue
        if (name == 'BotRuntime.__init__' and name in new_nodes and
                physical_callback_init(old_nodes[name], new_nodes[name])):
            continue
        if name not in PHYSICAL:
            violations.append('FROZEN FUNCTION: ' + name)
    if global_structure(old_tree) != global_structure(new_tree):
        violations.append('MODULE/CLASS GLOBALS: bot_runtime.py')
    unused, adapters_old, nodes_old = functions(read(BATTLE, BASELINE))
    unused, adapters_new, nodes_new = functions(read(BATTLE, target))
    for name in sorted(FROZEN_ADAPTERS):
        if name not in adapters_old:
            raise RuntimeError('Invalid frozen baseline adapter: ' + name)
        if adapters_old[name] != adapters_new.get(name):
            violations.append('FROZEN ADAPTER: ' + name)
    startup = 'BattleRuntime._finish_entity_startup'
    if (startup not in nodes_new or not physical_callback_injection(
            nodes_old[startup], nodes_new[startup])):
        violations.append('FROZEN STARTUP: ' + startup)
    print('baseline:', BASELINE)
    print('target:', target or str(repo))
    print('frozen files checked:', len(paths))
    print('Bot function definitions checked:', len(set(old) | set(new)))
    print('changed Bot functions requiring physical review:', ', '.join(changed) or '(none)')
    for problem in violations:
        print(problem)
    print('DECISION FREEZE:', 'FAIL' if violations else 'PASS')
    return not violations

def functions(source):
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    found = {}
    nodes = {}
    def walk(node, prefix=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + '.')
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                begin = min([child.lineno] + [n.lineno for n in child.decorator_list])
                found[prefix + child.name] = b''.join(lines[begin-1:child.end_lineno])
                nodes[prefix + child.name] = child
    walk(tree)
    return tree, found, nodes

def global_structure(tree):
    tree = copy.deepcopy(tree)
    def strip(node):
        body = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(child, ast.ClassDef):
                strip(child)
            body.append(child)
        node.body = body
    strip(tree)
    return ast.dump(tree, include_attributes=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument('--target', help='Git revision; default checks working files')
    args = parser.parse_args()
    return 0 if audit(args.repo, args.target) else 1


if __name__ == '__main__':
    sys.exit(main())
