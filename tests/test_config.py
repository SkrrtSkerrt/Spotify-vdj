import json
import tempfile
import unittest
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def test_load_and_save_preserve_max_concurrent_downloads(self):
        cfg = dict(config.DEFAULTS)
        cfg["max_concurrent_downloads"] = 4
        cfg["watch_output_folder"] = False
        cfg["watch_interval_seconds"] = 45

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = f"{tmpdir}/config.json"
            with patch.object(config, "CONFIG_FILE", cfg_file):
                config.save(cfg)
                loaded = config.load()

            self.assertEqual(loaded["max_concurrent_downloads"], 4)
            self.assertFalse(loaded["watch_output_folder"])
            self.assertEqual(loaded["watch_interval_seconds"], 45)
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["max_concurrent_downloads"], 4)


if __name__ == "__main__":
    unittest.main()
