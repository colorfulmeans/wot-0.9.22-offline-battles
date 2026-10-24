"""Export resource-backed passport groups for the Python 2 native codec audit."""
import base64
import json
from pathlib import Path
import sys
import zipfile
from packed_xml import read_packed_xml, TYPE_COMPRESSED_STRING

NATIONS=('ussr','germany','usa','china','france','uk','japan','czech','sweden','poland')

def export(game_root):
    result=[]
    with zipfile.ZipFile(Path(game_root)/'res/packages/scripts.pkg') as archive:
        for nation in NATIONS:
            root=read_packed_xml(archive.read('scripts/item_defs/tankmen/%s.xml'%nation))
            pools=[]
            for pool in ('normalGroups','premiumGroups'):
                section=dict(root.children)[pool.encode()].value
                groups=[]
                for name,group in section.children:
                    fields=dict(group.value.children)
                    sex=fields[b'sex']
                    sex=base64.b64encode(sex.value) if sex.value_type==TYPE_COMPRESSED_STRING else sex.value
                    data=dict(isFemales=sex==b'female')
                    for native,field in (('firstNamesList',b'firstNames'),('lastNamesList',b'lastNames'),('iconsList',b'icons')):
                        data[native]=[int(key[1:]) for key,value in fields[field].value.children]
                    groups.append(data)
                pools.append(groups)
            result.append(pools)
    return result

if __name__=='__main__':
    Path(sys.argv[2]).write_text(json.dumps(export(sys.argv[1])),encoding='utf8')
