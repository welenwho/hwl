#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

# 雅典娜 RE-CS-02 的 5.2GHz 是 QCN9074。开关决定编不编这路驱动。
# n：不编入驱动，并关掉 PCIe，固件里看不到这路 wifi，只剩 IPQ6018 双频。
# y：编入驱动并保留 PCIe，系统是三频。
set -euo pipefail
[ -n "${GITHUB_WORKSPACE:-}" ] || exit 0
[ -n "${WRT_CONFIG:-}" ] || exit 0

CFG="$GITHUB_WORKSPACE/Config/${WRT_CONFIG}.txt"
[ -f "$CFG" ] || exit 0
grep -q 'CONFIG_TARGET_DEVICE_qualcommax_ipq60xx_DEVICE_jdcloud_re-cs-02=y' "$CFG" || exit 0
grep -q 'ATHENA_QCN9074=' "$CFG" || exit 0
[ -d ./target/linux/qualcommax ] || exit 0

normalize_switch() {
	printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]'
}

OVERRIDE=$(normalize_switch "${WRT_ATHENA_QCN9074:-}")
case "$OVERRIDE" in
	y|yes|1|true|on) MODE=y ;;
	n|no|0|false|off) MODE=n ;;
	*)
		FROM_CFG=$(grep -E '^[[:space:]]*#?[[:space:]]*ATHENA_QCN9074=' "$CFG" | tail -1 || true)
		FROM_CFG=${FROM_CFG##*=}
		case "$(normalize_switch "$FROM_CFG")" in
			y|yes|1|true|on) MODE=y ;;
			*) MODE=n ;;
		esac
		;;
esac

#设备包以源码 ipq60xx.mk 为准，只增删 QCN9074 相关的几项，上游加的包不会丢
MK="./target/linux/qualcommax/image/ipq60xx.mk"
[ -f "$MK" ] || {
	echo "athena image makefile is missing: $MK" >&2
	exit 1
}
DEVICE_PACKAGES=$(python3 - "$MK" "$MODE" <<'PY'
import pathlib
import re
import sys

mode = sys.argv[2]
text = pathlib.Path(sys.argv[1]).read_text().replace("\\\n", " ")
block = re.search(r"^define Device/jdcloud_re-cs-02[ \t]*\n(.*?)^endef", text, re.M | re.S)
if not block:
    raise SystemExit("missing Device/jdcloud_re-cs-02 in image makefile")

packages = None
for match in re.finditer(r"^[ \t]*DEVICE_PACKAGES[ \t]*(:=|\+=|=)(.*)$", block.group(1), re.M):
    words = match.group(2).split()
    packages = words if match.group(1) != "+=" or packages is None else packages + words
if not packages:
    raise SystemExit("Device/jdcloud_re-cs-02 has no DEVICE_PACKAGES")
if any("$" in word for word in packages):
    raise SystemExit("DEVICE_PACKAGES uses make variables: " + " ".join(packages))

def qcn9074(word):
    name = word.lstrip("-")
    return name == "kmod-ath11k-pci" or name.startswith("ath11k-firmware-qcn9074")

if mode == "y":
    packages = [word for word in packages if not word.startswith("-") or not qcn9074(word)]
    if not any(word.startswith("ath11k-firmware-qcn9074") for word in packages):
        packages.append("ath11k-firmware-qcn9074-ddwrt")
else:
    packages = [word for word in packages if not qcn9074(word)]
    packages += ["-kmod-ath11k-pci", "-ath11k-firmware-qcn9074", "-ath11k-firmware-qcn9074-ddwrt"]
print(" ".join(packages))
PY
)
LINE="CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq60xx_DEVICE_jdcloud_re-cs-02=\"${DEVICE_PACKAGES}\""

DTS="./target/linux/qualcommax/dts/ipq6010-re-cs-02.dts"
[ -f "$DTS" ] || {
	echo "athena DTS is missing: $DTS" >&2
	exit 1
}

python3 - "$DTS" "$MODE" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
text = path.read_text()

def find_node_span(source, header):
    token = header + " {"
    start = source.find(token)
    if start < 0:
        token = header + "{"
        start = source.find(token)
    if start < 0:
        raise SystemExit("missing DTS node %s" % header)
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return brace, index
    raise SystemExit("unclosed DTS node %s" % header)

def own_head(source, brace, end):
    body = source[brace + 1:end]
    nested = body.find("{")
    if nested < 0:
        return body
    return body[:nested]

def own_status(source, header):
    brace, end = find_node_span(source, header)
    for line in own_head(source, brace, end).splitlines():
        stripped = line.strip()
        if stripped.startswith("status"):
            return stripped
    return ""

def set_own_status(source, header, status):
    brace, end = find_node_span(source, header)
    head = own_head(source, brace, end)
    desired = 'status = "%s";' % status
    if desired in head:
        return source
    if "status = " not in head:
        raise SystemExit("%s has no direct status property" % header)
    new_head = head.replace('status = "okay";', desired, 1).replace('status = "disabled";', desired, 1)
    return source[:brace + 1] + new_head + source[brace + 1 + len(head):]

def remove_labeled_node(source, label):
    token = label + ":"
    start = source.find(token)
    if start < 0:
        return source
    line = source.rfind("\n", 0, start) + 1
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                if end < len(source) and source[end] == ";":
                    end += 1
                if end < len(source) and source[end] == "\n":
                    end += 1
                return source[:line] + source[end:]
    raise SystemExit("unclosed DTS node %s" % label)

pcie_brace, pcie_end = find_node_span(text, "&pcie0")
if "pci17cb,1104" not in text[pcie_brace:pcie_end]:
    raise SystemExit("refusing to change &pcie0: QCN9074 pci17cb,1104 not found")
if own_status(text, "&wifi") != 'status = "okay";':
    raise SystemExit("refusing to edit DTS: IPQ6018 &wifi is not okay")

if mode == "y":
    text = set_own_status(text, "&pcie0", "okay")
    text = remove_labeled_node(text, "qcn9074_perst_hog")
    if own_status(text, "&pcie0") != 'status = "okay";':
        raise SystemExit("QCN9074 &pcie0 was not left enabled")
    if "qcn9074-perst-hog" in text:
        raise SystemExit("QCN9074 reset hog still present")
else:
    text = set_own_status(text, "&pcie0", "disabled")
    if "qcn9074-perst-hog" not in text:
        brace, end = find_node_span(text, "&tlmm")
        hog = """
	qcn9074_perst_hog: qcn9074-perst-hog {
		gpio-hog;
		gpios = <53 GPIO_ACTIVE_HIGH>;
		output-low;
		line-name = "qcn9074-perst";
	};"""
        text = text[:brace + 1] + hog + text[brace + 1:]
    if own_status(text, "&pcie0") != 'status = "disabled";':
        raise SystemExit("QCN9074 &pcie0 was not disabled")
    if text.count("qcn9074-perst-hog") != 1:
        raise SystemExit("QCN9074 reset hog was not added once")

if own_status(text, "&wifi") != 'status = "okay";':
    raise SystemExit("IPQ6018 &wifi status changed")
path.write_text(text)
PY


touch ./.config
grep -v -E '^#?[[:space:]]*ATHENA_QCN9074=|^CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq60xx_DEVICE_jdcloud_re-cs-02=' ./.config > ./.config.athena-qcn9074 || true
printf '%s\n' "$LINE" >> ./.config.athena-qcn9074
mv ./.config.athena-qcn9074 ./.config

if [ -n "${GITHUB_ENV:-}" ]; then
	echo "WRT_QCN9074=$MODE" >> "$GITHUB_ENV"
fi

if [ "$MODE" = "y" ]; then
	echo "athena QCN9074 on: tri-band WiFi, 5.2GHz driver included"
else
	echo "athena QCN9074 off: dual-band WiFi, 5.2GHz radio is not present"
fi
