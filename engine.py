"""Moteur de Croquis : transforme une image (couleur ou non) en dessin à colorier.

Étapes (chacune est une option) :
  1. contours noirs (contours nets « DoG » ou effet crayon),
  2. nettoyage des petites taches,
  3. ombres en hachures (ou en points),
  4. aplats noirs pour les zones très sombres,
  5. fond blanc (ou transparent), éventuellement en négatif.

Les longueurs (épaisseur, espacement…) sont en « unités » : 1 unité = 1/1000 du plus grand côté
de l'image. L'aperçu (petite image) et l'export (grande image) ont donc exactement le même rendu.
"""
import io
import math
import os

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage as ndi

Image.MAX_IMAGE_PIXELS = 250_000_000

# ──────────────────────────── réglages ────────────────────────────

DEFAULTS = {
    "lines": {"enabled": True, "style": "contours", "detail": 55, "amount": 50, "smoothing": 35,
              "thickness": 1.2, "useColors": True},
    "shading": {"enabled": False, "style": "hatching", "amount": 55, "layers": 3, "spacing": 5.0,
                "lineWidth": 1.0, "angle": 45, "variableWidth": True, "smoothing": 40},
    "solid": {"enabled": False, "threshold": 18},
    "cleanup": {"enabled": True, "size": 30},
    "output": {"autoContrast": True, "transparent": False, "negative": False},
}

RANGES = {
    ("lines", "detail"): (0, 100), ("lines", "amount"): (0, 100), ("lines", "smoothing"): (0, 100),
    ("lines", "thickness"): (-2.0, 8.0),
    ("shading", "amount"): (0, 100), ("shading", "layers"): (1, 4), ("shading", "spacing"): (2.0, 16.0),
    ("shading", "lineWidth"): (0.3, 3.0), ("shading", "angle"): (0, 180), ("shading", "smoothing"): (0, 100),
    ("solid", "threshold"): (0, 100), ("cleanup", "size"): (0, 100),
}
CHOICES = {("lines", "style"): ("contours", "pencil"), ("shading", "style"): ("hatching", "dots")}


def merge_settings(given):
    """Complète et borne des réglages venus de l'interface (jamais d'erreur sur une valeur bizarre)."""
    out = {}
    given = given if isinstance(given, dict) else {}
    for sec, defaults in DEFAULTS.items():
        g = given.get(sec) if isinstance(given.get(sec), dict) else {}
        out[sec] = {}
        for key, dv in defaults.items():
            v = g.get(key, dv)
            if isinstance(dv, bool):
                v = bool(v)
            elif (sec, key) in CHOICES:
                v = v if v in CHOICES[(sec, key)] else dv
            else:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    v = float(dv)
                if not math.isfinite(v):
                    v = float(dv)
                lo, hi = RANGES[(sec, key)]
                v = min(max(v, lo), hi)
                if key == "layers":
                    v = int(round(v))
            out[sec][key] = v
    return out


# ──────────────────────────── outils image ────────────────────────────

def load_rgb(source, max_side=6000):
    """Ouvre un fichier (chemin) ou des octets → tableau RGB uint8, fond transparent aplati sur blanc."""
    im = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    elif im.mode in ("I;16", "I", "F"):
        a = np.asarray(im, dtype=np.float32)
        a = (a - a.min()) / max(float(a.max() - a.min()), 1e-6)
        im = Image.fromarray((a * 255).astype(np.uint8), "L")
    im = im.convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    return np.asarray(im, dtype=np.uint8)


def resize_rgb(rgb, longest):
    h, w = rgb.shape[:2]
    if longest <= 0 or max(h, w) == longest:
        return rgb
    s = longest / max(h, w)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return np.asarray(Image.fromarray(rgb).resize(size, Image.LANCZOS), dtype=np.uint8)


class Cancelled(Exception):
    pass


class Source:
    """Une image prête à être traitée, avec un cache des calculs coûteux (flous…)."""

    def __init__(self, rgb):
        self.h, self.w = rgb.shape[:2]
        self.rgb = rgb.astype(np.float32) / 255.0
        r, g, b = self.rgb[..., 0], self.rgb[..., 1], self.rgb[..., 2]
        self.gray = (0.2126 * r + 0.7152 * g + 0.0722 * b).astype(np.float32)
        self.unit = max(self.h, self.w) / 1000.0
        self._cache = {}
        self._grid = None

    def memo(self, key, fn):
        if key not in self._cache:
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = fn()
        return self._cache[key]

    def grid(self):
        if self._grid is None:
            yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
            self._grid = (xx + 0.5, yy + 0.5)
        return self._grid


# ──────────────────────────── filtres ────────────────────────────

def _box_sizes(sigma, n=3):
    ideal = math.sqrt(12 * sigma * sigma / n + 1)
    wl = int(math.floor(ideal))
    if wl % 2 == 0:
        wl -= 1
    wu = wl + 2
    m = round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4))
    return [wl if i < m else wu for i in range(n)]


def gauss(a, sigma):
    """Flou gaussien rapide : exact pour les petits rayons, 3 flous « boîte » pour les grands."""
    if sigma < 0.35:
        return a
    if sigma <= 2.2:
        return ndi.gaussian_filter(a, sigma, mode="nearest", truncate=3.0)
    out = a
    for size in _box_sizes(sigma):
        if size > 1:
            out = ndi.uniform_filter(out, size=size, mode="nearest")
    return out


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def remove_small(ink, min_area):
    """Efface les taches noires plus petites que `min_area` pixels."""
    if min_area < 2:
        return ink
    m = ink > 0.5
    if not m.any():
        return ink
    lab, n = ndi.label(m, structure=np.ones((3, 3), dtype=bool))
    areas = np.bincount(lab.ravel(), minlength=n + 1)
    small = areas < min_area
    small[0] = False
    if not small.any():
        return ink
    kill = small[lab]
    kept = m & ~kill
    kill = ndi.binary_dilation(kill, structure=np.ones((3, 3), dtype=bool)) & ~kept
    return np.where(kill, np.float32(0), ink)


def thicken(ink, t):
    """Épaissit (t > 0) ou amincit (t < 0) les traits de t pixels, bords lissés."""
    if abs(t) < 0.05:
        return ink
    m = ink > 0.5
    if not m.any():
        return ink
    if t > 0:
        d = ndi.distance_transform_edt(~m).astype(np.float32)
        return np.maximum(ink, np.clip(t + 0.5 - d, 0, 1)).astype(np.float32)
    d = ndi.distance_transform_edt(m).astype(np.float32)
    return np.where(m, np.clip(d + t + 0.5, 0, 1), 0).astype(np.float32)


# ──────────────────────────── étapes ────────────────────────────

def _levels(src, auto):
    if not auto:
        return 0.0, 1.0

    def calc():
        lo, hi = np.percentile(src.gray[::3, ::3], [1, 99])
        return (float(lo), float(hi)) if hi - lo >= 0.08 else (0.0, 1.0)
    return src.memo(("levels",), calc)


def _stretch(a, lo, hi):
    return a if (lo, hi) == (0.0, 1.0) else np.clip((a - lo) / (hi - lo), 0, 1).astype(np.float32)


def _gray(src, auto):
    lo, hi = _levels(src, auto)
    return src.memo(("gray", auto), lambda: _stretch(src.gray, lo, hi))


def _contour_dog(src, L, auto):
    """Différence de gaussiennes : négatif sur le côté sombre d'un contour."""
    u = src.unit
    sigma = 0.65 * (4.5 / 0.65) ** (1 - L["detail"] / 100) * u
    pre = L["smoothing"] / 100 * 2.0 * u
    key = ("dog", auto, L["useColors"], round(sigma, 3), round(pre, 3))

    def calc():
        lo, hi = _levels(src, auto)
        planes = [_stretch(src.rgb[..., i], lo, hi) for i in range(3)] if L["useColors"] else [_gray(src, auto)]
        dmin = None
        for p in planes:
            base = gauss(p, pre) if pre > 0.3 else p
            d = gauss(base, sigma) - gauss(base, sigma * 1.6)
            dmin = d if dmin is None else np.minimum(dmin, d)
        return dmin.astype(np.float32)
    return src.memo(key, calc)


def lines_ink(src, L, auto):
    u = src.unit
    if L["style"] == "pencil":
        sigma = 1.0 * (10.0 / 1.0) ** (1 - L["detail"] / 100) * u
        pre = L["smoothing"] / 100 * 2.0 * u
        key = ("pencil", auto, round(sigma, 3), round(pre, 3))

        def calc():
            g = _gray(src, auto)
            g = gauss(g, pre) if pre > 0.3 else g
            b = gauss(1.0 - g, sigma)
            res = np.minimum(1.0, g / np.maximum(1.0 - b, 0.03))
            return (1.0 - res).astype(np.float32)
        ink = src.memo(key, calc)
        gain = 2.0 + L["amount"] / 100 * 10.0
        return np.clip(ink * gain, 0, 1).astype(np.float32)
    dog = _contour_dog(src, L, auto)
    thr = 0.06 * (0.004 / 0.06) ** (L["amount"] / 100)
    soft = thr * 0.35
    return smoothstep(-thr + soft, -thr - soft, dog)


def hatch_ink(src, tone, S):
    u = src.unit
    xx, yy = src.grid()
    sp = S["spacing"] * u
    lw = S["lineWidth"] * u
    top = 0.2 + 0.7 * S["amount"] / 100          # en dessous de cette clarté, on ombre
    out = np.zeros((src.h, src.w), np.float32)
    if S["style"] == "dots":
        dark = np.clip((top - tone) / top, 0, 1)
        th = math.radians(S["angle"])
        c, s = math.cos(th), math.sin(th)
        a = (xx * c + yy * s) / sp
        b = (-xx * s + yy * c) / sp
        fa, fb = a - np.floor(a) - 0.5, b - np.floor(b) - 0.5
        dist = np.sqrt(fa * fa + fb * fb) * sp
        radius = np.sqrt(dark * 0.85 / math.pi) * sp
        return np.where(dark > 0.02, np.clip(radius - dist + 0.5, 0, 1), 0).astype(np.float32)
    offsets = [0, 90, -45, 45]
    n = int(S["layers"])
    for i in range(n):
        T = top - (top - 0.06) * i / n
        active = tone < T
        if not active.any():
            break
        th = math.radians(S["angle"] + offsets[i])
        pos = (xx * math.cos(th) + yy * math.sin(th)) / sp
        f = pos - np.floor(pos)
        dist = np.minimum(f, 1 - f) * sp
        if S["variableWidth"]:
            depth = np.clip((T - tone) / 0.18, 0, 1)
            half = 0.5 * lw * (0.35 + 0.65 * depth) * 1.25
        else:
            half = 0.5 * lw
        cov = np.clip(half - dist + 0.5, 0, 1)
        out = np.maximum(out, np.where(active, cov, 0).astype(np.float32))
    return out


# ──────────────────────────── rendu complet ────────────────────────────

def render(src, settings, cancel=None):
    """Retourne l'« encre » (0 = papier, 1 = noir) sous forme d'un tableau float32 (h, w)."""
    s = merge_settings(settings)
    auto = s["output"]["autoContrast"]
    u = src.unit

    def check():
        if cancel is not None and cancel():
            raise Cancelled()

    ink = np.zeros((src.h, src.w), np.float32)
    min_area = 0.0
    if s["cleanup"]["enabled"]:
        min_area = (s["cleanup"]["size"] / 100) ** 2 * 600 * u * u

    if s["lines"]["enabled"]:
        L = lines_ink(src, s["lines"], auto)
        check()
        L = remove_small(L, min_area)
        check()
        ink = thicken(L, s["lines"]["thickness"] * u)
        check()

    if s["shading"]["enabled"]:
        S = s["shading"]
        sig = (0.5 + 3.5 * S["smoothing"] / 100) * u
        tone = src.memo(("tone", auto, round(sig, 3)), lambda: gauss(_gray(src, auto), sig))
        ink = np.maximum(ink, hatch_ink(src, tone, S))
        check()

    if s["solid"]["enabled"]:
        t2 = src.memo(("tone-solid", auto), lambda: gauss(_gray(src, auto), 1.2 * u))
        thr = 0.02 + 0.38 * s["solid"]["threshold"] / 100
        solid = smoothstep(thr + 0.03, thr - 0.03, t2)
        solid = remove_small(solid, min_area)
        ink = np.maximum(ink, solid)
        check()
    return ink


def to_image(ink, transparent=False, negative=False):
    """Encre → image Pillow : niveaux de gris (fond blanc) ou RGBA (fond transparent)."""
    v = np.clip(ink, 0, 1)
    if transparent:
        rgba = np.zeros(v.shape + (4,), np.uint8)
        if negative:
            rgba[..., :3] = 255
        rgba[..., 3] = (v * 255 + 0.5).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")
    g = v if negative else 1.0 - v
    return Image.fromarray((g * 255 + 0.5).astype(np.uint8), "L")


# ──────────────────────────── export ────────────────────────────

def save_png(im, path, dpi=300):
    im.save(path, "PNG", dpi=(dpi, dpi), optimize=False)


def save_pdf(im, path, margin_mm=10):
    """PDF A4 (portrait ou paysage selon l'image), image centrée avec marges, prête à imprimer."""
    dpi = 300
    long_px, short_px = round(297 / 25.4 * dpi), round(210 / 25.4 * dpi)
    landscape = im.width > im.height
    pw, ph = (long_px, short_px) if landscape else (short_px, long_px)
    m = round(margin_mm / 25.4 * dpi)
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    box = (pw - 2 * m, ph - 2 * m)
    s = min(box[0] / im.width, box[1] / im.height)
    fit = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    page = Image.new(im.mode if im.mode in ("L", "RGB") else "RGB", (pw, ph), 255 if im.mode == "L" else (255, 255, 255))
    page.paste(fit, ((pw - fit.width) // 2, (ph - fit.height) // 2))
    page.save(path, "PDF", resolution=dpi)
