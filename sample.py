"""Image d'exemple (dessinée par le programme, donc libre de droits) pour essayer Croquis sans fichier."""
import math

import numpy as np
from PIL import Image, ImageDraw

W, H = 1200, 900
SS = 2                              # sur-échantillonnage


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _shaded_disc(img, cx, cy, r, base, light=(-0.5, -0.6, 0.62), amb=0.32):
    """Disque ombré comme une sphère (lumière en haut à gauche)."""
    x0, y0 = int(cx - r), int(cy - r)
    n = int(2 * r)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    nx, ny = (xx - r) / r, (yy - r) / r
    rho2 = nx * nx + ny * ny
    nz = np.sqrt(np.clip(1 - rho2, 0, 1))
    lx, ly, lz = light
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lam = np.clip((nx * lx + ny * ly + nz * lz) / ln, 0, 1)
    k = (amb + (1 - amb) * lam)[..., None]
    col = np.clip(np.array(base, np.float32) * k + 28 * np.clip(lam - 0.8, 0, 1)[..., None] * 5, 0, 255)
    alpha = np.clip((1 - np.sqrt(rho2)) * r, 0, 1)            # bord lissé
    patch = Image.fromarray(np.dstack([col.astype(np.uint8), (alpha * 255).astype(np.uint8)]), "RGBA")
    img.alpha_composite(patch, (x0, y0))


def make_sample():
    w, h = W * SS, H * SS
    S = SS
    img = Image.new("RGBA", (w, h))
    # ciel
    sky = np.zeros((h, w, 3), np.uint8)
    top, bot = np.array((108, 190, 250)), np.array((255, 236, 190))
    t = np.linspace(0, 1, h)[:, None] ** 1.3
    sky[:] = (top + (bot - top) * t[..., None]).astype(np.uint8)
    img.paste(Image.fromarray(sky, "RGB"), (0, 0))
    d = ImageDraw.Draw(img)

    # soleil
    _shaded_disc(img, 930 * S, 190 * S, 95 * S, (255, 214, 70), light=(0, 0, 1), amb=0.75)
    # nuages
    for cx, cy, sc in ((250, 150, 1.0), (560, 90, 0.7)):
        for dx, dy, rr in ((0, 0, 48), (50, 12, 38), (-48, 14, 34), (22, -22, 36)):
            _shaded_disc(img, (cx + dx * sc) * S, (cy + dy * sc) * S, rr * sc * S, (255, 255, 255), light=(0, -1, 0.8), amb=0.82)

    # collines lointaines
    far = [(0, h)]
    for x in range(0, w + 1, 8):
        far.append((x, (470 + 38 * math.sin(x / (170 * S) + 1.1) + 18 * math.sin(x / (61 * S))) * S))
    far.append((w, h))
    d.polygon(far, fill=(96, 150, 170))
    # colline proche (dégradé)
    near_top = [(x, (610 + 28 * math.sin(x / (230 * S) + 0.4)) * S) for x in range(0, w + 1, 8)]
    hill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hill)
    hd.polygon([(0, h)] + near_top + [(w, h)], fill=(255, 255, 255, 255))
    g = np.zeros((h, w, 3), np.uint8)
    gt = np.linspace(0, 1, h)[:, None]
    g[:] = (np.array((140, 205, 90)) + (np.array((60, 130, 60)) - np.array((140, 205, 90))) * np.clip((gt - 0.65) / 0.35, 0, 1)[..., None]).astype(np.uint8)
    gi = Image.fromarray(g, "RGB").convert("RGBA")
    gi.putalpha(hill.split()[3])
    img.alpha_composite(gi)
    d = ImageDraw.Draw(img)

    # maison
    hx, hy, hw, hh = 230 * S, 520 * S, 330 * S, 220 * S
    wall = Image.new("RGB", (int(hw), int(hh)))
    wa = np.zeros((int(hh), int(hw), 3), np.uint8)
    wa[:] = (np.array((247, 224, 186)) + (np.array((226, 196, 152)) - np.array((247, 224, 186))) * np.linspace(0, 1, int(hw))[None, :, None]).astype(np.uint8)
    img.paste(Image.fromarray(wa, "RGB"), (int(hx), int(hy)))
    d.rectangle((hx + 250 * S, hy - 110 * S, hx + 295 * S, hy - 20 * S), fill=(168, 84, 66))          # cheminée
    d.polygon([(hx - 30 * S, hy + 4 * S), (hx + hw / 2, hy - 160 * S), (hx + hw + 30 * S, hy + 4 * S)], fill=(206, 70, 58))
    d.polygon([(hx + hw / 2, hy - 160 * S), (hx + hw + 30 * S, hy + 4 * S), (hx + hw / 2 + 10 * S, hy + 4 * S)], fill=(160, 48, 46))
    d.rectangle((hx + 40 * S, hy + 70 * S, hx + 120 * S, hy + 150 * S), fill=(120, 190, 235))          # fenêtre
    d.rectangle((hx + 40 * S, hy + 70 * S, hx + 120 * S, hy + 150 * S), outline=(120, 76, 50), width=6 * S)
    d.line((hx + 80 * S, hy + 70 * S, hx + 80 * S, hy + 150 * S), fill=(120, 76, 50), width=5 * S)
    d.line((hx + 40 * S, hy + 110 * S, hx + 120 * S, hy + 110 * S), fill=(120, 76, 50), width=5 * S)
    d.rectangle((hx + 190 * S, hy + 70 * S, hx + 280 * S, hh + hy), fill=(132, 84, 52))                # porte
    d.ellipse((hx + 258 * S, hy + 140 * S, hx + 270 * S, hy + 152 * S), fill=(240, 200, 80))

    # arbre
    tx = 820 * S
    trunk = np.zeros((int(210 * S), int(46 * S), 3), np.uint8)
    trunk[:] = (np.array((150, 98, 60)) + (np.array((92, 58, 38)) - np.array((150, 98, 60))) * np.linspace(0, 1, int(46 * S))[None, :, None]).astype(np.uint8)
    img.paste(Image.fromarray(trunk, "RGB"), (int(tx - 23 * S), int(560 * S)))
    for dx, dy, rr in ((0, 0, 92), (-78, 50, 70), (80, 52, 72), (-30, -66, 66), (40, -52, 60)):
        _shaded_disc(img, tx + dx * S, 470 * S + dy * S, rr * S, (66, 164, 78), amb=0.3)

    # ballon (sphère rouge) et son ombre au sol
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((560 * S, 770 * S, 760 * S, 812 * S), fill=(30, 60, 30, 110))
    img.alpha_composite(sh)
    _shaded_disc(img, 650 * S, 735 * S, 66 * S, (226, 48, 56), amb=0.28)

    # fleurs
    d = ImageDraw.Draw(img)
    for fx, fy, col in ((90, 790, (255, 120, 170)), (150, 830, (255, 214, 70)), (1010, 800, (255, 120, 170)), (1080, 770, (255, 255, 255)), (960, 850, (255, 214, 70))):
        d.line((fx * S, fy * S, fx * S, (fy + 40) * S), fill=(48, 120, 56), width=4 * S)
        for k in range(6):
            a = k * math.pi / 3
            d.ellipse(((fx + 13 * math.cos(a) - 9) * S, (fy + 13 * math.sin(a) - 9) * S, (fx + 13 * math.cos(a) + 9) * S, (fy + 13 * math.sin(a) + 9) * S), fill=col)
        d.ellipse(((fx - 8) * S, (fy - 8) * S, (fx + 8) * S, (fy + 8) * S), fill=(250, 190, 40))
    return np.asarray(img.convert("RGB").resize((W, H), Image.LANCZOS), dtype=np.uint8)


if __name__ == "__main__":
    Image.fromarray(make_sample()).save("sample_preview.png")
