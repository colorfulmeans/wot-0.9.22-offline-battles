"""Build original RGBA skins; native #1513 textured quads ignore vertex tint."""
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'src/res/gui/maps/offline_lan'


def texture(size, seed):
    """Seeded grain and broad mottling without repeating diagonal patterns."""
    rng = random.Random(seed)
    fine = Image.new('L', size)
    fine.putdata([rng.randrange(256) for _ in range(size[0]*size[1])])
    clouds = fine.resize((32, 8), Image.Resampling.BILINEAR).resize(
        size, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(2))
    return fine, clouds


def button(name, top, bottom, border, seed):
    image = Image.new('RGBA', (512, 48))
    fine, clouds = texture(image.size, seed)
    pixels = image.load()
    for y in range(48):
        blend = y/47.
        # A soft upper sheen and recessed lower edge match the game's metal.
        sheen = 7 * math.exp(-((blend-.16)/.23)**2)
        for x in range(512):
            wear = (fine.getpixel((x,y))-128)*.035
            wear += (clouds.getpixel((x,y))-128)*.30
            vignette = -7 * abs(x/511.-.5)*2
            colour = tuple(max(0, min(255, round(a+(b-a)*blend+
                sheen+wear+vignette))) for a,b in zip(top,bottom))
            pixels[x,y] = colour+(255,)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0,0,511,47), outline=(25,24,15,255), width=1)
    draw.rectangle((1,1,510,46), outline=border+(255,), width=1)
    draw.line((2,2,509,2), fill=tuple(min(255,c+34) for c in border)+(255,))
    draw.line((2,45,509,45), fill=(39,37,22,255))
    image.save(OUTPUT/(name+'.dds'))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel = Image.new('RGBA', (512,256))
    fine, clouds = texture(panel.size, 1513)
    pixels = panel.load()
    for y in range(256):
        for x in range(512):
            grain = (fine.getpixel((x,y))-128)*.025
            grain += (clouds.getpixel((x,y))-128)*.40
            # Stock settings-window reference: olive metal header/footer,
            # narrow side frame and recessed dark content. This is original
            # artwork, not a redistributed Flash bitmap or a GUI replacement.
            if y < 14:
                blend = y/13.
                base = tuple(a+(b-a)*blend for a,b in
                             zip((105,106,83),(43,45,32)))
                alpha = 250
            elif y >= 228:
                blend = (y-228)/27.
                base = tuple(a+(b-a)*blend for a,b in
                             zip((63,66,46),(33,36,25)))
                alpha = 250
            elif x < 3 or x >= 509:
                base, alpha = (51,54,37), 250
            else:
                light = 3*(1-y/255.)
                base, alpha = (18+light,19+light,12+light), 230
            pixels[x,y] = tuple(max(0,min(255,round(c+grain)))
                                for c in base)+(alpha,)
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0,0,511,255), outline=(27,29,19,255), width=1)
    draw.line((1,0,510,0), fill=(153,151,111,255))
    draw.line((1,1,510,1), fill=(116,117,86,255))
    draw.line((1,1,1,254), fill=(97,99,68,255))
    draw.line((510,1,510,254), fill=(69,72,49,255))
    draw.rectangle((3,14,508,227), outline=(82,83,56,255), width=1)
    draw.rectangle((4,15,507,226), outline=(5,7,3,255), width=1)
    panel.save(OUTPUT/'waiting_panel.dds')
    button('waiting_button', (109,110,83), (51,54,35), (151,149,115), 922)
    button('waiting_start', (210,23,10), (126,9,4), (231,80,44), 102)



if __name__ == '__main__':
    main()
