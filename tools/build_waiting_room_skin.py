"""Adapt the pinned client's own window/button bitmaps for the LAN room.

No noise, gradients, recolouring or replacement artwork is generated. Only
lossless SWF decoding, alpha unpremultiplication and native-style nine-slice
layout are applied. Never modify the installed client's gui.pkg.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import zipfile
import zlib
from PIL import Image
from build_map_picker_swf import (_validate_client, _decompress_swf,
                                  _skip_rect, _iter_tags)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'src/res/gui/maps/offline_lan'
SOURCE_HASHES = {
    'windows': '93d0e70d891fdbcc9083c70ba3740558c7409728dd5a1626aacff1d6c608ac3d',
    'guiControlsLobby': 'def7e31310aa7fad75732ceb308e4a43ad2fb5c2dbf65229ee4232134c4292b3',
    'guiControlsLobbyBattle': 'f6d12e6e40ab402703c2f4a15449665ed009cbfeab9689a85e745b119d761f92',
    'guiControlsLogin': 'df3b25cbba714522eb79b5d1a86d260cddf9166f6073387e5a87422a0ccbabd0',
}
BITMAPS = {
    'frame': ('windows', 2, (826,390)),
    'body': ('windows', 1, (803,340)),
    'button': ('guiControlsLobbyBattle', 525, (239,39)),
    'start': ('guiControlsLogin', 58, (158,50)),
    'field': ('guiControlsLobby', 349, (134,28)),
}

# Trim only the native bitmap's baked shadow/transparent padding so a
# requested 22 px control has a 22 px face, as the stock component does.
CROPS = {'frame':(8,8,817,377), 'button':(0,6,239,33),
         'field':(3,3,131,24), 'start':(0,0,158,50)}


def decode_bitmap(raw, has_alpha):
    """Decode SWF format-5 XRGB/ARGB, whose alpha colours are premultiplied."""
    if len(raw) < 7:
        raise ValueError('Truncated native bitmap')
    cid, fmt, width, height = struct.unpack_from('<HBHH', raw)
    if fmt != 5 or not width or not height or width*height > 16000000:
        raise ValueError('Unexpected native bitmap format/dimensions')
    pixels = zlib.decompress(raw[7:])
    if len(pixels) != width*height*4:
        raise ValueError('Native bitmap pixel length mismatch')
    rgba = bytearray(len(pixels))
    for at in range(0,len(pixels),4):
        alpha,r,g,b = pixels[at:at+4]
        alpha = alpha if has_alpha else 255
        rgb = tuple(min(255,round(c*255/alpha)) if alpha else 0 for c in (r,g,b))
        rgba[at:at+4] = bytes(rgb+(alpha,))
    return Image.frombytes('RGBA',(width,height),bytes(rgba))


def nine_slice(image, size, margins):
    """Preserve native corner/bevel pixels while sizing the frame/content."""
    width,height = size
    left,top,right,bottom = margins
    if width <= left+right or height <= top+bottom:
        raise ValueError('Target is smaller than native frame margins')
    source_x = (0,left,image.width-right,image.width)
    source_y = (0,top,image.height-bottom,image.height)
    target_x = (0,left,width-right,width)
    target_y = (0,top,height-bottom,height)
    output = Image.new('RGBA',size)
    for row in range(3):
        for col in range(3):
            tile = image.crop((source_x[col],source_y[row],
                               source_x[col+1],source_y[row+1]))
            target_size = (target_x[col+1]-target_x[col],target_y[row+1]-target_y[row])
            if tile.size != target_size:
                tile = tile.resize(target_size,Image.Resampling.BICUBIC)
            output.paste(tile,(target_x[col],target_y[row]))
    return output


def build(client_root, output):
    package = _validate_client(client_root)
    found = {}
    with zipfile.ZipFile(package) as archive:
        for member, expected in SOURCE_HASHES.items():
            source = archive.read('gui/flash/'+member+'.swf')
            if hashlib.sha256(source).hexdigest() != expected:
                raise ValueError('Native #1513 UI source changed: '+member)
            decoded = _decompress_swf(source)
            wanted = {cid:role for role,(owner,cid,size) in BITMAPS.items() if owner==member}
            for code,unused_start,a,b,unused_sprite in _iter_tags(
                    decoded,_skip_rect(decoded,8)+4,len(decoded)):
                if code not in (20,36):
                    continue
                cid = struct.unpack_from('<H',decoded,a)[0]
                if cid not in wanted:
                    continue
                role = wanted[cid]
                image = decode_bitmap(decoded[a:b],code==36)
                if image.size != BITMAPS[role][2] or role in found:
                    raise ValueError('Native UI bitmap identity changed: '+role)
                found[role] = image
    if set(found) != set(BITMAPS):
        raise ValueError('Missing native window/button bitmap')
    panel = nine_slice(found['frame'].crop(CROPS['frame']),
                       (640,330),(8,26,8,38))
    panel.alpha_composite(nine_slice(found['body'],(624,264),(8,8,8,8)),(8,27))
    textures = {'panel':panel}
    textures.update({role:found[role].crop(CROPS[role])
                     for role in ('button','start','field')})
    output.mkdir(parents=True,exist_ok=True)
    for role,image in textures.items():
        image.save(output/('waiting_'+role+'.dds'))
    receipt = {'client':'0.9.22.0.1 #1513','source_members':SOURCE_HASHES,
               'bitmaps':{role:{'member':'gui/flash/'+member+'.swf',
                    'character_id':cid,'size':size} for role,(member,cid,size) in BITMAPS.items()},
               'native_content_crops':CROPS,
               'operations':{'panel':'Native Window frame/content nine-slice at 640x330',
                    'button':'Native bitmap, shadow padding trimmed', 'start':'Native battle button bitmap',
                    'field':'Native recessed field bitmap, transparent padding trimmed'}}
    (output/'waiting_skin_source.json').write_bytes(
        (json.dumps(receipt,indent=2)+'\n').encode('utf-8'))
    print('Built native #1513 waiting-room assets:',output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client_root',type=Path)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args = parser.parse_args()
    build(args.client_root,args.output)


if __name__ == '__main__':
    main()
