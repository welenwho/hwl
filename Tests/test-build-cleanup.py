#!/usr/bin/env python3
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildCleanupTests(unittest.TestCase):
    def test_package_fetches_are_unique_and_use_current_packages(self):
        script = (ROOT / 'Scripts/Packages.sh').read_text()
        calls = [shlex.split(line) for line in script.splitlines() if line.startswith('UPDATE_PACKAGE "')]
        self.assertEqual(len(calls), len({tuple(call) for call in calls}))
        own = [call for call in calls if call[2] == 'welenwho/packages']
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0][5].split(), ['gecoosac', 'sing-box', 'luci-app-sbproxy', 'luci-app-wolultra'])
        self.assertIn('UPDATE_VERSION()', script)
        self.assertIn('Scripts/PRIVATE.sh', script)

    def test_configs_keep_current_proxy_and_wake_plugins(self):
        for name in ('GENERAL', 'TEST'):
            config = (ROOT / 'Config' / (name + '.txt')).read_text()
            self.assertIn('CONFIG_PACKAGE_luci-app-sbproxy=y', config)
            self.assertIn('CONFIG_PACKAGE_luci-app-wolultra=y', config)
            self.assertNotIn('CONFIG_PACKAGE_kmod-nft-tproxy=', config)
            for dependency in ('kmod-tun', 'kmod-nft-queue', 'kmod-nft-bridge', 'ip-full'):
                self.assertIn('CONFIG_PACKAGE_' + dependency + '=y', config)

    def test_handlers_preserve_unrelated_feed_and_keep_rust_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'wrt/package').mkdir(parents=True)
            vpn = base / 'wrt/feeds/packages/net/tailscale/Makefile'
            vpn.parent.mkdir(parents=True)
            original = 'PKG_VERSION:=1.102.2\nPKG_RELEASE:=1\ncopy ./files\n'
            vpn.write_text(original)
            rust = base / 'wrt/feeds/packages/lang/rust/Makefile'
            rust.parent.mkdir(parents=True)
            rust.write_text('ci-llvm=true\n')
            # Portable GNU sed -i stand-in for this one rule on macOS too.
            bins = base / 'bin'
            bins.mkdir()
            sed = bins / 'sed'
            sed.write_text('''#!/usr/bin/env python3
from pathlib import Path
import sys
assert sys.argv[1:3] == ['-i', 's/ci-llvm=true/ci-llvm=false/g']
p = Path(sys.argv[3])
p.write_text(p.read_text().replace('ci-llvm=true', 'ci-llvm=false'))
''')
            sed.chmod(0o755)
            env = dict(os.environ, GITHUB_WORKSPACE=tmp, PATH=str(bins) + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(ROOT / 'Scripts/Handles.sh')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(vpn.read_text(), original)
            self.assertFalse((vpn.parent / 'patches').exists())
            self.assertEqual(rust.read_text(), 'ci-llvm=false\n')
            self.assertIn('rust has been fixed', result.stdout)


if __name__ == '__main__': unittest.main()
