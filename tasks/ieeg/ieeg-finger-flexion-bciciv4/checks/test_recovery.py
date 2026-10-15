"""Normal recovery checks with small local bytes, never benchmark recordings."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest


TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "env"))
from export_bci import publish_export  # noqa: E402
from prepare import CACHE_ROOT, fetch_archive  # noqa: E402


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A clean CI checkout has no ignored source cache yet.
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    def test_export_publishes_only_complete_directory(self):
        with tempfile.TemporaryDirectory(prefix="bpb-bci-export-check-") as temporary:
            parent = Path(temporary)
            target = parent / "derived"

            def interrupted(stage):
                (stage / "public").mkdir()
                (stage / "public" / "incomplete.bin").write_bytes(b"partial local fixture")
                raise ValueError("fixture interrupted after its first output")

            with self.assertRaisesRegex(ValueError, "fixture interrupted"):
                publish_export(target, interrupted)
            self.assertFalse(target.exists())
            self.assertEqual(list(parent.iterdir()), [])

            def complete(stage):
                (stage / "public").mkdir()
                (stage / "public" / "complete.bin").write_bytes(b"complete local fixture")
                return ("train", "valid")

            self.assertEqual(publish_export(target, complete), ("train", "valid"))
            self.assertEqual((target / "public" / "complete.bin").read_bytes(), b"complete local fixture")
            with self.assertRaises(FileExistsError):
                publish_export(target, complete)

    def test_interrupted_http_transfer_resumes_exact_range(self):
        payload = bytes(range(256)) * 257
        etag = '"local-byte-fixture-v1"'
        requests = []

        class Source(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_GET(self):
                offset = len(payload) // 3
                requests.append((self.headers.get("Range"), self.headers.get("If-Match")))
                if len(requests) == 1:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("ETag", etag)
                    self.end_headers()
                    self.wfile.write(payload[:offset])
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    self.send_response(206)
                    self.send_header("Content-Length", str(len(payload) - offset))
                    self.send_header("Content-Range", f"bytes {offset}-{len(payload) - 1}/{len(payload)}")
                    self.send_header("ETag", etag)
                    self.end_headers()
                    self.wfile.write(payload[offset:])

        server = ThreadingHTTPServer(("127.0.0.1", 0), Source)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="bpb-bci-transfer-", dir=CACHE_ROOT) as temporary:
                archive = Path(temporary) / "small-source.zip"
                url = f"http://127.0.0.1:{server.server_port}/small-source.zip"
                options = {"url": url, "expected_bytes": len(payload),
                           "expected_sha256": hashlib.sha256(payload).hexdigest(), "chunk_bytes": 1024}
                with self.assertRaisesRegex(ValueError, "ended before"):
                    fetch_archive(archive, **options)
                partial = archive.with_suffix(".zip.partial")
                receipt = archive.with_suffix(".zip.partial.json")
                self.assertTrue(partial.is_file() and receipt.is_file())
                self.assertFalse(archive.exists())
                offset = partial.stat().st_size
                self.assertEqual(offset, len(payload) // 3)
                fetch_archive(archive, **options)
                self.assertEqual(archive.read_bytes(), payload)
                self.assertFalse(partial.exists())
                self.assertEqual(requests, [(None, None),
                                            (f"bytes={offset}-{len(payload) - 1}", etag)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_wrong_complete_source_preserves_partial(self):
        delivered = b"changed source bytes"
        expected = b"pinned source bytes!"

        class Changed(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(delivered)))
                self.end_headers()
                self.wfile.write(delivered)

        self.assertEqual(len(delivered), len(expected))
        server = ThreadingHTTPServer(("127.0.0.1", 0), Changed)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="bpb-bci-changed-", dir=CACHE_ROOT) as temporary:
                archive = Path(temporary) / "small-source.zip"
                options = {"url": f"http://127.0.0.1:{server.server_port}/small-source.zip",
                           "expected_bytes": len(expected),
                           "expected_sha256": hashlib.sha256(expected).hexdigest()}
                with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                    fetch_archive(archive, **options)
                self.assertFalse(archive.exists())
                self.assertTrue(archive.with_suffix(".zip.partial").is_file())
                with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                    fetch_archive(archive, **options)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_changed_etag_refuses_resume(self):
        payload = b"pinned local source" * 1024
        cut = len(payload) // 4
        requests = []

        class ChangedEtag(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_GET(self):
                requests.append(self.headers.get("Range"))
                if len(requests) == 1:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("ETag", '"version-one"')
                    self.end_headers()
                    self.wfile.write(payload[:cut])
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    self.send_response(206)
                    self.send_header("Content-Length", str(len(payload) - cut))
                    self.send_header("Content-Range", f"bytes {cut}-{len(payload) - 1}/{len(payload)}")
                    self.send_header("ETag", '"version-two"')
                    self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), ChangedEtag)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="bpb-bci-etag-", dir=CACHE_ROOT) as temporary:
                archive = Path(temporary) / "small-source.zip"
                options = {"url": f"http://127.0.0.1:{server.server_port}/small-source.zip",
                           "expected_bytes": len(payload),
                           "expected_sha256": hashlib.sha256(payload).hexdigest(),
                           "chunk_bytes": 1024}
                with self.assertRaisesRegex(ValueError, "ended before"):
                    fetch_archive(archive, **options)
                with self.assertRaisesRegex(ValueError, "ETag changed"):
                    fetch_archive(archive, **options)
                self.assertFalse(archive.exists())
                self.assertEqual(archive.with_suffix(".zip.partial").stat().st_size, cut)
                self.assertEqual(requests, [None, f"bytes={cut}-{len(payload) - 1}"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
