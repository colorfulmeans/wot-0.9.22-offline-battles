"""Parking selection and ordinary defense-view navigation."""
import copy


class ArtilleryEditorMixin:
    def _parking_items(self):
        deleted=set(self.entry().get('deleted_positions',()))
        rows={p['id']:p for p in self.spg_defaults}
        rows.update((p['id'],p) for p in self.entry()['positions'])
        return [p for p in rows.values() if p['team']==self.team and p['id'] not in deleted]

    def _store_parking(self, item):
        rows=self._ensure_entry()['positions']
        current=next((p for p in rows if p['id']==item['id']),None)
        if current is None:rows.append(item)
        else:current.clear();current.update(item)

    def _sync_parking_endpoints(self, zone):
        zone.pop('travel',None);zone.pop('links',None)

    def _remove_parking_references(self, identity):
        return

    def _refresh_connection_tree(self):
        self.tree_connections={}

    def _connection_tree_key(self):
        return None

    def edit_defense(self):
        if not (self._selected_parent() or {}).get('defense'):return
        self.network_mode='' if self.network_mode=='defense' else 'defense'
        self.network_link='';self.wait_edit=False;self.selected_point=0;self.selected_wait=None
        self._refresh_properties();self.redraw()
