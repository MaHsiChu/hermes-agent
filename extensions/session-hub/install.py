"""Install the checkout's Session Hub into an explicitly selected Hermes home."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parent


def install(home: Path) -> None:
    home = home.expanduser().resolve()
    if not (ROOT / 'settings.json').is_file():
        raise SystemExit('Copy settings.example.json to settings.json and configure local paths first.')
    config_path = home / 'config.yaml'
    cfg = yaml.safe_load(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError('Hermes config.yaml must contain a mapping')
    # Compile before changing an installed plugin or its configuration.
    subprocess.run(['node', str(ROOT / 'build-ui.mjs')], check=True, cwd=ROOT)
    home.mkdir(parents=True, exist_ok=True)
    backup = home / 'config.before-session-hub.yaml'
    if config_path.exists() and not backup.exists():
        shutil.copy2(config_path, backup)
    target = home / 'plugins/session-hub'
    shutil.copytree(ROOT / 'plugin', target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'extension-root.txt'))
    (target / 'extension-root.txt').write_text(str(ROOT), encoding='utf-8')
    desktop = home / 'desktop-plugins/session-hub'
    desktop.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'build/plugin.js', desktop / 'plugin.js')
    plugins = cfg.setdefault('plugins', {})
    enabled = plugins.setdefault('enabled', [])
    if 'session-hub' not in enabled:
        enabled.append('session-hub')
    plugins['disabled'] = [p for p in plugins.get('disabled', []) if p != 'session-hub']
    cfg.setdefault('mcp_servers', {})['session-hub'] = {
        'command': sys.executable, 'args': [str(ROOT / 'mcp_server.py')],
        'timeout': 90, 'connect_timeout': 40,
    }
    config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('Installed Session Hub into', home)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-home', type=Path, required=True,
                        help='Explicit target profile; test with a fresh directory first.')
    install(parser.parse_args().hermes_home)
