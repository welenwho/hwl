#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'Scripts/Preset-SBProxy.sh'


class PresetTests(unittest.TestCase):
    def fixture(self, base, presets=True):
        package_path = base / 'wrt/package'
        repo = package_path / 'packages'
        plugin = repo / 'luci-app-sbproxy'
        plugin.mkdir(parents=True)
        (plugin / 'Makefile').write_text('PKG_NAME:=luci-app-sbproxy\n')
        data = plugin / 'root/etc/sbproxy'
        (data / 'resources').mkdir(parents=True)
        (data / 'dashboard').mkdir()
        if presets:
            for name in ('geoip_cn', 'geosite_cn'):
                (data / 'resources' / (name + '.srs')).write_text('SRS-old')
                (data / 'resources' / (name + '.ver')).write_text('20260901000000\n')
        (data / 'resources/direct_list.txt').write_text('user.example\n')
        (data / 'dashboard/index.html').write_text('old-dashboard')
        scripts = repo / '.github/scripts'
        scripts.mkdir(parents=True)
        validator = base / 'validator'
        validator.write_text('#!/bin/sh\ncase "$(head -c 3 "$3")" in SRS) exit 0;; *) exit 1;; esac\n')
        validator.chmod(0o755)
        (scripts / 'prepare-rule-set-tool.sh').write_text('''#!/bin/bash
[ "${MOCK_TOOL_FAIL:-0}" != 1 ] || exit 1
printf 'SING_BOX=%s\nLD_LIBRARY_PATH=\n' "$MOCK_VALIDATOR" > "$GITHUB_ENV"
''')
        (scripts / 'update-sbproxy-geodata.sh').write_text('''#!/bin/bash
set -eu
data="$REPO_ROOT/luci-app-sbproxy/root/etc/sbproxy"
printf '%s' "$REPO_ROOT" > "$MOCK_UPDATE_ROOT"
printf SRS-new > "$data/resources/geoip_cn.srs"
printf '20260909000000\n' > "$data/resources/geoip_cn.ver"
[ "${MOCK_UPDATE_FAIL:-0}" != 1 ] || exit 1
printf SRS-new > "$data/resources/geosite_cn.srs"
printf '20260909000000\n' > "$data/resources/geosite_cn.ver"
printf new-dashboard > "$data/dashboard/index.html"
''')
        env = dict(os.environ, MOCK_VALIDATOR=str(validator), MOCK_UPDATE_ROOT=str(base / 'update-root'),
                   SBP_SING_BOX='nonexistent-sbproxy-test-tool', MOCK_TOOL_FAIL='0', MOCK_UPDATE_FAIL='0')
        return package_path, repo, data, env

    def run_case(self, failure=None, presets=True):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            package_path, repo, data, env = self.fixture(base, presets)
            if failure == 'tool': env['MOCK_TOOL_FAIL'] = '1'
            if failure == 'update': env['MOCK_UPDATE_FAIL'] = '1'
            if failure == 'install':
                bins = base / 'bin'
                bins.mkdir()
                mv = bins / 'mv'
                mv.write_text('#!/bin/sh\ncase "$1" in */repository/luci-app-sbproxy/root/etc/sbproxy/dashboard) exit 1;; esac\nexec /bin/mv "$@"\n')
                mv.chmod(0o755)
                env['PATH'] = str(bins) + ':' + os.environ['PATH']
            result = subprocess.run(['bash', str(SCRIPT), str(package_path)], env=env, text=True, capture_output=True)
            expected_failure = failure == 'install' or (failure is not None and not presets)
            self.assertEqual(result.returncode != 0, expected_failure, result.stdout + result.stderr)
            if failure and presets:
                self.assertEqual((data / 'resources/geoip_cn.srs').read_text(), 'SRS-old')
                self.assertEqual((data / 'resources/geosite_cn.srs').read_text(), 'SRS-old')
                self.assertEqual((data / 'dashboard/index.html').read_text(), 'old-dashboard')
            elif not failure:
                self.assertEqual((data / 'resources/geoip_cn.srs').read_text(), 'SRS-new')
                self.assertEqual((data / 'resources/geosite_cn.srs').read_text(), 'SRS-new')
                self.assertEqual((data / 'dashboard/index.html').read_text(), 'new-dashboard')
                self.assertNotEqual((base / 'update-root').read_text(), str(repo))
            self.assertEqual((data / 'resources/direct_list.txt').read_text(), 'user.example\n')
            self.assertFalse(list((repo / 'luci-app-sbproxy').glob('.preset.*')))

    def test_shared_update_is_staged(self): self.run_case()
    def test_partial_update_keeps_old_bundle(self): self.run_case('update')
    def test_validator_failure_keeps_old_bundle(self): self.run_case('tool')
    def test_missing_bundle_blocks_failed_update(self): self.run_case('update', False)
    def test_install_failure_restores_both_directories(self): self.run_case('install')

    def test_no_package_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['bash', str(SCRIPT), tmp], capture_output=True)
            self.assertEqual(result.returncode, 0)

    def test_handles_delegates(self):
        script = (ROOT / 'Scripts/Handles.sh').read_text()
        self.assertIn('Scripts/Preset-SBProxy.sh', script)
        for old in ('<<<<<<<', '>>>>>>>', '|||||||', 'cncidr.txt', 'china_ip4', 'china_ip6', 'HP_RESOURCES'):
            self.assertNotIn(old, script)


if __name__ == '__main__': unittest.main()
