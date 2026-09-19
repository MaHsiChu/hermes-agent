"""Exercise real bundle/copy/config installation in two isolated profiles."""
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

from install import ROOT, install


class InstallationContracts(unittest.TestCase):
    def test_profile_installation_preserves_configuration_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / 'a', root / 'b'
            a.mkdir()
            original = 'model: preserved-model\nplugins:\n  enabled: [other]\n  disabled: [session-hub, another]\n'
            (a / 'config.yaml').write_text(original, encoding='utf-8')
            install(a)
            install(b)
            install(a)
            cfg = yaml.safe_load((a / 'config.yaml').read_text(encoding='utf-8'))
            self.assertEqual(cfg['model'], 'preserved-model')
            self.assertEqual(cfg['plugins']['enabled'], ['other', 'session-hub'])
            self.assertEqual(cfg['plugins']['disabled'], ['another'])
            self.assertEqual((a / 'config.before-session-hub.yaml').read_text(encoding='utf-8'), original)
            for home in (a, b):
                config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8'))
                self.assertEqual(config['mcp_servers']['session-hub']['command'], sys.executable)
                self.assertEqual((home / 'plugins/session-hub/extension-root.txt').read_text(), str(ROOT))
                self.assertGreater((home / 'desktop-plugins/session-hub/plugin.js').stat().st_size, 100)
            self.assertNotIn('model', yaml.safe_load((b / 'config.yaml').read_text()))

    def test_invalid_config_is_rejected_without_installing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / 'config.yaml').write_text('- not-a-mapping\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                install(home)
            self.assertFalse((home / 'plugins').exists())
