from pathlib import Path
import tempfile
import unittest

from sdr_cli import media


class MediaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.sdr/media').mkdir(parents=True)
        (self.root / '.sdr/media/clip.mp4').write_bytes(b'mp4')
        (self.root / '.sdr/media/clip.WEBM').write_bytes(b'webm')

    def test_name_ok(self):
        for name in ('clip.mp4', 'Riding_on_a_Sounding_Rocket.webm', 'a-b.c.m4v', 'X.MP4'):
            self.assertTrue(media.name_ok(name), name)
        for name in ('', '.mp4', '..mp4', '../x.mp4', 'a/b.mp4', 'a\\b.mp4', 'clip.mov', 'clip', 'clip.mp4\x00',
                     'a' * 97 + '.mp4', None, 5, ' clip.mp4', 'cl ip.mp4', 'é.mp4'):
            self.assertFalse(media.name_ok(name), repr(name))
        self.assertTrue(media.name_ok('a' * 96 + '.mp4'))

    def test_media_path(self):
        self.assertEqual(media.media_path(self.root, 'clip.mp4'), self.root / '.sdr/media/clip.mp4')
        self.assertEqual(media.media_path(self.root, 'clip.WEBM'), self.root / '.sdr/media/clip.WEBM')
        self.assertIsNone(media.media_path(self.root, 'missing.mp4'))
        with self.assertRaises(ValueError):
            media.media_path(self.root, '../secret.mp4')

    def test_content_type(self):
        self.assertEqual(media.content_type('a.mp4'), 'video/mp4')
        self.assertEqual(media.content_type('a.M4V'), 'video/mp4')
        self.assertEqual(media.content_type('a.WebM'), 'video/webm')

    def test_directory_is_not_a_file(self):
        (self.root / '.sdr/media/dir.mp4').mkdir()
        self.assertIsNone(media.media_path(self.root, 'dir.mp4'))


if __name__ == '__main__':
    unittest.main()
