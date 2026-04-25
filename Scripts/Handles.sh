#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

PKG_PATH="$GITHUB_WORKSPACE/wrt/package"

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"

#预置 SBProxy 数据：复用 packages 中的统一 SRS 更新与校验实现。
if ! bash "$PROJECT_ROOT/Scripts/Preset-SBProxy.sh" "$PKG_PATH"; then
	echo "SBProxy preset preparation failed!" >&2
	exit 1
fi

#修改argon主题字体和颜色
if [ -d "$PKG_PATH/luci-theme-argon" ]; then
	echo " "
	if sed -i "s/primary '.*'/primary '#31a1a1'/; s/'0.2'/'0.5'/; s/'none'/'bing'/; s/'600'/'normal'/" \
		"$PKG_PATH/luci-theme-argon/luci-app-argon-config/root/etc/config/argon"; then
		echo "theme-argon has been fixed!"
	else
		echo "theme-argon fix failed; continuing!"
	fi
fi

#修改aurora菜单式样
if [ -d "$PKG_PATH/luci-app-aurora-config" ]; then
	echo " "
	if find "$PKG_PATH/luci-app-aurora-config/root/usr/share/aurora/" -type f -name '*.template' -exec \
		sed -i "s/nav_type '.*'/nav_type 'dropdown'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" {} +; then
		echo "theme-aurora has been fixed!"
	else
		echo "theme-aurora fix failed; continuing!"
	fi
fi

#修复Tailscale配置文件冲突，并为1.102.2回移可调WireGuard批量大小
FEEDS_PACKAGES="$PKG_PATH/../feeds/packages"
TS_FILE="$(find "$FEEDS_PACKAGES" -maxdepth 3 -type f -wholename '*/tailscale/Makefile' -print -quit 2>/dev/null)"
if [ -f "$TS_FILE" ]; then
	TS_DIR="${TS_FILE%/Makefile}"
	TS_VERSION="$(sed -n 's/^PKG_VERSION:=//p' "$TS_FILE" | head -n 1)"
	TS_BATCH_PATCH_SOURCE="$PROJECT_ROOT/Patches/tailscale/010-backport-configurable-wg-batch-size.patch"
	TS_BATCH_PATCH_TARGET="$TS_DIR/patches/010-backport-configurable-wg-batch-size.patch"
	echo " "

	if sed -i '/\/files/d' "$TS_FILE"; then
		echo "tailscale has been fixed!"
	else
		echo "tailscale fix failed; continuing!"
	fi

	if [ "$TS_VERSION" = "1.102.2" ]; then
		if [ ! -f "$TS_BATCH_PATCH_SOURCE" ]; then
			echo "tailscale batch-size backport is missing!"
			exit 1
		fi
		if mkdir -p "$TS_DIR/patches" &&
			cp "$TS_BATCH_PATCH_SOURCE" "$TS_BATCH_PATCH_TARGET" &&
			sed -i 's/^PKG_RELEASE:=1$/PKG_RELEASE:=2/' "$TS_FILE"; then
			echo "tailscale 1.102.2 batch-size backport has been installed!"
		else
			echo "tailscale batch-size backport installation failed!"
			exit 1
		fi
	else
		echo "tailscale $TS_VERSION does not require the 1.102.2 batch-size backport."
	fi
fi

#修复Rust编译失败
RUST_FILE="$(find "$FEEDS_PACKAGES" -maxdepth 3 -type f -wholename '*/rust/Makefile' -print -quit 2>/dev/null)"
if [ -f "$RUST_FILE" ]; then
	echo " "

	if sed -i 's/ci-llvm=true/ci-llvm=false/g' "$RUST_FILE"; then
		echo "rust has been fixed!"
	else
		echo "rust fix failed; continuing!"
	fi
fi
