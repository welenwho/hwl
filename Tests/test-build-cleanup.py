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
        self.assertEqual(own[0][5].split(), ['sing-box', 'luci-app-sbproxy'])
        self.assertEqual(own[0][6], 'sbproxy')
        viking = next(call for call in calls if call[2] == 'VIKINGYFY/packages')
        self.assertNotIn('sing-box', viking[5].split())
        self.assertIn('retain_package_source "sing-box" "./package/sbproxy"', script)
        self.assertIn('UPDATE_VERSION()', script)
        self.assertIn('Scripts/PRIVATE.sh', script)

    def test_retain_drops_viking_and_feed_sing_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            owner = base / 'package/sbproxy/sing-box'
            owner.mkdir(parents=True)
            marker = 'https://github.com/welenwho/packages/releases/download/'
            (owner / 'Makefile').write_text('PKG_SOURCE_URL:=' + marker + 'sbproxy-core-v1.14.4\n')
            viking = base / 'package/packages/sing-box'
            viking.mkdir(parents=True)
            (viking / 'Makefile').write_text('PKG_SOURCE_URL:=https://codeload.github.com/SagerNet/sing-box\n')
            feed = base / 'feeds/packages/net/sing-box'
            feed.mkdir(parents=True)
            (feed / 'Makefile').write_text('PKG_SOURCE_URL:=https://codeload.github.com/SagerNet/sing-box\n')
            installed = base / 'package/feeds/packages'
            installed.mkdir(parents=True)
            (installed / 'sing-box').symlink_to(feed)
            env = dict(os.environ, PACKAGES_SH_SOURCE_ONLY='1')
            command = 'source "%s"\nretain_package_source sing-box ./package/sbproxy "%s"\n' % (ROOT / 'Scripts/Packages.sh', marker)
            result = subprocess.run(['bash', '-c', command], cwd=tmp, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((owner / 'Makefile').is_file())
            self.assertFalse(viking.exists())
            self.assertFalse(feed.exists())
            self.assertFalse((installed / 'sing-box').exists())
            self.assertIn('Using sing-box from', result.stdout)

    def test_configs_keep_current_proxy_and_wake_plugins(self):
        for name in ('GENERAL', 'TEST'):
            config = (ROOT / 'Config' / (name + '.txt')).read_text()
            self.assertIn('CONFIG_PACKAGE_luci-app-sbproxy=y', config)
            self.assertIn('CONFIG_PACKAGE_luci-app-wolultra=y', config)
            self.assertNotIn('CONFIG_PACKAGE_kmod-nft-tproxy=', config)
            for dependency in ('kmod-tun', 'kmod-nft-queue', 'kmod-nft-bridge', 'ip-full'):
                self.assertIn('CONFIG_PACKAGE_' + dependency + '=y', config)

    def test_handlers_leave_unrelated_feeds_and_rust_makefile(self):
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
            env = dict(os.environ, GITHUB_WORKSPACE=tmp)
            result = subprocess.run(['bash', str(ROOT / 'Scripts/Handles.sh')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(vpn.read_text(), original)
            self.assertFalse((vpn.parent / 'patches').exists())
            # Rust host build is owned by prepare-rust.sh, not this sed.
            self.assertEqual(rust.read_text(), 'ci-llvm=true\n')
            self.assertNotIn('rust has been fixed', result.stdout)

    def test_handles_fix_guards_find_cloned_packages(self):
        # FIX 守卫目录为空时会静默跳过，这里确认每个修补都能找到 ./package 下的软件包。
        fixes = {
            'theme-argon': 'luci-theme-argon/luci-app-argon-config/root/etc/config/argon',
            'theme-aurora': 'luci-app-aurora-config/root/usr/share/aurora/default.template',
            'theme-vantage': 'luci-theme-vantage/luci-theme-vantage/htdocs/luci-static/vantage/vantage.css',
            'natmapt': 'luci-app-natmapt/root/usr/share/luci/menu.d/luci-app-natmap.json',
        }
        with tempfile.TemporaryDirectory() as tmp:
            wrt = Path(tmp) / 'wrt'
            for target in fixes.values():
                path = wrt / 'package' / target
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"admin/network/natmap": {}}\n')
            env = dict(os.environ, GITHUB_WORKSPACE=tmp)
            result = subprocess.run(['bash', str(ROOT / 'Scripts/Handles.sh')], cwd=wrt, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            script = (ROOT / 'Scripts/Handles.sh').read_text()
            for name in fixes:
                self.assertIn('FIX "%s"' % name, script)
                # macOS 的 BSD sed 会走到 "fix failed"，但两种输出都说明守卫目录找到了。
                self.assertRegex(result.stdout, '%s (has been fixed!|fix failed; continuing!)' % name)


if __name__ == '__main__': unittest.main()
