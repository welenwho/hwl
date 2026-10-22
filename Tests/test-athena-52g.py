#!/usr/bin/env python3
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DTS_BODY = """
&tlmm {
	tmp1628_pins: tmp1628-pins {
		pins = "gpio69";
		function = "gpio";
	};
};

&pcie0 {
	status = "okay";
	perst-gpios = <&tlmm 53 GPIO_ACTIVE_LOW>;

	pcie@0 {
		wifi@0,0 {
			status = "okay";
			compatible = "pci17cb,1104";
		};
	};
};

&wifi {
	status = "okay";
	qcom,ath11k-calibration-variant = "JDC-RE-CS-02";
};
"""
DEVICE_PACKAGES = "CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq60xx_DEVICE_jdcloud_re-cs-02="


class Athena52gTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name) / "wrt"
        (self.tree / "target/linux/qualcommax/dts").mkdir(parents=True)
        self.dts = self.tree / "target/linux/qualcommax/dts/ipq6010-re-cs-02.dts"
        self.dts.write_text(DTS_BODY)
        self.config = self.tree / ".config"
        self.env = dict(os.environ, GITHUB_WORKSPACE=str(ROOT))
        self.env.pop("WRT_ATHENA_QCN9074", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, config, switch=None):
        env = dict(self.env, WRT_CONFIG=config)
        if switch is None:
            env.pop("WRT_ATHENA_QCN9074", None)
        else:
            env["WRT_ATHENA_QCN9074"] = switch
        return subprocess.run(
            ["bash", str(ROOT / "Scripts/Athena-52g.sh")],
            cwd=self.tree,
            env=env,
            capture_output=True,
            text=True,
        )

    def package_line(self):
        lines = [line for line in self.config.read_text().splitlines() if line.startswith(DEVICE_PACKAGES)]
        self.assertEqual(len(lines), 1, self.config.read_text())
        return lines[0]

    def test_config_switch_defaults_to_dual_band(self):
        config = (ROOT / "Config/IPQ60XX-WIFI-YES-RE-CS-02.txt").read_text()
        self.assertIn("# ATHENA_QCN9074=n", config)
        self.assertNotIn("CONFIG_TARGET_DEVICE_PACKAGES_", config)
        result = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dual-band", result.stdout)
        dts = self.dts.read_text()
        self.assertIn('&pcie0 {\n\tstatus = "disabled";', dts)
        self.assertIn('&wifi {\n\tstatus = "okay";', dts)
        self.assertEqual(dts.count("qcn9074-perst-hog"), 1)
        line = self.package_line()
        self.assertIn("-kmod-ath11k-pci", line)
        self.assertIn("-ath11k-firmware-qcn9074-ddwrt", line)
        self.assertIn("luci-app-athena-led", line)
        self.assertNotIn("-kmod-ath11k-ahb", line)
        self.assertFalse((self.tree / "target/linux/qualcommax/ipq60xx/base-files").exists())

        again = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.dts.read_text(), dts)
        self.assertEqual(self.config.read_text().count(DEVICE_PACKAGES), 1)

    def test_switch_on_keeps_tri_band_and_restores_pcie(self):
        off = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02", "n")
        self.assertEqual(off.returncode, 0, off.stdout + off.stderr)
        result = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02", "y")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("tri-band", result.stdout)
        dts = self.dts.read_text()
        self.assertIn('&pcie0 {\n\tstatus = "okay";', dts)
        self.assertIn('&wifi {\n\tstatus = "okay";', dts)
        self.assertNotIn("qcn9074-perst-hog", dts)
        self.assertIn("pci17cb,1104", dts)
        line = self.package_line()
        self.assertIn("ath11k-firmware-qcn9074-ddwrt", line)
        self.assertNotIn("-kmod-ath11k-pci", line)
        self.assertNotIn("-ath11k-firmware-qcn9074", line)

    def test_workflow_override_beats_config_file(self):
        result = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02", "y")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('&pcie0 {\n\tstatus = "okay";', self.dts.read_text())
        self.assertIn("tri-band", result.stdout)

    def test_refuses_to_change_pcie_without_qcn9074(self):
        self.dts.write_text(DTS_BODY.replace('compatible = "pci17cb,1104";', 'compatible = "pci17cb,0000";'))
        result = self.run_hook("IPQ60XX-WIFI-YES-RE-CS-02", "n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pci17cb,1104", result.stderr)
        self.assertIn('&pcie0 {\n\tstatus = "okay";', self.dts.read_text())
        self.assertIn('&wifi {\n\tstatus = "okay";', self.dts.read_text())

    def test_other_devices_are_left_alone(self):
        original = self.dts.read_text()
        result = self.run_hook("IPQ60XX-WIFI-YES-RE-SS-01", "n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.dts.read_text(), original)
        self.assertFalse(self.config.exists())

    def test_configs_without_the_switch_are_left_alone(self):
        original = self.dts.read_text()
        result = self.run_hook("IPQ60XX-WIFI-NO", "y")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.dts.read_text(), original)
        self.assertFalse(self.config.exists())


if __name__ == "__main__":
    unittest.main()
