"""Opt-in verification of the actual packaged editor; writes only a temp store."""
import json
import tempfile
from pathlib import Path
import traceback


def run(destination):
    report = {'ok': False, 'native_gameplay_tested': False}
    root = None
    try:
        import tkinter as tk
        import PIL
        import bot_tactics_ui
        import bot_tactics_store as storage
        with tempfile.TemporaryDirectory(prefix='bot-editor-smoke-') as temp:
            root = tk.Tk(); root.withdraw()
            ui = bot_tactics_ui.BotTacticsEditor(root, store=storage.Store(temp), language='en')
            def fail(error):
                raise AssertionError(str(error))
            ui.error = fail
            root.update(); ui.book.select(1); root.update()
            graph = storage.graph_data('08_ruinberg')
            # Actual canvas callbacks, not directly constructing the profile.
            ui.new_route(); root.update()
            for point in graph['routes']['1'][0]['waypoints'][:4]:
                x, y = ui.view.screen(point)
                ui.canvas.event_generate('<ButtonPress-1>', x=int(x), y=int(y))
                ui.canvas.event_generate('<ButtonRelease-1>', x=int(x), y=int(y))
                root.update()
            ui.item_vars['label'].set('Smoke route')
            ui.item_vars['policy'].set('fixed')
            assert ui.update_properties()
            ui.new_position(); root.update()
            x, y = ui.view.screen((-106., 346.))
            ui.canvas.event_generate('<ButtonPress-1>', x=int(x), y=int(y))
            ui.canvas.event_generate('<ButtonRelease-1>', x=int(x), y=int(y)); root.update()
            ui.item_vars['radius'].set('34')
            ui.profile_name.set('Packaged editor smoke')
            ui.save(True); root.update()
            active = ui.store.active()
            assert active['maps']['08_ruinberg']['routes'][0]['policy'] == 'fixed'
            assert active['maps']['08_ruinberg']['positions'][0]['radius'] == 34.
            assert not ui.dirty()
            # Test localized presentation in the actual frozen executable.
            # Switching must not alter the applied document or its canonical IDs.
            before_locale = ui.store.active_path.read_bytes()
            ui.set_language('zh'); root.update()
            assert ui.map_var.get() == '\u9c81\u522b\u514b'
            assert tuple(ui.rule_boxes['skill']['values']) == (
                '\u7ee7\u627f', '\u65b0\u624b', '\u666e\u901a', '\u8001\u5175', '\u7cbe\u82f1')
            assert not ui.dirty()
            ui.set_language('en'); root.update()
            assert ui.map_var.get() == 'Ruinberg'
            assert 'All vehicle classes' in ui.rule_boxes['class_tag']['values']
            assert before_locale == ui.store.active_path.read_bytes()
            assert not ui.dirty()
            report['locale_roundtrip'] = ['en', 'zh', 'en']
            report['locale_preserved_active_bytes'] = True
            report['localized_maps'] = len(ui.map_labels)
            # Prove that the runtime plan reader, not just the form, sees it.
            spawn = graph['spawn_formations']['1'][0]
            state = dict(id=11, team=1, slot=0, vehicle='smoke:SPG', profile={'class_tag':'SPG'},
                         collision_shape=(1.8,4.,-.8,2.), x=spawn[0],y=spawn[1],z=spawn[2])
            plans, statuses = storage.runtime.assign_manual_positions(active, '08_ruinberg', graph, [state])
            assert statuses[11] == 'manual_selected' and plans[11]['source'] == 'launcher_manual_v1'
            assert len(storage.contract.MAPS) == 41
            report.update(ok=True, pillow=PIL.__version__, tk=tk.TkVersion,
                          map_count=41, canvas_route_points=len(active['maps']['08_ruinberg']['routes'][0]['points']),
                          manual_plan=plans[11], profile_sha256=storage.contract.digest(active),
                          isolated_profile=True)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
    return 0 if report['ok'] else 1
