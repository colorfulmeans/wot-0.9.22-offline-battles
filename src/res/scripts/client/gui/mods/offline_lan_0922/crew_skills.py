"""Exact-seat skill bounds and durable full-skill grants for #1513 recruits."""
from gui.mods.offline_lan_0922 import crew_seat_data as data

CREDITS = 'launcherCrewSkillCredits'


def skills_for(roles):
    result=set(data.COMMON)
    for role in roles:result.update(data.ROLE_SKILLS.get(role,()))
    return tuple(sorted(result.intersection(data.ACTIVE)))


def seats(vehicle):
    return data.SEATS.get(vehicle,())


def bounds(vehicle,seat,female,training):
    rows=seats(vehicle)
    if isinstance(seat,bool) or not isinstance(seat,int) or not 0<=seat<len(rows):
        raise ValueError('Select an actual crew seat for this vehicle.')
    if type(training) is not int or training not in (50,75,100):
        raise ValueError('Invalid crew training level.')
    minimum=1 if female else 0
    return minimum,len(skills_for(rows[seat])) if training==100 else minimum


def saved_credits(value):
    result={}
    if not isinstance(value,dict):return result
    for key,row in value.items():
        try:
            identity=int(key)
            remaining=row['remaining'];learned=row.get('learned',[])
            if identity<=0 or type(remaining) is not int or not 0<=remaining<=25:continue
            if not isinstance(learned,list) or len(learned)!=len(set(learned)) or any(s not in data.ACTIVE for s in learned):continue
            if remaining+len(learned)>25:continue
            result[str(identity)]=dict(remaining=remaining,learned=list(learned))
        except (ValueError,TypeError,KeyError):continue
    return result


def grant_skill(descriptor,skill,tankmen):
    """Spend native XP in a detached descriptor, never serialize huge free XP."""
    if skill in descriptor.skills or descriptor.roleLevel!=100:
        raise ValueError('The crew member cannot learn this skill.')
    before=descriptor.freeXP
    sequence=len(descriptor.skills)-descriptor.freeSkillsNumber+1
    cost=sum(tankmen.TankmanDescr.levelUpXpCost(level,sequence) for level in range(100))
    # addSkill (unlike addXP) consumes this Python integer without capping it.
    # Its native level-up/rank loop leaves exactly the original bounded XP.
    descriptor.freeXP=before+cost
    descriptor.addSkill(skill)
    if descriptor.skillLevel(skill)!=100 or descriptor.freeXP!=before:
        raise ValueError('Native full-skill grant did not round trip.')
    return descriptor.makeCompactDescr()


def reset_grants(descriptor,credit,fraction,tankmen):
    """Return granted choices as credits; only earned XP follows reset losses."""
    learned=set(credit['learned'])
    ordinary=descriptor.skills[descriptor.freeSkillsNumber:]
    earned=descriptor.freeXP
    for index,skill in enumerate(ordinary,1):
        if skill not in learned:
            earned+=sum(tankmen.TankmanDescr.levelUpXpCost(level,index)
                        for level in range(descriptor.skillLevel(skill)))
    descriptor.dropSkills(0.0,False)
    if earned:descriptor.addXP(int(earned*fraction))
    restored=len(set(ordinary).intersection(learned))
    return dict(remaining=credit['remaining']+restored,learned=[])
