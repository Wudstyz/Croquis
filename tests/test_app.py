"""Tests du serveur de Croquis (logique des demandes, sécurité de l'API)."""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import sample  # noqa: E402


class RenderSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.set_doc(sample.make_sample(), "Exemple")

    def test_old_sequence_number_is_accepted_when_nothing_is_pending(self):
        """Régression : un numéro énorme reçu une fois ne doit pas bloquer les demandes suivantes."""
        data, _ = app.do_render({"seq": 10 ** 13, "max": 300, "settings": {}})
        self.assertTrue(data.startswith(b"\x89PNG"))
        data, hdr = app.do_render({"seq": 5, "max": 300, "settings": {}})
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(hdr["X-Seq"], "5")

    def test_older_request_is_dropped_when_a_newer_one_is_waiting(self):
        app.latest_seq, app.active = 100, 1          # une demande plus récente (100) est déjà en attente
        try:
            with self.assertRaises(app.Superseded):
                app.do_render({"seq": 50, "max": 300, "settings": {}})
        finally:
            app.active = 0


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.set_doc(sample.make_sample(), "Exemple")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, path, body=None, headers=None, method=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read()
            finally:
                e.close()

    def test_post_without_app_header_is_refused(self):
        code, _ = self.call("/api/sample", {}, {"Content-Type": "application/json"})
        self.assertEqual(code, 403)

    def test_wrong_host_is_refused(self):
        code, _ = self.call("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_render_and_export_validation(self):
        h = {"X-Croquis": "1", "Content-Type": "application/json"}
        code, data = self.call("/api/render", {"seq": 1, "max": 300, "settings": {"shading": {"enabled": True}}}, h)
        self.assertEqual(code, 200)
        self.assertTrue(data.startswith(b"\x89PNG"))
        code, _ = self.call("/api/export", {"path": "relatif.png", "format": "png"}, h)
        self.assertEqual(code, 400)
        code, _ = self.call("/api/export", {"path": "/tmp/x.exe", "format": "exe"}, h)
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
