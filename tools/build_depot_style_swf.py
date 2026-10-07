"""Build the warehouse menu from the user's exact #1513 lobby asset.

Requires Java 17 and FFDec 26.3.0. No client asset or decompiled source is
redistributed in this repository. Output belongs at res/gui/flash/lobby.swf
inside the mod; never overwrite the installed client's gui.pkg.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

INPUT_SHA256 = '3a54f7081b35b77dfbcb0048bfe9e8c77f0071cf0586cfb68dabf5a00ff81e55'
BASE = 'net.wg.gui.lobby.store.'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Unexpected #1513 ActionScript anchor: ' + old[:80])
    return source.replace(old, new, 1)


def transform(name, source):
    if name == BASE + 'StoreComponent':
        if source.count('FITTING_TYPES.STORE_SLOTS') != 3:
            raise ValueError('Unexpected store category consumers')
        source = source.replace('FITTING_TYPES.STORE_SLOTS', 'this.getStoreSlots()')
        marker = '      protected function getLinkageFromFittingType(param1:String) : String\n'
        source = replace_once(source, marker, '''      protected function getStoreSlots() : Array
      {
         if(getNameS() == "inventory")
         {
            return FITTING_TYPES.STORE_SLOTS.concat(["offlineStyles"]);
         }
         return FITTING_TYPES.STORE_SLOTS;
      }

''' + marker)
        source = replace_once(source, '         return param1 + FITTING_TYPE_VIEW_POSTFIX;', '''         if(param1 == "offlineStyles")
         {
            return "shopVehicleViewUI";
         }
         return param1 + FITTING_TYPE_VIEW_POSTFIX;''')
        source = replace_once(source, '"label":param1(_loc5_ + NAME_LABEL_SUFFIX),',
            '"label":_loc5_ == "offlineStyles" ? "风格化" : param1(_loc5_ + NAME_LABEL_SUFFIX),')
        source = replace_once(source,
            'this.header.text = MENU.shop_menu(this.getStoreSlots()[param1] + NAME_LABEL_SUFFIX);',
            'this.header.text = this.getStoreSlots()[param1] == "offlineStyles" ? "风格化" : MENU.shop_menu(this.getStoreSlots()[param1] + NAME_LABEL_SUFFIX);')
        source = replace_once(source,
            'this.storeTable.updateHeaderCountTitle(MENU.shop_table_header_count(param1.fittingType));',
            'this.storeTable.updateHeaderCountTitle(param1.fittingType == "offlineStyles" ? "库存" : MENU.shop_table_header_count(param1.fittingType));')
    elif name == BASE + 'views.ShopVehicleView':
        source = replace_once(source, '         return this.getSelectedObtainingType();',
            '         return getUIName() == "inventory" ? "offlineStyles" : this.getSelectedObtainingType();')
    elif name == BASE + 'inventory.InventoryModuleListItemRenderer':
        marker = '      private function updateModuleIcon(param1:StoreTableData) : void\n'
        source = replace_once(source, marker, '''      override protected function showTooltip() : void
      {
         if(data && StoreTableData(data).itemTypeName == "offlineStyle")
         {
            return;
         }
         super.showTooltip();
      }

''' + marker)
        source = replace_once(source,
            '            this.moduleIcon.setValuesWithType(param1.requestType,param1.moduleLabel,param1.level);',
            '''            if(param1.itemTypeName == "offlineStyle")
            {
               getHelper().initModuleIconAsDefault(this.moduleIcon);
            }
            else
            {
               this.moduleIcon.setValuesWithType(param1.requestType,param1.moduleLabel,param1.level);
            }''')
    else:
        raise ValueError('Unreviewed class: ' + name)
    return source


def build(client, java, ffdec, output):
    with zipfile.ZipFile(Path(client) / 'res/packages/gui.pkg') as archive:
        raw = archive.read('gui/flash/lobby.swf')
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA256:
        raise ValueError('Requires Chinese HD 0.9.22.0.1 #1513 lobby.swf')
    classes = (BASE + 'StoreComponent', BASE + 'views.ShopVehicleView',
               BASE + 'inventory.InventoryModuleListItemRenderer')
    command = [str(java), '-Djava.awt.headless=true', '-jar', str(ffdec)]
    with tempfile.TemporaryDirectory(prefix='wot-depot-ui-') as directory:
        temp = Path(directory)
        current = temp / 'lobby.swf'
        current.write_bytes(raw)
        subprocess.run(command + ['-selectclass', ','.join(classes), '-export',
                                  'script', str(temp / 'export'), str(current)], check=True)
        for index, name in enumerate(classes):
            source = temp / 'export/scripts' / (name.replace('.', '/') + '.as')
            patched = temp / ('patch%d.as' % index)
            patched.write_text(transform(name, source.read_text(encoding='utf8')), encoding='utf8')
            target = temp / ('lobby%d.swf' % index)
            subprocess.run(command + ['-replace', str(current), str(target), name,
                                      str(patched)], check=True)
            current = target
        subprocess.run(command + ['-selectclass', ','.join(classes), '-export',
                                  'script', str(temp / 'verify'), str(current)], check=True)
        for name in classes:
            verified = temp / 'verify/scripts' / (name.replace('.', '/') + '.as')
            if 'offlineStyle' not in verified.read_text(encoding='utf8'):
                raise ValueError('Compiled category missing: ' + name)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(current.read_bytes())
    output.with_suffix('.swf.json').write_text(json.dumps(dict(
        input_sha256=INPUT_SHA256, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        classes=list(classes), client='Chinese HD 0.9.22.0.1 #1513'),indent=2)+'\n',encoding='utf8')
    print('Built warehouse styles UI:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('client', 'java', 'ffdec', 'output'):
        parser.add_argument('--' + name, required=True)
    arguments = parser.parse_args()
    build(arguments.client, arguments.java, arguments.ffdec, arguments.output)
