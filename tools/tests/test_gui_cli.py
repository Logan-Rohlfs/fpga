# tools/tests/test_gui_cli.py
from pathlib import Path
import tempfile
import unittest

from sdr_cli import cli, core, roles


class GuiCliTest(unittest.TestCase):
    def test_gui_arguments(self):
        args = cli.parser().parse_args(['gui', '--source', 'sim', '--lan', '--http-port', '9000', '--no-browser'])
        self.assertEqual((args.command, args.source, args.lan, args.http_port, args.no_browser),
                         ('gui', 'sim', True, 9000, True))
        defaults = cli.parser().parse_args(['gui'])
        self.assertEqual((defaults.source, defaults.lan, defaults.http_port, defaults.speed), ('serial', False, 8080, 1.0))

    def test_password_prompt(self):
        answers = iter(['correct horse', 'correct horse'])
        stored = cli.prompt_gui_password(read=lambda prompt: next(answers), interactive=True)
        self.assertTrue(roles.verify_password('correct horse', stored))
        mismatch = iter(['correct horse', 'wrong horse'])
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: next(mismatch), interactive=True)
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: 'short', interactive=True)
        with self.assertRaises(core.ToolError):
            cli.prompt_gui_password(read=lambda prompt: 'x', interactive=False)

    def test_hash_is_saved_and_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = dict(core.DEFAULTS, gui_admin_hash=roles.hash_password('pw', iterations=1000))
            core.save_config(root, config)
            loaded = core.load_config(root)
            self.assertEqual(loaded['gui_admin_hash'], config['gui_admin_hash'])
            self.assertEqual(cli.public_config(loaded)['gui_admin_hash'], '(set)')
            self.assertEqual(cli.public_config(core.DEFAULTS)['gui_admin_hash'], '')
