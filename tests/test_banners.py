import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_dashboard as builder


class BannerDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.songs = self.root/'Songs'
        self.songs.mkdir()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_native_banner_cache_is_found(self):
        (self.root/'Banner').mkdir()
        self.assertEqual(builder.resolve_banners_dir(str(self.songs)), str(self.root/'Banner'))

    def test_legacy_staged_cache_still_works(self):
        (self.root/'Banners').mkdir()
        self.assertEqual(builder.resolve_banners_dir(str(self.songs)), str(self.root/'Banners'))

    def test_native_cache_has_priority(self):
        (self.root/'Banner').mkdir()
        (self.root/'Banners').mkdir()
        self.assertEqual(builder.resolve_banners_dir(str(self.songs)), str(self.root/'Banner'))

    def test_explicit_override_is_respected(self):
        (self.root/'Banner').mkdir()
        os.environ['SM_BANNERS'] = str(self.root/'custom')
        self.assertEqual(builder.resolve_banners_dir(str(self.songs)), str(self.root/'custom'))

    def test_missing_cache_is_empty(self):
        self.assertEqual(builder.resolve_banners_dir(str(self.songs)), '')


if __name__ == '__main__':
    unittest.main()
