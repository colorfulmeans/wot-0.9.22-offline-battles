"""Navigable three-category map checks; reports never mutate route data."""
import copy
import tkinter as tk
from tkinter import ttk
import bot_tactics_inventory as inventory
import bot_tactics_labels as labels
import bot_tactics_navigation as navigation
from bot_tactics_store import contract


def show(editor):
    e=editor
    rows=inventory.inspect(contract.canonical(e.document),e.map_name,e.graph_cache[e.map_name],
                           contract,receipt=navigation.persist_receipt)
    snapshot=copy.deepcopy(e.document['maps']);name=e.map_name;profile_name=e.document['name']
    window=tk.Toplevel(e.root);window.title(e.tr('本图检查清单','Map check inventory'))
    window.geometry('980x600');window.transient(e.root)
    status=ttk.Label(window,text=e.tr('导航数据检查；不保证实战畅通。双击条目定位。','Navigation-data checks, not a live physics guarantee. Double-click to locate.'))
    status.pack(anchor='w',padx=8,pady=8)
    tree=ttk.Treeview(window,columns=('team','scope','kind','result'),show='tree headings')
    for key,zh,en in (('#0','路线／炮位','Route / parking'),('team','队伍','Team'),('scope','车型','Class'),('kind','配置项目','Configuration'),('result','结果','Result')):
        tree.heading(key,text=e.tr(zh,en));tree.column(key,width=190 if key in ('#0','result') else 120)
    scroll=ttk.Scrollbar(window,command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');tree.pack(fill='both',expand=True,padx=8)
    kinds={'route':('路线（双向）','Route (both directions)'), 'sortie':('火炮残局出击','SPG sortie'),
        'parking':('炮位','Parking'),'deployment':('火炮部署','SPG deployment'),
        'relocation':('火炮换位','SPG relocation'),'defense':('回防线','Defense connection')}
    for key,zh,en in (('correct','配置且正确','Configured and correct'),('incorrect','配置但是错误','Configured but incorrect'),('unconfigured','未配置','Unconfigured')):
        group=[r for r in rows if r['category']==key and not r['disabled']]
        tree.insert('', 'end',iid=key,text=e.tr(zh,en)+' (%d)'%len(group),open=True)
    disabled=[r for r in rows if r['disabled']]
    if disabled:tree.insert('','end',iid='disabled',text=e.tr('禁用路线（不参与通行检查）','Disabled routes (excluded from travel checks)'),open=False)
    targets={}
    for i,row in enumerate(rows):
        key='row%d'%i;targets[key]=row
        result=e.tr('导航数据检查通过','Navigation-data checks passed')
        if row['category']=='unconfigured':result=e.tr('未配置，使用现有兜底','Unconfigured; existing fallback')
        if row['issues']:result=e.tr('发现 %d 个问题','%d issues')%len(row['issues'])
        caption=labels.tactic_name(row['label'],e.language)
        if row['selection'] and row['selection'][0]=='builtin' and row['label']==row['identity']:
            caption=labels.route_label(row['identity'],e.language)
        if row['link']:caption+=' → '+row['link']
        tree.insert('disabled' if row['disabled'] else row['category'],'end',iid=key,text=caption,
            values=(row['team'],labels.enum_label('class_tag',row['scope'],e.language),e.tr(*kinds[row['kind']]),result))
        for j,issue in enumerate(row['issues']):
            identity=key+'_%d'%j;targets[identity]=dict(row,issue=issue)
            text=labels.validation_label(issue['reason'],e.language)
            if issue.get('direction'):text+=' / '+e.tr('正向' if issue['direction']=='forward' else '反向' if issue['direction']=='reverse' else '等待位连接',issue['direction'])
            coords=' → '.join('X %.1f Z %.1f'%tuple(p[:2]) for p in issue['points'])
            nodes=e.tr('节点 ','Node ')+' → '.join(str(n) for n in issue['nodes'])
            if issue.get('wait_slot') is not None:nodes+=e.tr(' / 等待点 ',' / wait place ')+str(issue['wait_slot'])
            tree.insert(key,'end',iid=identity,text=text,values=('', '', nodes, coords))

    def current():return snapshot==e.document['maps'] and name==e.map_name and profile_name==e.document['name']
    timer=[None]
    def refresh():
        if not window.winfo_exists():return
        if not current():status.configure(text=e.tr('检查结果已过期，请重新检查；旧结果不再用于定位。','Results expired; run the check again. Old results cannot locate edited nodes.'))
        timer[0]=window.after(300,refresh)
    def locate(event=None):
        if not current():return
        selected=tree.selection()
        row=targets.get(selected[0]) if selected else None
        if not row or not row['selection'] or row['disabled']:return
        e.team_var.set(str(row['team']));e.team=row['team'];e._load_map()
        e.route_class_var.set('total' if row['scope']!='SPG' else 'SPG')
        e.network_mode='';e.network_link='';e.selection=tuple(row['selection'])
        if row['scope']=='SPG' and e.selection[0]=='routes':e.selection=('routes',row['identity'])
        e._refresh_items()
        if row['mode'] and row['points']:
            e.network_mode=row['mode'];e.network_link=row['link']
        e.wait_edit=False;e.selected_wait=None
        e.selected_point=(row.get('issue',{}).get('nodes') or [1])[0]-1
        if row.get('issue',{}).get('wait_slot') is not None:
            e.wait_edit=True;e.selected_wait=row['issue']['wait_slot']-1
        e._refresh_properties();e.redraw()
        item=e._selected()
        if item:
            point=(item.get('points') or [item.get('point')])[e.selected_point]
            x,y=e.view.screen(point)
            e.view.pan_x+=e.canvas.winfo_width()/2-x;e.view.pan_y+=e.canvas.winfo_height()/2-y;e.redraw()
        e.root.lift()
    tree.bind('<Double-1>',locate)
    ttk.Button(window,text=e.tr('定位选中项','Locate selection'),command=locate).pack(side='left',padx=8,pady=8)
    ttk.Button(window,text=e.tr('关闭','Close'),command=window.destroy).pack(side='right',padx=8,pady=8)
    def cancel(event):
        if event.widget is window and timer[0] is not None:
            window.after_cancel(timer[0]);timer[0]=None
    window.bind('<Destroy>',cancel,add='+')
    timer[0]=window.after(300,refresh)
    return window
