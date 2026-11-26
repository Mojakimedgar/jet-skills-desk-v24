"""Place every team portrait on a clean white background.

Pipeline per photo: standard 4:5 crop (see make_team_portraits.py) -> GrabCut segmentation seeded with
head/shoulder priors -> guided-filter edge refinement -> colour clean-up of edge pixels -> composite on white.

Run:  python scripts/whiten_team_backgrounds.py [name ...]      (no names = everyone)
      python scripts/whiten_team_backgrounds.py --sheet          (also writes a review sheet to /tmp/team_review.png)

Each photo can carry hints in HINTS: rectangles (fractions of the 560x700 portrait) that are certainly the
person ('fg') or certainly background ('bg'). Adjust them if a cut-out looks wrong, then re-run.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_team_portraits import OUT, PEOPLE, SIZE, SRC, crop_box, open_source  # noqa: E402

W, H = SIZE
# Hints per photo, in fractions of the 560x700 portrait. Each hint is (kind, shape, *numbers):
#   kind  fg  = certainly the person, used exactly (for dark hair on a dark backdrop, where colour cannot tell them apart)
#         sfg = probably the person: the edge is decided from colour, the inside is kept
#         bg  = certainly background
#   shape poly = flat list of x,y points            ell = cx, cy, rx, ry
# A photo listed in REPLACE_DEFAULT ignores the generic head/shoulder prior and uses only its own hints.
HINTS = {
    "mampho.png": [("fg", "ell", .50, .20, .185, .235), ("fg", "poly", .41, .36, .61, .36, .63, .48, 1, .60, 1, 1, 0, 1, 0, .62, .39, .48)],
    "sean.jpg": [("sfg", "ell", .50, .30, .21, .22)],
    "papie-medgar-mojaki.jpg": [("sfg", "ell", 0.581, 0.477, .225, .27), ("sfg", "poly", 0.445, 0.725, 0.734, 0.672, 0.836, 0.685, 1.0, 0.735, 1.0, 1.0, 0.133, 1.0, 0.144, 0.919, 0.234, 0.79, 0.375, 0.723),
                                ("bg", "poly", 0, 0, 1, 0, 1, .195, 0, .195)],
    "koketso.jpeg": [("bg", "poly", .68, .18, .84, .18, .84, .62, .68, .62), ("bg", "poly", 0, .20, .12, .20, .12, .60, 0, .60)],
    "mercy.jpeg": [("sfg", "ell", .50, .27, .22, .25), ("sfg", "poly", .24, .36, .32, .36, .32, .64, .24, .64),
                   ("sfg", "poly", .36, .54, .66, .54, 1, .66, 1, 1, 0, 1, 0, .63),
                   ("bg", "poly", .73, .42, 1, .42, 1, .70, .90, .665, .76, .645, .62, .607, .68, .52), ("bg", "poly", 0, .40, .26, .40, .26, .60, 0, .625)],
    "patience.jpg": [("sfg", "poly", .25, .13, .45, .03, .90, .03, .95, .10, .66, .20, .35, .21), ("sfg", "ell", .50, .38, .17, .20),
                     ("sfg", "poly", .66, .27, .77, .25, .80, .36, .82, .50, .74, .52, .70, .42), ("sfg", "poly", .76, .48, .95, .52, 1, .62, .80, .62),
                     ("sfg", "poly", .34, .55, .66, .55, 1, .62, 1, 1, 0, 1, 0, .62)],
}
REPLACE_DEFAULT = {"mampho.png", "papie-medgar-mojaki.jpg", "mercy.jpeg", "patience.jpg"}
# name -> [(x0, y0, x1, y1, min_brightness, max_colourfulness)]: grey wall left in a small region is turned white
GREY_FIX = {"mercy.jpeg": [(.22, .415, .31, .50, 100, 40), (.22, .50, .36, .64, 62, 38), (.575, .50, .86, .66, 55, 38)]}
WHITE_ALREADY = {"mzwakhe.jpg"}      # photographed on white: only levels are adjusted


def shape_mask(shape, nums):
    m = np.zeros((H, W), np.uint8)
    if shape == "ell":
        cx, cy, rx, ry = nums
        cv2.ellipse(m, (int(cx * W), int(cy * H)), (int(rx * W), int(ry * H)), 0, 0, 360, 1, -1)
    else:
        pts = (np.array(nums, np.float32).reshape(-1, 2) * [W, H]).astype(np.int32)
        cv2.fillPoly(m, [pts], 1)
    return m


def rect(mask, kind, x0, y0, x1, y1):
    v = {"fg": cv2.GC_FGD, "pfg": cv2.GC_PR_FGD, "bg": cv2.GC_BGD, "pbg": cv2.GC_PR_BGD}[kind]
    mask[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = v


def seed_mask(name):
    m = np.full((H, W), cv2.GC_PR_BGD, np.uint8)
    if name not in REPLACE_DEFAULT:
        # every portrait is framed the same way: face centred at x=0.5, head top at ~0.14, chin at ~0.52
        cv2.ellipse(m, (int(W * .5), int(H * .33)), (int(W * .17), int(H * .20)), 0, 0, 360, cv2.GC_PR_FGD, -1)
        cv2.ellipse(m, (int(W * .5), int(H * .34)), (int(W * .09), int(H * .13)), 0, 0, 360, cv2.GC_FGD, -1)
        body = np.array([[.30, .52], [.70, .52], [.97, .70], [1.0, 1.0], [0, 1.0], [.03, .70]]) * [W, H]
        cv2.fillPoly(m, [body.astype(np.int32)], cv2.GC_PR_FGD)
        core = np.array([[.40, .56], [.60, .56], [.72, 1.0], [.28, 1.0]]) * [W, H]
        cv2.fillPoly(m, [core.astype(np.int32)], cv2.GC_FGD)
        rect(m, "bg", 0, 0, .02, 1); rect(m, "bg", .98, 0, 1, .6); rect(m, "bg", 0, 0, 1, .02)
        rect(m, "bg", 0, 0, .12, .30); rect(m, "bg", .88, 0, 1, .30)
    else:
        rect(m, "bg", 0, 0, .02, .5); rect(m, "bg", .98, 0, 1, .5)
    soft = [h for h in HINTS.get(name, []) if h[0] == "sfg"]
    for kind, shape, *nums in soft:
        region = shape_mask(shape, nums)
        m[region == 1] = cv2.GC_PR_FGD
    for kind, shape, *nums in soft:
        inner = cv2.erode(shape_mask(shape, nums), np.ones((3, 3), np.uint8), iterations=14)
        m[inner == 1] = cv2.GC_FGD
    for kind, shape, *nums in HINTS.get(name, []):
        if kind == "fg":
            m[shape_mask(shape, nums) == 1] = cv2.GC_FGD
    for kind, shape, *nums in HINTS.get(name, []):
        if kind == "bg":
            m[shape_mask(shape, nums) == 1] = cv2.GC_BGD
    return m


def guided(I, p, r=8, eps=1e-3):
    box = lambda x: cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))
    mI, mp = box(I), box(p)
    a = (box(I * p) - mI * mp) / (box(I * I) - mI * mI + eps)
    b = mp - a * mI
    return box(a) * I + box(b)


def cutout(img_bgr, name):
    mask = seed_mask(name)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img_bgr, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    # keep the main person, fill pinholes, smooth the outline
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:
        fg = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    inv = 1 - fg; n, lab, stats, _ = cv2.connectedComponentsWithStats(inv)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 900:
            fg[lab == i] = 1
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # trimap -> refined soft alpha
    k = np.ones((3, 3), np.uint8)
    sure_fg, maybe = cv2.erode(fg, k, iterations=3), cv2.dilate(fg, k, iterations=3)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    soft = guided(gray, cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 1.2), r=6, eps=2e-3)
    alpha = np.clip(soft, 0, 1)
    alpha[sure_fg == 1] = 1; alpha[maybe == 0] = 0
    alpha = np.clip((alpha - .08) / .84, 0, 1)            # tighten the soft edge slightly
    return alpha.astype(np.float32)


def composite(img_bgr, alpha):
    img = img_bgr.astype(np.float32)
    core = (alpha > .98).astype(np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (0, 0), 3)
    est = blur(img * core[..., None]) / np.maximum(blur(core), 1e-3)[..., None]     # colour of nearby solid person
    edge = ((alpha > 0) & (alpha < .98)).astype(np.float32)[..., None]
    img = img * (1 - .85 * edge) + est * (.85 * edge)                              # remove the old background's colour from the edge
    a = alpha[..., None]
    return np.clip(img * a + 255 * (1 - a), 0, 255).astype(np.uint8)


def grey_fix(out_bgr, name):
    for x0, y0, x1, y1, lo, sat in GREY_FIX.get(name, []):
        ys, xs = slice(int(y0 * H), int(y1 * H)), slice(int(x0 * W), int(x1 * W))
        reg = out_bgr[ys, xs].astype(np.float32)
        bright = reg.mean(axis=2)
        colour = reg.max(axis=2) - reg.min(axis=2)
        k = np.clip((bright - lo) / 25, 0, 1) * np.clip((sat - colour) / 15, 0, 1)
        k = cv2.GaussianBlur(k, (0, 0), 1.0)[..., None]
        out_bgr[ys, xs] = np.clip(reg * (1 - k) + 255 * k, 0, 255).astype(np.uint8)
    return out_bgr


def whiten_levels(img_bgr):
    """Photo already on white: push the near-white backdrop to pure white."""
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = np.clip((g - 226) / 20, 0, 1)[..., None]
    return np.clip(img_bgr * (1 - k) + 255 * k, 0, 255).astype(np.uint8)


def make(name):
    cx, top, chin = PEOPLE[name]
    im = open_source(name)
    portrait = im.crop(crop_box(*im.size, cx, top, chin)).resize(SIZE, Image.LANCZOS)
    bgr = cv2.cvtColor(np.array(portrait), cv2.COLOR_RGB2BGR)
    out = whiten_levels(bgr) if name in WHITE_ALREADY else grey_fix(composite(bgr, cutout(bgr, name)), name)
    dest = OUT / (Path(name).stem + ".jpg")
    Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(dest, quality=90, optimize=True, progressive=True)
    return dest


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = args or list(PEOPLE)
    OUT.mkdir(parents=True, exist_ok=True)
    for n in names:
        print("done", make(n).name)
    if "--sheet" in sys.argv:
        ims = [Image.open(OUT / (Path(n).stem + ".jpg")).resize((280, 350)) for n in PEOPLE]
        sheet = Image.new("RGB", (280 * 5 + 32, 350 * 2 + 8), (200, 200, 200))
        for i, im in enumerate(ims):
            sheet.paste(im, ((i % 5) * 288, (i // 5) * 358))
        sheet.save("/tmp/team_review.png")
