#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

# Redmi AX6（含 stock layout）没有 USB 口、PCIe 设备和 SATA/NVMe，闪存是 NAND/UBI，
# 下面这些包在它上面用不上，开机还会加载一部分模块占内存。
# 只从这两个设备的 rootfs 里去掉（TARGET_DEVICE_PACKAGES 写 -包名，打包时 apk del），
# 同一配置里的 AP8220 和其他配置的机型照常带着。
#
# 依赖已按 owrt、main 两个分支编出来的 AX6 固件核对（解包 lib/apk/db/installed）：
# 列表里的包只被列表里的其他包依赖；留下的程序和内核模块都不链接、不依赖列表里的库和模块。
# 有意保留：block-mount、libblkid（block 会 dlopen）、kmod-macvlan（shellsync 依赖）、
# PPPoE、nand-utils、kmod-mtd-rw、zram 和内核加密/压缩库。
set -euo pipefail
[ -f ./.config ] || exit 0

TARGET="qualcommax_ipq807x"
DEVICES=()
for dev in redmi_ax6 redmi_ax6-stock; do
	if grep -qxF "CONFIG_TARGET_DEVICE_${TARGET}_DEVICE_${dev}=y" ./.config; then
		DEVICES+=("$dev")
	fi
done
[ ${#DEVICES[@]} -gt 0 ] || exit 0

PACKAGES=(
	# USB 控制器、串口
	kmod-usb-common kmod-usb-core kmod-usb-dwc3 kmod-usb-dwc3-qcom kmod-usb-roles
	kmod-usb-ohci kmod-usb-uhci kmod-usb-xhci-hcd kmod-usb3
	kmod-usb-serial kmod-usb-serial-qualcomm kmod-usb-serial-wwan kmod-usb-wdm
	# USB 网卡、手机共享
	kmod-usb-net kmod-usb-net-asix kmod-usb-net-asix-ax88179 kmod-usb-net-cdc-eem
	kmod-usb-net-cdc-ether kmod-usb-net-cdc-mbim kmod-usb-net-cdc-ncm kmod-usb-net-cdc-subset
	kmod-usb-net-huawei-cdc-ncm kmod-usb-net-ipheth kmod-usb-net-rndis kmod-usb-net-rtl8150
	kmod-usb-net-rtl8152 kmod-usb-net-sierrawireless kmod-mii kmod-phy-ax88796b r8152-firmware
	# USB 存储
	kmod-usb-storage kmod-usb-storage-extras kmod-usb-storage-uas
	# USB 工具
	usbutils usbids usb-modeswitch usbmuxd libimobiledevice libimobiledevice-glue
	libplist libusbmuxd libusb-1.0 libudev-zero
	# SATA / NVMe
	kmod-ata-core kmod-ata-ahci kmod-scsi-core kmod-nvme nvme-cli libnvme liburing
	smartmontools smartmontools-drivedb
	# btrfs / xfs，以及依赖它们的 diskman、partexp
	kmod-fs-btrfs btrfs-progs kmod-lib-raid6 kmod-lib-xor kmod-fs-xfs xfs-mkfs
	libinih liburcu libattr liblzo
	luci-app-diskman luci-i18n-diskman-zh-cn luci-app-partexp luci-i18n-partexp-zh-cn
	parted libparted dosfstools swap-utils wipefs bc libreadline
	# ext4 / f2fs
	kmod-fs-ext4 kmod-fs-f2fs e2fsprogs f2fs-tools f2fsck mkf2fs resize2fs
	libext2fs libcomerr libss libe2p libf2fs
	# ntfs（owrt 是 kmod-fs-ntfs，main 是 kmod-fs-ntfs3）/ exfat / vfat / fuse
	kmod-fs-ntfs kmod-fs-ntfs3 ntfs3-mount kmod-fs-exfat kmod-fs-vfat kmod-fuse
	kmod-nls-cp437 kmod-nls-iso8859-1 kmod-nls-utf8 exfat-fsck exfat-mkfs
	# ksmbd 文件共享
	kmod-fs-ksmbd kmod-fs-smbfs-common kmod-fs-netfs kmod-fs-exportfs kmod-nls-ucs2-utils
	kmod-asn1-decoder kmod-oid-registry kmod-lib-crc16
	# 磁盘工具
	automount blkid lsblk fdisk cfdisk sfdisk gdisk cgdisk sgdisk mmc-utils losetup
	libfdisk libsmartcols libmount libpopt musl-fts libxml2
	# 链路聚合、隧道、虚拟网卡
	kmod-bonding proto-bonding kmod-wireguard kmod-ovpn-backports kmod-veth kmod-dummy
	# PCIe wifi（AX6 的 wifi 都在 AHB 上）
	kmod-ath11k-pci kmod-mhi-bus kmod-qrtr-mhi
	# natmap、btop、htop、iperf3（bash、coreutils-timeout 只有 natmap 在用）
	natmapt luci-app-natmapt luci-i18n-natmapt-zh-cn bash coreutils-timeout coreutils
	btop htop iperf3 libiperf3 libatomic
)

# 先展开依赖，只写这次编译真的会装进去的包：apk del 遇到一个不存在的包名会整条失败，一个都不删
make defconfig >/dev/null

# main 分支的 QSDK NSS（ECM、lag-mgr、bridge-mgr 等）依赖 kmod-bonding，那边要保留
KEEP=()
if grep -qxF "CONFIG_PACKAGE_kmod-qca-nss-ecm=y" ./.config; then
	KEEP+=(kmod-bonding)
fi

REMOVE=()
for pkg in "${PACKAGES[@]}"; do
	for keep in ${KEEP[@]+"${KEEP[@]}"}; do
		[ "$pkg" = "$keep" ] && continue 2
	done
	if grep -qxF "CONFIG_PACKAGE_${pkg}=y" ./.config; then
		REMOVE+=("-${pkg}")
	fi
done
[ ${#REMOVE[@]} -gt 0 ] || exit 0

for dev in "${DEVICES[@]}"; do
	key="CONFIG_TARGET_DEVICE_PACKAGES_${TARGET}_DEVICE_${dev}"
	old=$(grep "^${key}=" ./.config | tail -1 | sed -e "s/^${key}=//" -e 's/^"//' -e 's/"$//' || true)
	merged=()
	for word in $old "${REMOVE[@]}"; do
		for seen in ${merged[@]+"${merged[@]}"}; do
			[ "$word" = "$seen" ] && continue 2
		done
		merged+=("$word")
	done
	grep -v "^${key}=" ./.config > ./.config.ax6-slim || true
	printf '%s="%s"\n' "$key" "${merged[*]}" >> ./.config.ax6-slim
	mv ./.config.ax6-slim ./.config
done

echo "redmi ax6 slim: ${#REMOVE[@]} packages removed from ${DEVICES[*]}"
