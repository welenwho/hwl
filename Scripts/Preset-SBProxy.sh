#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Reuse the package repository's validated SRS/dashboard updater. Firmware
# builds never generate legacy split IPv4/IPv6 resources or compile a core here.
set -euo pipefail

package_path="${1:-${GITHUB_WORKSPACE:?}/wrt/package}"
manifests=()
if [ ! -d "$package_path" ]; then
	echo 'SBProxy package tree is absent; skipping presets.'
	exit 0
fi
while IFS= read -r path; do manifests+=("$path"); done < <(
	find "$package_path" -maxdepth 3 -type f -path '*/luci-app-sbproxy/Makefile'
)
if [ "${#manifests[@]}" -eq 0 ]; then
	echo 'SBProxy package is absent; skipping presets.'
	exit 0
fi
[ "${#manifests[@]}" -eq 1 ] || { echo 'Multiple SBProxy packages found; refusing an ambiguous preset target.' >&2; exit 1; }
package_dir="$(CDPATH= cd -- "$(dirname -- "${manifests[0]}")" && pwd)"
repository="${package_dir%/*}"
data="$package_dir/root/etc/sbproxy"
resources="$data/resources"
updater="$repository/.github/scripts/update-sbproxy-geodata.sh"
prepare="$repository/.github/scripts/prepare-rule-set-tool.sh"
# resources 和 dashboard 必须有；yacd、metacubexd 面板只在软件包自带时才一起更新。
preset_dirs=(resources dashboard)
for name in dashboard-yacd dashboard-metacubexd; do
	[ ! -d "$data/$name" ] || preset_dirs+=("$name")
done
for name in "${preset_dirs[@]}"; do
	target="$data/$name"
	if [ -L "$target" ] || { [ -e "$target" ] && [ ! -d "$target" ]; }; then
		echo "Unsafe preset directory type: $target" >&2
		exit 1
	fi
done

has_presets() {
	local resource version
	for resource in geoip_cn geosite_cn; do
		[ -s "$resources/$resource.srs" ] && [ "$(head -c 3 "$resources/$resource.srs")" = SRS ] || return 1
		version="$(cat "$resources/$resource.ver" 2>/dev/null)" || return 1
		case "$version" in ''|*[!0-9]*) return 1;; esac
	done
}
fallback() {
	echo "WARNING: $*" >&2
	if has_presets; then
		echo 'Keeping the package repository SBProxy presets; no files were replaced.'
		exit 0
	fi
	echo 'No usable unified SBProxy presets remain; refusing to build with missing data.' >&2
	exit 1
}

[ -f "$updater" ] || fallback 'Shared SBProxy updater is unavailable; update the package repository.'
[ "${SBP_PRESET_UPDATE:-1}" != 0 ] || fallback 'Online SBProxy preset update was disabled.'

# Keep staging on the package filesystem so the final renames are atomic.
temporary="$(mktemp -d "$package_dir/.preset.XXXXXX")"
install_complete=0
moved=()
installed=()
cleanup() {
	local backup kept=0
	for backup in "$temporary"/old-*; do [ ! -d "$backup" ] || kept=1; done
	if [ "$install_complete" = 0 ] && [ "$kept" = 1 ]; then
		echo "Preset backups retained for recovery: $temporary" >&2
	else
		rm -rf -- "$temporary"
	fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
stage="$temporary/repository/luci-app-sbproxy/root/etc/sbproxy"
mkdir -p "$temporary/tool-runtime"
for name in "${preset_dirs[@]}"; do
	mkdir -p "$stage/$name"
	[ ! -d "$data/$name" ] || cp -a "$data/$name/." "$stage/$name/"
done

validator="$(command -v "${SBP_SING_BOX:-${SING_BOX:-sing-box}}" 2>/dev/null || true)"
validator_lib="${LD_LIBRARY_PATH:-}"
if [ -z "$validator" ] || [ ! -x "$validator" ]; then
	[ -f "$prepare" ] || fallback 'Shared rule-set validator preparation script is unavailable.'
	if ! (cd "$repository" &&
		RUNNER_TEMP="$temporary/tool-runtime" GITHUB_ENV="$temporary/tool.env" \
		RULE_TOOL_CACHE="${SBP_RULE_TOOL_CACHE:-$package_path/../dl/sbproxy-rule-cache}" \
		bash "$prepare"); then
		fallback 'Unable to prepare the pinned rule-set validator.'
	fi
	validator="$(sed -n 's/^SING_BOX=//p' "$temporary/tool.env" | tail -n 1)"
	validator_lib="$(sed -n 's/^LD_LIBRARY_PATH=//p' "$temporary/tool.env" | tail -n 1)"
	[ -x "$validator" ] || fallback 'Prepared rule-set validator is unavailable.'
fi

if ! REPO_ROOT="$temporary/repository" SING_BOX="$validator" LD_LIBRARY_PATH="$validator_lib" \
     GITHUB_OUTPUT="$temporary/update.output" bash "$updater"; then
	fallback 'SBProxy preset update failed; discarding staged partial changes.'
fi
for resource in geoip_cn geosite_cn; do
	[ -s "$stage/resources/$resource.ver" ] &&
		LD_LIBRARY_PATH="$validator_lib" "$validator" rule-set decompile "$stage/resources/$resource.srs" -o /dev/null ||
		fallback "Staged $resource failed final validation."
done
for name in "${preset_dirs[@]}"; do
	case "$name" in
		dashboard*) [ -s "$stage/$name/index.html" ] || fallback "Staged $name is incomplete." ;;
	esac
done

# 先把旧目录全部挪走再放入新目录，任何一步失败都整体回滚，不留半新半旧的预置数据。
restore() {
	local name
	for name in ${installed[@]+"${installed[@]}"}; do rm -rf -- "${data:?}/$name"; done
	for name in ${moved[@]+"${moved[@]}"}; do mv "$temporary/old-$name" "$data/$name"; done
}
mkdir -p "$data"
for name in "${preset_dirs[@]}"; do
	[ -d "$data/$name" ] || continue
	if ! mv "$data/$name" "$temporary/old-$name"; then
		restore
		echo 'Failed to move SBProxy presets aside; original directories restored.' >&2
		exit 1
	fi
	moved+=("$name")
done
for name in "${preset_dirs[@]}"; do
	if ! mv "$stage/$name" "$data/$name"; then
		restore
		echo 'Failed to install SBProxy presets; original directories restored.' >&2
		exit 1
	fi
	installed+=("$name")
done
install_complete=1
echo "SBProxy presets updated from the shared package scripts: ${preset_dirs[*]}"
