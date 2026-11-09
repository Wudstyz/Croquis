"""Tests du moteur de Croquis. Lancer : python -m unittest discover -s tests -v"""
import copy
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402
import sample  # noqa: E402


def settings(**sections):
    s = copy.deepcopy(engine.DEFAULTS)
    for k, v in sections.items():
        s[k].update(v)
    return s


def disc_image(n=600, r=180, bg=255, fg=20):
    yy, xx = np.mgrid[0:n, 0:n]
    img = np.full((n, n, 3), bg, np.uint8)
    img[(xx - n // 2) ** 2 + (yy - n // 2) ** 2 <= r * r] = fg
    return img


class EngineTests(unittest.TestCase):
    def test_blank_image_gives_blank_page(self):
        src = engine.Source(np.full((400, 500, 3), 255, np.uint8))
        for s in (settings(), settings(shading={"enabled": True}), settings(solid={"enabled": True})):
            ink = engine.render(src, s)
            self.assertLess(float(ink.max()), 0.01)

    def test_disc_gets_an_outline_and_nothing_else(self):
        n, r = 600, 180
        src = engine.Source(disc_image(n, r))
        ink = engine.render(src, settings(lines={"thickness": 0}, cleanup={"enabled": False}))
        yy, xx = np.mgrid[0:n, 0:n]
        d = np.sqrt((xx - n // 2) ** 2 + (yy - n // 2) ** 2)
        ring = (np.abs(d - r) < 8)
        # le contour doit être fermé : dans chaque tranche d'angle de 3°, on trouve du trait dans la bande
        ang = (np.degrees(np.arctan2(yy - n // 2, xx - n // 2)) + 180) // 3
        for a in range(120):
            self.assertGreater(float(ink[ring & (ang == a)].max()), 0.5, f"contour interrompu vers {a * 3}°")
        self.assertLess(float(ink[d < r - 30].max()), 0.05, "l'intérieur plat reste blanc")
        self.assertLess(float(ink[d > r + 30].max()), 0.05, "le fond plat reste blanc")

    def test_cleanup_removes_specks_but_keeps_shapes(self):
        img = disc_image()
        img[40:46, 40:46] = 0                      # une petite tache isolée
        src = engine.Source(img)
        with_cleanup = engine.render(src, settings(cleanup={"enabled": True, "size": 60}, lines={"detail": 90}))
        without = engine.render(src, settings(cleanup={"enabled": False}, lines={"detail": 90}))
        self.assertGreater(float(without[36:50, 36:50].max()), 0.5)
        self.assertLess(float(with_cleanup[30:56, 30:56].max()), 0.05)
        self.assertGreater(float(with_cleanup[300 - 190:300 - 170, 300].max()), 0.5)   # le disque est gardé

    def test_thickness_changes_amount_of_ink(self):
        src = engine.Source(disc_image())
        thin = engine.render(src, settings(lines={"thickness": -1.0})).sum()
        base = engine.render(src, settings(lines={"thickness": 0.0})).sum()
        fat = engine.render(src, settings(lines={"thickness": 4.0})).sum()
        self.assertLess(thin, base)
        self.assertGreater(fat, base * 1.5)

    def test_hatching_only_in_shadows(self):
        n = 600
        grad = np.tile(np.linspace(0, 255, n, dtype=np.uint8), (n, 1))     # sombre à gauche, clair à droite
        src = engine.Source(np.dstack([grad] * 3))
        ink = engine.render(src, settings(lines={"enabled": False}, shading={"enabled": True, "amount": 55, "smoothing": 0}, output={"autoContrast": False}))
        self.assertGreater(float(ink[:, :150].mean()), 0.15)
        self.assertLess(float(ink[:, -150:].mean()), 0.01)

    def test_more_layers_means_more_ink_in_darkest_zone(self):
        n = 500
        src = engine.Source(np.full((n, n, 3), 25, np.uint8))
        a = engine.render(src, settings(lines={"enabled": False}, shading={"enabled": True, "layers": 1}, output={"autoContrast": False})).mean()
        b = engine.render(src, settings(lines={"enabled": False}, shading={"enabled": True, "layers": 4}, output={"autoContrast": False})).mean()
        self.assertGreater(b, a * 1.5)

    def test_solid_fills_very_dark_areas(self):
        img = np.full((400, 400, 3), 230, np.uint8)
        img[100:300, 100:300] = 5
        src = engine.Source(img)
        ink = engine.render(src, settings(lines={"enabled": False}, solid={"enabled": True, "threshold": 20}, output={"autoContrast": False}))
        self.assertGreater(float(ink[150:250, 150:250].min()), 0.95)
        self.assertLess(float(ink[:60, :60].max()), 0.01)

    def test_preview_and_full_size_look_the_same(self):
        rgb = sample.make_sample()
        s = settings(shading={"enabled": True})
        small = engine.render(engine.Source(engine.resize_rgb(rgb, 600)), s).mean()
        big = engine.render(engine.Source(engine.resize_rgb(rgb, 1200)), s).mean()
        self.assertLess(abs(small - big) / big, 0.2, f"quantité d'encre différente : {small:.3f} vs {big:.3f}")

    def test_bad_settings_never_crash(self):
        for bad in (None, 5, "x", {"lines": 3}, {"lines": {"detail": "abc", "thickness": 1e99, "style": "zzz"}},
                    {"shading": {"layers": 999, "spacing": -3, "enabled": "oui"}}, {"cleanup": {"size": float("nan")}}):
            m = engine.merge_settings(bad)
            for sec, d in engine.DEFAULTS.items():
                self.assertEqual(set(m[sec]), set(d))
            engine.render(engine.Source(disc_image(200, 60)), m)
        self.assertEqual(engine.merge_settings({"shading": {"layers": 999}})["shading"]["layers"], 4)

    def test_output_formats(self):
        src = engine.Source(disc_image(300, 90))
        ink = engine.render(src, settings())
        im = engine.to_image(ink)
        self.assertEqual(im.mode, "L")
        self.assertEqual(im.getpixel((2, 2)), 255)                       # fond blanc
        tr = engine.to_image(ink, transparent=True)
        self.assertEqual(tr.mode, "RGBA")
        self.assertEqual(tr.getpixel((2, 2))[3], 0)                      # fond transparent
        neg = engine.to_image(ink, negative=True)
        self.assertEqual(neg.getpixel((2, 2)), 0)                        # fond noir
        with tempfile.TemporaryDirectory() as t:
            engine.save_png(im, os.path.join(t, "a.png"))
            engine.save_pdf(im, os.path.join(t, "a.pdf"))
            with Image.open(os.path.join(t, "a.png")) as back:
                self.assertEqual(back.size, im.size)
            with open(os.path.join(t, "a.pdf"), "rb") as f:
                self.assertTrue(f.read(5) == b"%PDF-")

    def test_load_handles_transparency_and_orientation(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "t.png")
            Image.new("RGBA", (50, 30), (0, 0, 0, 0)).save(p)              # entièrement transparent
            rgb = engine.load_rgb(p)
            self.assertEqual(rgb.shape, (30, 50, 3))
            self.assertEqual(int(rgb.min()), 255)                          # aplati sur blanc


if __name__ == "__main__":
    unittest.main()
