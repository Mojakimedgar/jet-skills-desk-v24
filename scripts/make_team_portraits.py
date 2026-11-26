"""Create uniformly framed team portraits (4:5, up to 560x700) from the original photos.

The photos are shown AS THEY ARE: only cropped to the same 4:5 frame with a similar head position,
never cut out, never recoloured and never placed on a white background. Originals are never modified.

To add or replace a person: put the photo in static/images/, add an entry below with
  cx   = horizontal centre of the face (fraction of image width, 0-1)
  top  = top of the head or hair (fraction of image height)
  chin = bottom of the chin (fraction of image height)
and run:  python scripts/make_team_portraits.py
(Tip: if a face is small or the photo is low resolution, the result is upscaled and will look soft.
Use the highest-resolution original you have.)
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "static/images", ROOT / "static/images/team"
SIZE = (560, 700)          # 4:5
HEAD_FRACTION = 0.38       # head (hair top to chin) as a share of the portrait height
HEADROOM = 0.14            # space above the head as a share of the portrait height

# No padding is added to any photo (nothing artificial is put around the person).
PAD_TOP = {}

PEOPLE = {  # file: (cx, top, chin)
    "mampho.png": (0.43, 0.00, 0.345),
    "sean.jpg": (0.55, 0.10, 0.53),
    "papie-medgar-mojaki.jpg": (0.58, 0.012, 0.675),
    "koketso.jpeg": (0.56, 0.28, 0.53),
    "mzwakhe.jpg": (0.50, 0.14, 0.53),
    "athabile-ntlokwana.jpg": (0.49, 0.10, 0.46),
    "mercy.jpeg": (0.50, 0.05, 0.46),
    "sinalo.jpeg": (0.53, 0.14, 0.50),
    "patience.jpg": (0.545, 0.03, 0.27),
}


def open_source(name):
    im = Image.open(SRC / name).convert("RGB")
    pad = PAD_TOP.get(name)
    if pad:
        canvas = Image.new("RGB", (im.width, round(im.height * (1 + pad))), (255, 255, 255))
        canvas.paste(im, (0, canvas.height - im.height))
        im = canvas
    return im


def crop_box(w, h, cx, top, chin):
    head = (chin - top) * h
    ch = head / HEAD_FRACTION                 # ideal crop height
    ch = min(ch, h, w / 0.8)                  # cannot exceed the photo
    cw = ch * 0.8
    y = top * h - HEADROOM * ch
    x = cx * w - cw / 2
    y = max(0, min(y, h - ch)); x = max(0, min(x, w - cw))
    return round(x), round(y), round(x + cw), round(y + ch)


def main():
    """Crop every photo to the shared 4:5 frame (no background change). Never upscales beyond the original."""
    OUT.mkdir(parents=True, exist_ok=True)
    for name in PEOPLE:
        im = open_source(name)
        portrait = im.crop(crop_box(*im.size, *PEOPLE[name]))
        if portrait.width > SIZE[0]:
            portrait = portrait.resize(SIZE, Image.LANCZOS)
        stem = Path(name).stem
        portrait.save(OUT / f"{stem}.jpg", quality=90, optimize=True, progressive=True)
        portrait.save(OUT / f"{stem}.webp", quality=88, method=6)
        print("done", stem, portrait.size)


if __name__ == "__main__":
    main()
