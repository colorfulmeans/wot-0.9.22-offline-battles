"""Artillery-only editor topology and one-shot connection transactions."""
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
        point=list(zone['point'])+[0]
        if zone.get('travel'):zone['travel'][-1]=point[:]
        for path in zone.get('links',{}).values():path[0]=point[:]
        for peer in self._parking_items():
            if peer['id']==zone['id'] or zone['id'] not in peer.get('links',{}):continue
            updated=copy.deepcopy(peer);updated['links'][zone['id']][-1]=point[:]
            self._store_parking(updated)

    def _remove_parking_references(self, identity):
        for peer in self._parking_items():
            if identity in peer.get('links',{}):
                updated=copy.deepcopy(peer);updated['links'].pop(identity)
                self._store_parking(updated)

    def connect_all_positions(self):
        # A check-shaped action, never a persisted switch or automatic policy.
        self.connect_all_var.set(False)
        if self.builtin:return
        peers=self._parking_items()
        if len(peers)<2:return
        updated={p['id']:copy.deepcopy(p) for p in peers}
        changed=set()
        try:
            for index,first in enumerate(peers):
                for last in peers[index+1:]:
                    if (last['id'] in first.get('links',{}) or
                            first['id'] in last.get('links',{})):continue
                    for owner,target in ((first,last),(last,first)):
                        updated[owner['id']].setdefault('links',{})[target['id']]=[
                            list(owner['point'])+[0],list(target['point'])+[0]]
                        changed.add(owner['id'])
            if not changed:return
            before=copy.deepcopy(self.document);history=copy.deepcopy(self.histories)
            self.checkpoint()
            try:
                for identity in sorted(changed):self._store_parking(updated[identity])
                self._refresh_items();self.mark()
            except Exception:
                self.document=before;self.histories=history;self._refresh_items()
                raise
        except Exception as error:self.error(error)
        finally:self.connect_all_var.set(False)

    def _refresh_connection_tree(self):
        self.tree_connections={}
        for zone in self._parking_items():
            parent=next((key for key in ('builtin_positions:'+zone['id'],'positions:'+zone['id']) if self.items.exists(key)),None)
            if parent is None:continue
            selection=tuple(parent.split(':',1));self.items.item(parent,open=True)
            paths=[]
            if zone.get('travel'):paths.append(('travel',''))
            paths.extend(('link',identity) for identity in sorted(zone.get('links',{})))
            for index,(mode,link) in enumerate(paths):
                key='connection:'+zone['id']+':'+str(index)
                self.tree_connections[key]=(selection,mode,link)
                self.items.insert(parent,'end',iid=key,text=self._connection_caption(mode,link),tags=('artillery',))

    def _connection_caption(self, mode, link):
        if mode=='travel':return self.tr('部署：基地 → 本炮位','Deploy: base → this parking')
        peer=next((p for p in self._parking_items() if p['id']==link),None)
        from bot_tactics_labels import tactic_name
        return self.tr('换位 → ','Relocate → ')+tactic_name(peer['label'] if peer else link,self.language)

    def _connection_tree_key(self):
        return next((key for key,value in getattr(self,'tree_connections',{}).items()
            if value==(self.selection,self.network_mode,self.network_link)),None)

    def edit_defense(self):
        if not (self._selected_parent() or {}).get('defense'):return
        self.network_mode='' if self.network_mode=='defense' else 'defense'
        self.network_link='';self.wait_edit=False;self.selected_point=0;self.selected_wait=None
        self._refresh_properties();self.redraw()

    def delete_deployment(self):
        if self.builtin or self.network_mode!='travel':return
        self.checkpoint();self._editable_parent().pop('travel',None)
        self.network_mode='';self.network_link='';self._refresh_items();self.mark()
