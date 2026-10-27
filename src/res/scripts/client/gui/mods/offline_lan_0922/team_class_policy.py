"""Positive team class selection: fixed Bots, guaranteed classes, random fill."""
CLASSES=('lightTank','mediumTank','heavyTank','AT-SPG','SPG')


def canonical(value=None):
    if value is not None and (not isinstance(value,dict) or set(map(str,value))!=set(('1','2'))):
        raise ValueError('Invalid team class choices')
    result={}
    for side in (1,2):
        raw=value.get(str(side),value.get(side)) if value is not None else None
        if raw is None:raw=dict((tag,True) for tag in CLASSES);raw['random']=True
        if not isinstance(raw,dict) or set(raw)-set(CLASSES+('random','order')) or any(tag not in raw or type(raw[tag]) is not bool for tag in CLASSES):
            raise ValueError('Invalid team class choices')
        random_mode=raw.get('random',False)
        if type(random_mode) is not bool:raise ValueError('Invalid random class mode')
        order=raw.get('order',[tag for tag in CLASSES if raw[tag]])
        if not isinstance(order,(list,tuple)) or any(tag not in CLASSES for tag in order) or len(order)!=len(set(order)):
            raise ValueError('Invalid class selection order')
        order=[tag for tag in order if raw[tag]]+[tag for tag in CLASSES if raw[tag] and tag not in order]
        result[str(side)]=dict((tag,raw[tag]) for tag in CLASSES)
        result[str(side)].update(random=random_mode or not order,order=order)
    return result


def required(row,pinned=()):
    return [] if row['random'] else [tag for tag in row['order'] if row[tag] and tag not in pinned]


def trim(row,automatic,pinned=(),keep=None):
    """Preserve early choices, including remembered choices in random mode."""
    removed=[]
    newest=list(reversed(row['order']))
    if keep in newest:newest.remove(keep);newest.append(keep)
    for tag in newest:
        needed=[t for t in row['order'] if row[t] and t not in pinned]
        if len(needed)<=automatic:break
        if tag in pinned:continue
        row[tag]=False;row['order'].remove(tag);removed.append(tag)
    if not row['order']:row['random']=True
    return removed


def allows(row,tag):
    return row['random'] or row.get(tag,False)


def artillery_limit(size,human,pinned,row):
    nominal=0 if size<=6 else min(3,(size-4)//3)
    if not row['random'] and row['SPG']:nominal=max(1,nominal)
    remaining=max(0,nominal-human-pinned)
    # A human never satisfies the guaranteed BOT. Pinned Bots do.
    if not row['random'] and row['SPG'] and not pinned:remaining=max(1,remaining)
    return remaining


def validate(row,automatic,pinned,candidates,spg_limit):
    needed=required(row,pinned)
    if len(needed)>automatic:return 'slots'
    if any(tag not in candidates for tag in needed):return 'missing_class'
    allowed=[tag for tag in candidates if allows(row,tag)]
    if automatic and (not allowed or (allowed==['SPG'] and automatic>spg_limit)):
        return 'pool'
    return None

def matching_tiers(candidates,needed,humans,proposed,random_mode,groups=()):
    """Choose one legal random window that can supply every guaranteed class."""
    proposed=tuple(sorted(set(proposed)))
    needed=set(needed)
    if not needed and not groups:return proposed
    def covered(tiers):
        present=set(tag for level,tag in candidates if level in tiers)
        return needed.issubset(present) and all(set(group).intersection(present) for group in groups)
    if covered(proposed):return proposed
    if not random_mode:return None
    humans=set(humans)
    windows=[]
    for low in range(1,11):
        for width in (1,2,3):
            window=tuple(range(low,min(11,low+width)))
            if len(window)!=width or not humans.issubset(window):continue
            if covered(window):windows.append(window)
    if not windows:return None
    return min(windows,key=lambda w:(abs(len(w)-len(proposed)),len(set(w)^set(proposed)),w))
