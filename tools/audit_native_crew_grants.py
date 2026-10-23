"""Execute pinned Python crew serialization/XP methods with isolated resource fixtures."""
from __future__ import print_function
import sys,os,zipfile,marshal,types,struct,math,json
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path[:0]=['tools','src/res/scripts/client']
import audit_client_abi as abi
for name,path in [('gui','src/res/scripts/client/gui'),('gui.mods','src/res/scripts/client/gui/mods')]:
 m=types.ModuleType(name);m.__path__=[os.path.abspath(path)];sys.modules[name]=m
from gui.mods.offline_lan_0922 import crew_skills
class NS(object):
 def __init__(self,**kw):self.__dict__.update(kw)
z=zipfile.ZipFile(sys.argv[1]+'/res/packages/scripts.pkg')
c=marshal.loads(z.read('scripts/common/items/tankmen.pyc')[8:])
sc=types.ModuleType('skills_constants');exec marshal.loads(z.read('scripts/common/items/components/skills_constants.pyc')[8:]) in sc.__dict__
config=NS(getRoleRanks=lambda role:[NS(id=i) for i in range(20)],hasFirstName=lambda x:True,hasLastName=lambda x:True,hasIcon=lambda x:True)
scope=dict(abi._module_constant_globals(c));scope.update(sc.__dict__)
scope.update(__name__='native_crew_audit',struct=struct,math=math,skills_constants=sc,
 ITEM_TYPES=NS(tankman=8),nations=NS(NAMES=['ussr']),vehicles=NS(g_list=NS(getList=lambda nation:{1:NS(tags=frozenset())})),
 getNationConfig=lambda nation:config,getNationGroups=lambda *a:[],findGroupsByIDs=lambda *a:[(0,None)],
 LOG_ERROR=lambda *a:print('native error',a))
for name in ('_makeLevelXpCosts','generateCompactDescr'):
 code=next(v for v in c.co_consts if isinstance(v,types.CodeType) and v.co_name==name)
 scope[name]=types.FunctionType(code,scope)
scope['_g_levelXpCosts']=scope['_makeLevelXpCosts']()
body=next(v for v in c.co_consts if isinstance(v,types.CodeType) and v.co_name=='TankmanDescr')
ns=types.FunctionType(body,scope)()
cls=type('TankmanDescr',(object,),ns);scope['TankmanDescr']=cls
tankmen=NS(TankmanDescr=cls)
raw=scope['generateCompactDescr']((0,False,False,1,1,1),1,'commander',100,[],0,'audit-dossier',[])
d=cls(raw)
for skill in crew_skills.skills_for(('commander','gunner','loader','radioman')):
 before=d.getPassport();d=cls(crew_skills.grant_skill(d,skill,tankmen))
 assert d.getPassport()==before and d.dossierCompactDescr=='audit-dossier' and d.freeXP==0
 assert all(d.skillLevel(s)==100 for s in d.skills)
print('NATIVE PYTHON ROUND TRIP',len(d.skills),'full skills; bounded saved XP:',d.freeXP)
credit=dict(remaining=0,learned=list(d.skills))
updated=crew_skills.reset_grants(d,credit,1.,tankmen);d=cls(d.makeCompactDescr())
assert not d.skills and d.freeXP==0 and updated['remaining']==20
print('NATIVE PYTHON RESET',updated['remaining'],'credits; no duplicated XP')
for training in (50,75,100):
 raw=scope['generateCompactDescr']((0,False,True,1,1,1),1,'commander',training,[],100,'female-dossier',['brotherhood'])
 female=cls(raw)
 assert female.roleLevel==training and female.skills==['brotherhood'] and female.freeSkills==['brotherhood'] and female.freeXP==0
 if training==100:
  for skill in crew_skills.skills_for(('commander','gunner','loader','radioman')):
   if skill!='brotherhood':female=cls(crew_skills.grant_skill(female,skill,tankmen))
  assert len(female.skills)==20 and female.freeSkills==['brotherhood']
  restored=crew_skills.reset_grants(female,dict(remaining=0,learned=[s for s in female.skills if s!='brotherhood']),1.,tankmen)
  female=cls(female.makeCompactDescr())
  assert female.skills==['brotherhood'] and restored['remaining']==19 and female.freeXP==0
print('NATIVE FEMALE CODEC: 50/75/100 training, zero perk and 19 selectable grants round trip')
print('Scope: pinned Python bytecode and codec with resource fixtures; native gameplay not tested.')
