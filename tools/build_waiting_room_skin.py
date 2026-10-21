"""Build original RGBA skins; native #1513 textured quads ignore vertex tint."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'src/res/gui/maps/offline_lan'


def button(name, top, bottom, border):
    image = Image.new('RGBA', (512, 48))
    draw = ImageDraw.Draw(image)
    for y in range(48):
        blend = y/47.
        colour = tuple(round(a+(b-a)*blend) for a, b in zip(top, bottom))
        draw.line((0, y, 511, y), fill=colour+(255,))
    draw.rectangle((0, 0, 511, 47), outline=(15, 16, 10, 255), width=1)
    draw.rectangle((1, 1, 510, 46), outline=border+(255,), width=1)
    draw.line((2, 2, 509, 2), fill=tuple(min(255, c+24) for c in border)+(255,))
    draw.line((2, 45, 509, 45), fill=(31, 31, 18, 255))
    image.save(OUTPUT/(name+'.dds'))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel = Image.new('RGBA', (512, 256))
    pixels = panel.load()
    for y in range(256):
        for x in range(512):
            grain = ((x*13+y*7) % 5)-2
            light = int(5*(1-y/255.))
            pixels[x, y] = (12+grain+light, 13+grain+light, 9+grain+light, 222)
    ImageDraw.Draw(panel).rectangle((0, 0, 511, 255), outline=(6, 7, 4, 246), width=2)
    panel.save(OUTPUT/'waiting_panel.dds')
    button('waiting_button', (105, 109, 82), (47, 50, 33), (146, 148, 112))
    button('waiting_start', (181, 25, 13), (103, 7, 4), (222, 66, 40))


if __name__ == '__main__':
    main()
