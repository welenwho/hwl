#!/usr/bin/env python3
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Scripts/AX6-Slim.sh"
PREFIX = "CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq807x_DEVICE_"
DEVICES = (
    "CONFIG_TARGET_qualcommax=y\n"
    "CONFIG_TARGET_qualcommax_ipq807x=y\n"
    "CONFIG_TARGET_MULTI_PROFILE=y\n"
    "CONFIG_TARGET_PER_DEVICE_ROOTFS=y\n"
    "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_aliyun_ap8220=y\n"
    "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_redmi_ax6=y\n"
    "CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_redmi_ax6-stock=y\n"
)
# Packages AX6 still needs, or that other parts of the firmware depend on.
MUST_KEEP = {
    "block-mount", "libblkid", "kmod-macvlan", "kmod-ppp", "kmod-pppoe", "kmod-pppox",
    "ppp", "ppp-mod-pppoe", "luci-proto-ppp", "nand-utils", "kmod-mtd-rw", "zram-swap", "kmod-zram",
    "kmod-loop", "kmod-lib-zstd", "kmod-lib-lzo", "kmod-tun", "kmod-nft-offload",
    "kmod-nft-queue", "kmod-nft-bridge", "wpad-openssl", "kmod-ath11k", "kmod-ath11k-ahb",
    "kmod-qrtr", "kmod-qrtr-smd", "ipq-wifi-redmi_ax6", "kmod-nss-wifi-drv", "sing-box",
    "luci-app-sbproxy", "libstdcpp", "libncurses", "stuntman-client", "luci-app-watchcat",
    "watchcat", "ddns-go", "luci-app-ddns-go", "luci-app-upnp", "miniupnpd",
    "luci-app-wolultra", "etherwake", "relayd", "coremark", "kmod-crypto-sha256",
    "kmod-udptunnel4", "kmod-udptunnel6", "uboot-envtools", "ubi-utils", "fstools",
}


def script_packages():
    body = re.search(r"^PACKAGES=\((.*?)^\)", SCRIPT.read_text(), re.M | re.S).group(1)
    return [w for line in body.splitlines() for w in line.split("#", 1)[0].split()]


class AX6SlimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name) / "wrt"
        self.tree.mkdir()
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir()
        self.marker = Path(self.tmp.name) / "make-called"
        fake_make = bindir / "make"
        fake_make.write_text('#!/bin/sh\necho "$@" >> "%s"\n' % self.marker)
        fake_make.chmod(0o755)
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]))

    def tearDown(self):
        self.tmp.cleanup()

    def run_case(self, config):
        (self.tree / ".config").write_text(config)
        result = subprocess.run(["bash", str(SCRIPT)], cwd=self.tree, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (self.tree / ".config").read_text(), result

    def device_words(self, text, device):
        lines = [l for l in text.splitlines() if l.startswith(PREFIX + device + "=")]
        self.assertEqual(len(lines), 1, "%s lines: %r" % (device, lines))
        return lines[0].split("=", 1)[1].strip('"').split()

    def selected(self, names):
        return "".join("CONFIG_PACKAGE_%s=y\n" % n for n in names)

    def test_owrt_ax6_devices_get_negatives(self):
        names = [n for n in script_packages() if n not in ("kmod-fs-ntfs3", "ntfs3-mount")]
        text, result = self.run_case(DEVICES + self.selected(names + ["block-mount", "kmod-macvlan"]))
        for device in ("redmi_ax6", "redmi_ax6-stock"):
            words = self.device_words(text, device)
            self.assertTrue(all(w.startswith("-") for w in words), words)
            for name in ("-kmod-usb-core", "-kmod-bonding", "-kmod-fs-ntfs", "-usbmuxd",
                         "-natmapt", "-btop", "-htop", "-iperf3", "-luci-app-diskman"):
                self.assertIn(name, words)
            for name in ("-kmod-fs-ntfs3", "-ntfs3-mount", "-block-mount", "-kmod-macvlan"):
                self.assertNotIn(name, words)
        self.assertNotIn(PREFIX + "aliyun_ap8220=", text)
        self.assertIn("defconfig", self.marker.read_text())
        self.assertIn("redmi ax6 slim:", result.stdout)

    def test_main_keeps_bonding_for_nss(self):
        names = [n for n in script_packages() if n != "kmod-fs-ntfs"]
        text, _ = self.run_case(DEVICES + self.selected(names + ["kmod-qca-nss-ecm"]))
        words = self.device_words(text, "redmi_ax6")
        self.assertNotIn("-kmod-bonding", words)
        self.assertIn("-proto-bonding", words)
        self.assertIn("-kmod-fs-ntfs3", words)
        self.assertIn("-ntfs3-mount", words)
        self.assertNotIn("-kmod-fs-ntfs", words)

    def test_only_packages_in_this_build_are_negated(self):
        text, _ = self.run_case(DEVICES + self.selected(["kmod-usb-core", "btop"]))
        self.assertEqual(self.device_words(text, "redmi_ax6"), ["-kmod-usb-core", "-btop"])

    def test_other_configs_are_untouched(self):
        config = ("CONFIG_TARGET_qualcommax_ipq60xx=y\n"
                  "CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-cs-02=y\n"
                  + self.selected(script_packages()))
        text, _ = self.run_case(config)
        self.assertEqual(text, config)
        self.assertFalse(self.marker.exists())

    def test_existing_value_is_kept_and_rerun_is_stable(self):
        config = DEVICES + self.selected(["kmod-usb-core", "htop"]) + PREFIX + 'redmi_ax6="foo -bar"\n'
        (self.tree / ".config").write_text(config)
        for _ in range(2):
            subprocess.run(["bash", str(SCRIPT)], cwd=self.tree, env=self.env, check=True,
                           capture_output=True)
        text = (self.tree / ".config").read_text()
        self.assertEqual(self.device_words(text, "redmi_ax6"), ["foo", "-bar", "-kmod-usb-core", "-htop"])
        self.assertEqual(self.device_words(text, "redmi_ax6-stock"), ["-kmod-usb-core", "-htop"])

    def test_list_never_touches_packages_ax6_still_needs(self):
        names = script_packages()
        self.assertEqual(len(names), len(set(names)), "duplicate package names")
        self.assertEqual(sorted(MUST_KEEP & set(names)), [])


if __name__ == "__main__":
    unittest.main()
