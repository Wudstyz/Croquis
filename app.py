"""Croquis : transforme une image en dessin à colorier. Fenêtre native (pywebview) + petit serveur HTTP local."""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import engine
import sample

APP_NAME = "Croquis"
SUPPORT = os.environ.get("CROQUIS_SUPPORT") or os.path.expanduser("~/Library/Application Support/Croquis")
SETTINGS_FILE = os.path.join(SUPPORT, "settings.json")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".avif")
EXPORT_LIMIT = 4500          # côté long maximal d'un export (garde la mémoire raisonnable)
A4_PX = 3508                 # A4 à 300 dpi


class ApiError(Exception):
    pass


class Superseded(Exception):
    """Un calcul plus récent a été demandé : on abandonne celui-ci."""


# ──────────────────────────── document courant ────────────────────────────

class Doc:
    def __init__(self, rgb, name):
        self.rgb, self.name = rgb, name
        self.h, self.w = rgb.shape[:2]
        self._sources = {}

    def source(self, longest, keep=True):
        longest = int(min(max(longest, 64), 12000))
        if longest in self._sources:
            return self._sources[longest]
        src = engine.Source(engine.resize_rgb(self.rgb, longest) if longest != max(self.w, self.h) else self.rgb)
        if keep:
            if len(self._sources) >= 3:
                self._sources.pop(next(iter(self._sources)))
            self._sources[longest] = src
        return src


doc = None
doc_lock = threading.Lock()
render_lock = threading.Lock()
seq_lock = threading.Lock()
latest_seq = 0
active = 0                   # nombre de demandes de rendu en cours ou en attente


def load_path(path):
    """Ouvre une image ; les formats que Pillow ne lit pas (HEIC…) passent par l'outil `sips` de macOS."""
    try:
        return engine.load_rgb(path)
    except Exception as first:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".heic", ".heif", ".avif"):
            with tempfile.TemporaryDirectory() as t:
                out = os.path.join(t, "x.png")
                r = subprocess.run(["/usr/bin/sips", "-s", "format", "png", path, "--out", out],
                                   capture_output=True, timeout=60)
                if r.returncode == 0 and os.path.exists(out):
                    return engine.load_rgb(out)
        raise ApiError("Impossible de lire cette image (%s)." % type(first).__name__)


def set_doc(rgb, name):
    global doc
    with doc_lock:
        doc = Doc(rgb, name)
    return {"name": name, "w": doc.w, "h": doc.h}


def need_doc():
    if doc is None:
        raise ApiError("Aucune image ouverte.")
    return doc


# ──────────────────────────── réglages enregistrés ────────────────────────────

def load_saved():
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_saved(d):
    try:
        os.makedirs(SUPPORT, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass


# ──────────────────────────── routes ────────────────────────────

def png_bytes(im, level=1):
    b = io.BytesIO()
    im.save(b, "PNG", compress_level=level)
    return b.getvalue()


def do_render(body):
    """Calcule l'aperçu. Une demande est « périmée » seulement si une demande PLUS RÉCENTE est arrivée
    pendant qu'elle attendait ; sans demande en attente, on repart toujours du numéro reçu."""
    global latest_seq, active
    d = need_doc()
    seq = int(body.get("seq", 0))
    side = int(min(max(int(body.get("max", 1400)), 200), 4000))
    side = min(side, max(d.w, d.h))
    with seq_lock:
        latest_seq = seq if active == 0 else max(latest_seq, seq)
        active += 1
    try:
        with render_lock:
            if seq < latest_seq:
                raise Superseded()
            t0 = time.time()
            src = d.source(side)
            s = engine.merge_settings(body.get("settings"))
            try:
                ink = engine.render(src, s, cancel=lambda: seq < latest_seq)
            except engine.Cancelled:
                raise Superseded()
            im = engine.to_image(ink, s["output"]["transparent"], s["output"]["negative"])
            data = png_bytes(im)
            ms = int((time.time() - t0) * 1000)
    finally:
        with seq_lock:
            active -= 1
    return data, {"X-Ms": str(ms), "X-W": str(src.w), "X-H": str(src.h), "X-Seq": str(seq)}


def render_full(body):
    """Rendu pleine taille pour l'export / la copie."""
    d = need_doc()
    size = body.get("size", "original")
    s = engine.merge_settings(body.get("settings"))
    longest = min(max(d.w, d.h), EXPORT_LIMIT) if size == "original" else A4_PX
    with render_lock:
        src = d.source(longest, keep=False)
        ink = engine.render(src, s)
    return engine.to_image(ink, s["output"]["transparent"], s["output"]["negative"]), s


def do_export(body):
    path = str(body.get("path") or "")
    fmt = body.get("format", "png")
    if not os.path.isabs(path) or fmt not in ("png", "pdf"):
        raise ApiError("Chemin ou format invalide.")
    if not path.lower().endswith("." + fmt):
        path += "." + fmt
    im, s = render_full(body)
    if fmt == "png":
        engine.save_png(im, path)
    else:
        engine.save_pdf(im, path)
    return {"path": path, "w": im.width, "h": im.height}


def do_copy(body):
    im, _ = render_full(body)
    from AppKit import NSPasteboard, NSPasteboardTypePNG
    from Foundation import NSData
    data = png_bytes(im, 3)
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setData_forType_(NSData.dataWithBytes_length_(data, len(data)), NSPasteboardTypePNG)
    return {"ok": True}


def route(method, path, query, body, headers):
    if method == "GET" and path == "/api/state":
        saved = load_saved()
        return {"defaults": engine.DEFAULTS, "saved": saved,
                "doc": ({"name": doc.name, "w": doc.w, "h": doc.h} if doc else None)}
    if method == "POST" and path == "/api/settings":
        save_saved(body if isinstance(body, dict) else {})
        return {"ok": True}
    if method == "POST" and path == "/api/upload":
        name = unquote((query.get("name") or ["image"])[0])
        try:
            rgb = engine.load_rgb(body)
        except Exception:
            ext = os.path.splitext(name)[1].lower() or ".heic"
            with tempfile.TemporaryDirectory() as t:
                p = os.path.join(t, "in" + ext)
                with open(p, "wb") as f:
                    f.write(body)
                rgb = load_path(p)
        return set_doc(rgb, name)
    if method == "POST" and path == "/api/open":
        p = str(body.get("path") or "")
        if not os.path.isfile(p):
            raise ApiError("Fichier introuvable.")
        return set_doc(load_path(p), os.path.basename(p))
    if method == "POST" and path == "/api/sample":
        return set_doc(sample.make_sample(), "Exemple")
    if method == "POST" and path == "/api/export":
        return do_export(body)
    if method == "POST" and path == "/api/copy":
        return do_copy(body)
    if method == "POST" and path == "/api/reveal":
        p = str(body.get("path") or "")
        if os.path.exists(p):
            subprocess.Popen(["/usr/bin/open", "-R", p])
        return {"ok": True}
    raise ApiError("Route inconnue.")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype if ctype != "application/json" else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        u = urlparse(self.path)
        # Protection : seule la fenêtre de l'app peut parler à ce serveur (pas une page web quelconque).
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send(403, {"error": "interdit"})
        if method == "POST" and self.headers.get("X-Croquis") != "1":
            return self.send(403, {"error": "interdit"})
        try:
            if method == "GET" and u.path == "/":
                with open(os.path.join(BASE, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if method == "GET" and u.path == "/icon.png":
                for p in (os.path.join(BASE, "icon.png"), os.path.join(BASE, "docs", "icon.png")):
                    if os.path.exists(p):
                        with open(p, "rb") as f:
                            return self.send(200, f.read(), "image/png")
                return self.send(404, {"error": "absent"})
            if method == "GET" and u.path == "/api/original":
                d = need_doc()
                side = min(int(parse_qs(u.query).get("max", ["1400"])[0]), 4000, max(d.w, d.h))
                rgb = engine.resize_rgb(d.rgb, side)
                from PIL import Image
                b = io.BytesIO()
                Image.fromarray(rgb).save(b, "JPEG", quality=92)
                return self.send(200, b.getvalue(), "image/jpeg")
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            if method == "POST" and u.path == "/api/render":
                try:
                    data, hdr = do_render(json.loads(raw or b"{}"))
                except Superseded:
                    return self.send(204, b"")          # demande périmée : la page en a déjà envoyé une plus récente
                return self.send(200, data, "image/png", hdr)
            if method == "POST" and u.path == "/api/upload":
                body = raw
            else:
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    return self.send(400, {"error": "JSON invalide"})
            self.send(200, route(method, u.path, parse_qs(u.query), body, self.headers))
        except ApiError as e:
            self.send(400, {"error": str(e)})
        except (ValueError, TypeError) as e:
            self.send(400, {"error": "Requête invalide : %s" % e})
        except MemoryError:
            self.send(500, {"error": "Image trop grande pour la mémoire disponible."})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": "%s : %s" % (type(e).__name__, e)})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


# ──────────────────────────── fenêtre native ────────────────────────────

class Api:
    """Boîtes de dialogue natives, appelées depuis la page."""

    def _kind(self, which):
        import webview
        k = getattr(webview, "FileDialog", None)
        if k:
            return getattr(k, which)
        return {"OPEN": webview.OPEN_DIALOG, "SAVE": webview.SAVE_DIALOG}[which]

    def choose_image(self):
        import webview
        r = webview.windows[0].create_file_dialog(
            self._kind("OPEN"), directory=os.path.expanduser("~/Pictures"), allow_multiple=False,
            file_types=("Images (*.png;*.jpg;*.jpeg;*.heic;*.heif;*.tif;*.tiff;*.bmp;*.gif;*.webp)",))
        if not r:
            return None
        return r if isinstance(r, str) else r[0]

    def choose_save(self, name, ext):
        import webview
        r = webview.windows[0].create_file_dialog(
            self._kind("SAVE"), directory=os.path.expanduser("~/Documents"), save_filename=name)
        if not r:
            return None
        path = r if isinstance(r, str) else r[0]
        if not path.lower().endswith("." + ext):
            path += "." + ext
        return path


def set_mac_identity():
    try:
        from AppKit import NSAppearance, NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = APP_NAME
        app = NSApplication.sharedApplication()
        app.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))     # thème clair uniquement
        icon = os.path.join(BASE, "icon.icns")
        if os.path.exists(icon):
            app.setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(icon))
    except Exception:
        pass


def main():
    port = 0
    server_only = "--server" in sys.argv
    if server_only:
        i = sys.argv.index("--server")
        port = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 8766
    # Pour les essais : CROQUIS_OPEN=sample (ou un chemin d'image) ouvre une image dès le lancement.
    first = os.environ.get("CROQUIS_OPEN")
    if first:
        try:
            set_doc(sample.make_sample(), "Exemple") if first == "sample" else set_doc(load_path(first), os.path.basename(first))
        except Exception as e:
            print("CROQUIS_OPEN ignoré :", e, file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % srv.server_port
    if server_only:
        print("Croquis — serveur :", url, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    import webview
    set_mac_identity()
    webview.create_window(APP_NAME, url, js_api=Api(), width=1380, height=880, min_size=(1040, 700),
                          background_color="#FFFBEF")
    webview.start(set_mac_identity)
    os._exit(0)


if __name__ == "__main__":
    main()
