"""Native material decoding and removal of the invalid map-text override."""
import json
from pathlib import Path
import struct
import sys
import unittest
import zlib
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_waiting_room_skin as skin
import build_map_picker_swf as picker


class NativeSkinTests(unittest.TestCase):
    def test_argb_unpremultiplies_and_preserves_real_alpha(self):
        raw = struct.pack('<HBHH',1,5,2,1)+zlib.compress(
            bytes((128,64,32,0,0,0,0,0)))
        image = skin.decode_bitmap(raw,True)
        self.assertEqual([(128,64,0,128),(0,0,0,0)],list(image.getdata()))

    def test_xrgb_ignores_padding_instead_of_becoming_invisible(self):
        raw = struct.pack('<HBHH',1,5,1,1)+zlib.compress(bytes((0,90,40,20)))
        self.assertEqual((90,40,20,255),skin.decode_bitmap(raw,False).getpixel((0,0)))

    def test_truncated_native_bitmap_is_rejected(self):
        raw = struct.pack('<HBHH',1,5,2,1)+zlib.compress(bytes((255,1,2,3)))
        with self.assertRaisesRegex(ValueError,'length mismatch'):
            skin.decode_bitmap(raw,True)

    def test_nine_slice_keeps_native_corners_and_their_alpha(self):
        image = Image.new('RGBA',(5,5),(10,20,30,40))
        for at,colour in (((0,0),(1,2,3,255)),((4,0),(4,5,6,128)),
                          ((0,4),(7,8,9,64)),((4,4),(10,11,12,32))):
            image.putpixel(at,colour)
        resized = skin.nine_slice(image,(9,11),(1,1,1,1))
        for a,b in (((0,0),(0,0)),((4,0),(8,0)),((0,4),(0,10)),((4,4),(8,10))):
            self.assertEqual(image.getpixel(a),resized.getpixel(b))

    def test_packaged_materials_have_the_native_bitmap_dimensions(self):
        root = ROOT/'src/res/gui/maps/offline_lan'
        receipt = json.loads((root/'waiting_skin_source.json').read_text())
        self.assertEqual(skin.SOURCE_HASHES,receipt['source_members'])
        for role in ('button','start','field'):
            member,cid,size = skin.BITMAPS[role]
            self.assertEqual(list(size),receipt['bitmaps'][role]['size'])
            self.assertEqual(cid,receipt['bitmaps'][role]['character_id'])
            with Image.open(root/('waiting_'+role+'.dds')) as image:
                crop = skin.CROPS[role]
                self.assertEqual((crop[2]-crop[0],crop[3]-crop[1]),image.size)
        with Image.open(root/'waiting_panel.dds') as image:
            self.assertEqual((640,286),image.size)

    def test_normal_faces_keep_native_bevel_pixels_at_every_control_width(self):
        root=ROOT/'src/res/gui/maps/offline_lan'
        with Image.open(root/'waiting_button.dds') as original:
            for name,width in (('small',24),('normal',180),('close',100),('random',128)):
                with Image.open(root/('waiting_button_'+name+'.dds')) as face:
                    self.assertEqual((width,22),face.size)
                    self.assertEqual(original.getpixel((1,1)),face.getpixel((1,1)))
                    self.assertEqual(original.getpixel((158,20)),face.getpixel((width-2,20)))

    def test_client_map_picker_movie_is_not_overridden(self):
        self.assertFalse((ROOT/'src/res/gui/flash/trainingWindow.swf').exists())
        self.assertTrue(picker.OUTPUT_PATH.startswith('build/'))


if __name__ == '__main__':
    unittest.main()
