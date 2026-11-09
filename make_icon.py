"""Génère icon.icns et docs/icon.png.

Une sphère coupée en deux : à gauche la couleur (l'image d'origine), à droite le croquis
(contour noir + hachures d'ombre). Style graphique : gros traits noirs, ombre portée dure, fond jaune.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import numpy as np
import math, os, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024            # taille finale
K = 3               # sur-échantillonnage (anti-crénelage)
W = S * K


def px(v):
    return int(round(v * K))


def P(x, y):
    return (px(x), px(y))


def to_L(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "L")


yy, xx = np.mgrid[0:W, 0:W].astype(np.float32)
INK = (20, 18, 28, 255)
PAPER = (253, 252, 248, 255)


def circle_mask(cx, cy, r):
    return (((xx - px(cx)) ** 2 + (yy - px(cy)) ** 2) <= px(r) ** 2)


# ── fond : jaune vif en carré arrondi ──
t = np.clip((0.5 * xx + 0.9 * yy) / (1.4 * W), 0, 1)[..., None]
c0 = np.array((255, 226, 92), np.float32)
c1 = np.array((255, 178, 26), np.float32)
rgb = (c0 + (c1 - c0) * t).astype(np.uint8)
bg = Image.fromarray(np.dstack([rgb, np.full((W, W, 1), 255, np.uint8)]), "RGBA")
sq = Image.new("L", (W, W), 0)
ImageDraw.Draw(sq).rounded_rectangle((px(64), px(64), px(S - 64), px(S - 64)), radius=px(205), fill=255)

CX, CY, R = 466, 474, 288        # sphère
SH = 50                          # décalage de l'ombre portée dure

img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
img.alpha_composite(bg)

# ombre portée dure (noir plein)
shadow = Image.new("RGBA", (W, W), (214, 112, 8, 255))   # ombre portée orange foncé (laisse lire les hachures)
shadow.putalpha(to_L(circle_mask(CX + SH, CY + SH, R + 6)))
img.alpha_composite(shadow)

# base blanche
base = Image.new("RGBA", (W, W), PAPER)
base.putalpha(to_L(circle_mask(CX, CY, R)))
img.alpha_composite(base)

# ── demi-plan gauche (coupure légèrement penchée) ──
phi = math.radians(-14)
side = (xx - px(CX)) * math.cos(phi) + (yy - px(CY)) * math.sin(phi)
left = side < 0
inside = circle_mask(CX, CY, R)

# moitié couleur : dégradé coucher de soleil
g = np.clip(((xx - px(CX - R)) * 0.55 + (yy - px(CY - R)) * 0.85) / (px(2 * R) * 1.2), 0, 1)[..., None]
stops = [(0.0, (255, 120, 60)), (0.5, (238, 46, 128)), (1.0, (96, 60, 232))]
col = np.zeros((W, W, 3), np.float32)
for (a, ca), (b, cb) in zip(stops, stops[1:]):
    m = (g >= a) & (g <= b)
    u = np.where(m, (g - a) / (b - a), 0)
    col = np.where(m, np.array(ca, np.float32) + (np.array(cb, np.float32) - np.array(ca, np.float32)) * u, col)
colimg = Image.fromarray(np.dstack([col.astype(np.uint8), np.full((W, W, 1), 255, np.uint8)]), "RGBA")
colimg.putalpha(to_L((inside & left).astype(np.float32)))
img.alpha_composite(colimg)

# reflet brillant sur la couleur
gl = Image.new("RGBA", (W, W), (0, 0, 0, 0))
gd = ImageDraw.Draw(gl)
gcx, gcy = CX - 128, CY - 150
gd.ellipse((px(gcx - 78), px(gcy - 40), px(gcx + 78), px(gcy + 40)), fill=(255, 255, 255, 120))
gl = gl.rotate(38, resample=Image.BICUBIC, center=(px(gcx), px(gcy)))
gl.putalpha(ImageChops.multiply(gl.split()[3], to_L((inside & left).astype(np.float32))))
img.alpha_composite(gl)

# ── moitié croquis : hachures d'ombre en croissant (lumière en haut à gauche) ──
inner = circle_mask(CX, CY, R - 14)
right_inner = inner & ~left


def crescent(shift):
    return inner & ~circle_mask(CX - shift, CY - shift, R)


def hatch(angle, spacing, width, area):
    lay = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(lay)
    diag = math.hypot(S, S)
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    k = -diag
    while k < diag:
        # droites perpendiculaires à la direction (c, s), espacées de `spacing`
        ox, oy = CX + k * -s, CY + k * c
        d.line((px(ox - c * diag), px(oy - s * diag), px(ox + c * diag), px(oy + s * diag)), fill=255, width=px(width))
        k += spacing
    lay = ImageChops.multiply(lay, to_L(area.astype(np.float32)))
    out = Image.new("RGBA", (W, W), INK)
    out.putalpha(lay)
    return out


img.alpha_composite(hatch(45, 31, 9, right_inner & crescent(100)))
img.alpha_composite(hatch(-45, 31, 9, right_inner & crescent(44)))

# ── traits noirs : coupure, contour ──
ln = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ld = ImageDraw.Draw(ln)
dx, dy = -math.sin(phi), math.cos(phi)          # direction de la coupure
ld.line((px(CX - dx * R), px(CY - dy * R), px(CX + dx * R), px(CY + dy * R)), fill=INK, width=px(14))
# petit trait de brillance, côté croquis
rr = R - 52
ld.arc((px(CX - rr), px(CY - rr), px(CX + rr), px(CY + rr)), start=-72, end=-34, fill=INK, width=px(11))
ln.putalpha(ImageChops.multiply(ln.split()[3], to_L(inside.astype(np.float32))))
img.alpha_composite(ln)
ol = Image.new("RGBA", (W, W), (0, 0, 0, 0))
od = ImageDraw.Draw(ol)
od.ellipse((px(CX - R), px(CY - R), px(CX + R), px(CY + R)), outline=INK, width=px(24))
img.alpha_composite(ol)

# ── étincelle (étoile à quatre branches) en haut à droite ──
def star(cx, cy, r, inner_r, fill, outline=None, ow=0):
    pts = []
    for i in range(8):
        a = math.radians(-90 + i * 45)
        rr = r if i % 2 == 0 else inner_r
        pts.append(P(cx + rr * math.cos(a), cy + rr * math.sin(a)))
    st = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    d.polygon(pts, fill=fill)
    if outline:
        d.line(pts + [pts[0]], fill=outline, width=px(ow), joint="curve")
    return st


img.alpha_composite(star(CX + SH + 178, CY - R + 8, 80, 22, INK))
img.alpha_composite(star(CX + SH + 178, CY - R + 8, 67, 17, PAPER))

# ── découpe dans le carré arrondi ──
out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
out.paste(img, (0, 0), sq)
out = out.resize((S, S), Image.LANCZOS)

# ── sorties : icon.icns, docs/icon.png ──
iset = os.path.join(HERE, "icon.iconset")
shutil.rmtree(iset, ignore_errors=True)
os.mkdir(iset)
for sz in (16, 32, 128, 256, 512):
    out.resize((sz, sz), Image.LANCZOS).save(f"{iset}/icon_{sz}x{sz}.png")
    out.resize((sz * 2, sz * 2), Image.LANCZOS).save(f"{iset}/icon_{sz}x{sz}@2x.png")
subprocess.run(["iconutil", "-c", "icns", iset, "-o", os.path.join(HERE, "icon.icns")], check=True)
shutil.rmtree(iset)
os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
out.save(os.path.join(HERE, "docs", "icon.png"))
print("OK : icon.icns et docs/icon.png")
