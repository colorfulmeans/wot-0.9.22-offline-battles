"""Opt-in packaged Tk verification using an isolated temporary save only."""
import json
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace


def run(destination, game_root, translate=lambda value: value):
    report = {'ok': False, 'native_gameplay_tested': False}
    root = None
    try:
        import tkinter as tk
        from tkinter import ttk
        import customizations_ui as ui
        store = ui.store
        original_read, original_write = store.read_inventory, store.write_inventory
        with tempfile.TemporaryDirectory(prefix='styles-smoke-') as temp:
            store.read_inventory = lambda *args: original_read(*args, root=temp)
            store.write_inventory = lambda *args: original_write(*args, root=temp, is_running=lambda: False)
            root = tk.Tk(); root.withdraw()
            parent = tk.Toplevel(root); parent.withdraw()
            owner = SimpleNamespace(_tk=tk, _ttk=ttk, _t=translate,
                save_dialog=parent, _save_slot_id='default',
                game_root=SimpleNamespace(get=lambda: game_root))
            dialog = ui.CustomizationsDialog(owner)
            def captions(widget):
                return ([str(widget.cget('text'))] if isinstance(widget,tk.Button) else []) + [
                    caption for child in widget.winfo_children() for caption in captions(child)]
            assert translate('Save changes') in captions(dialog.window)
            dialog.window.geometry('+10000+10000')
            root.update()
            assert len(dialog.table.get_children()) == 27
            hidden = [s for s in dialog.styles if s['hidden']]
            assert len(hidden) == 9
            chosen = next(s for s in hidden if s['id'] == 128)
            applicable = [v for v in dialog.vehicles if store.compatible(chosen, v)]
            before = sum(dialog.inventory['4']['128'].values())
            dialog.table.selection_set('128'); dialog.quantity.set('2'); dialog.add()
            assert sum(dialog.inventory['4']['128'].values()) == before + len(applicable)*2
            dialog.save()
            restored = original_read('default', game_root, dialog.styles, dialog.vehicles, root=temp)
            assert restored == dialog.inventory
            metadata=store.save_slots.metadata_path('default',game_root,root=temp)
            rows=store.save_ledger._read_state(metadata)['initial_account_notifications']
            assert any(reward['kind']=='style' for row in rows
                       for change in row['settlement']['account_changes'] for reward in change['rewards'])
            store.save_ledger.write_balances('default',dict(credits=123,gold=456,freeXP=789,crystal=42),
                game_root=game_root,root=temp,is_running=lambda:False)
            store.save_slots.set_earnings_percent('default',250,game_root=game_root,root=temp,is_running=lambda:False)
            rows=store.save_ledger._read_state(metadata)['initial_account_notifications']
            kinds={reward['kind'] for row in rows for change in row['settlement']['account_changes']
                   for reward in change['rewards']}
            assert {'style','credits','gold','freeXP','crystal','earnings_percent'} <= kinds
            label = next(k for k,v in dialog.vehicle_by_label.items() if v is not None and not store.compatible(chosen, v))
            dialog.vehicle.set(label); dialog.refresh()
            assert not dialog.table.exists('128')
            dialog.close()
            store.read_inventory, store.write_inventory = original_read, original_write
            report.update(ok=True, styles=27, hidden=9, compatible_add=True, atomic_save=True,
                          target_filter=True, temporary_save_only=True, save_caption=translate('Save changes'),
                          customization_wallet_earnings_receipts=True)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
    Path(destination).write_text(json.dumps(report, indent=2), encoding='utf8')
    return 0 if report['ok'] else 1
