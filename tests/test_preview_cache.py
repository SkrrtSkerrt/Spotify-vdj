import io
import os
import tempfile
import unittest
from unittest.mock import patch

import preview_cache


class PreviewCacheTests(unittest.TestCase):
    def test_download_preview_clip_writes_local_cache_file(self):
        payload = b"preview-bytes"
        fake_response = io.BytesIO(payload)
        fake_response.__enter__ = lambda self=fake_response: self
        fake_response.__exit__ = lambda *args: False

        with tempfile.TemporaryDirectory() as tmpdir, patch("preview_cache.urlopen", return_value=fake_response):
            path = preview_cache.download_preview_clip(
                "https://example.com/preview.mp3",
                cache_key="track-1",
                cache_dir=tmpdir,
            )

            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), payload)

    def test_download_preview_clip_redownloads_corrupt_cache_file(self):
        payload = b"fresh-preview-bytes"

        def make_response():
            response = io.BytesIO(payload)
            response.__enter__ = lambda self=response: self
            response.__exit__ = lambda *args: False
            return response

        with tempfile.TemporaryDirectory() as tmpdir, patch("preview_cache.urlopen", side_effect=lambda *args, **kwargs: make_response()):
            path = preview_cache.download_preview_clip(
                "https://example.com/preview.mp3",
                cache_key="track-1",
                cache_dir=tmpdir,
            )
            with open(path, "wb") as f:
                f.write(b"corrupt-data")
            refreshed = preview_cache.download_preview_clip(
                "https://example.com/preview.mp3",
                cache_key="track-1",
                cache_dir=tmpdir,
            )
            self.assertEqual(refreshed, path)
            with open(refreshed, "rb") as f:
                self.assertEqual(f.read(), payload)


if __name__ == "__main__":
    unittest.main()
