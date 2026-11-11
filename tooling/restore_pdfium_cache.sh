#!/usr/bin/env bash
# Restore PDFium into the Dart build-hook cache from a built APK.
#
# `pdfium_dart` downloads a prebuilt libpdfium from GitHub Releases the first time
# a build needs it, and skips the download when the target file already exists:
#
#   app/.dart_tool/hooks_runner/shared/pdfium_dart/build/<hash>/chromium_8125/
#       android-arm64/libpdfium.so
#       android-arm/libpdfium.so
#       android-x64/libpdfium.so
#
# GitHub occasionally answers 504 for those release assets. If you already have a
# built APK (or a saved libpdfium.so), this script seeds the cache and the build
# proceeds without touching the network.
#
# Usage:
#   tooling/restore_pdfium_cache.sh                      # from the newest APK
#   tooling/restore_pdfium_cache.sh path/to/libpdfium.so
#   tooling/restore_pdfium_cache.sh path/to/libpdfium.so arm64|arm|x64
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir="$repo_root/app"
release_dir="chromium_8125"

seed() {
  local lib="$1" arch="$2"
  local dirs
  dirs="$(find "$app_dir/.dart_tool/hooks_runner/shared/pdfium_dart/build" \
            -maxdepth 1 -mindepth 1 -type d 2>/dev/null || true)"
  if [[ -z "$dirs" ]]; then
    echo "No hook cache directory yet; run a build once (it will fail on the download), then retry." >&2
    exit 1
  fi
  while IFS= read -r dir; do
    [[ -z "$dir" ]] && continue
    # Only the hook's own shared build dirs carry the gate library.
    [[ -f "$dir/libpdfrx_pdfium_gate.so" ]] || continue
    local target="$dir/$release_dir/android-$arch"
    mkdir -p "$target"
    cp "$lib" "$target/libpdfium.so"
    echo "seeded $target/libpdfium.so"
  done <<< "$dirs"
}

source_lib="${1:-}"
only_abi="${2:-}"

if [[ -z "$source_lib" ]]; then
  apk="$(ls -t "$app_dir"/build/app/outputs/flutter-apk/*.apk 2>/dev/null | head -1 || true)"
  if [[ -z "$apk" ]]; then
    echo "No APK found. Build one (or pass a libpdfium.so path) first." >&2
    exit 1
  fi
  echo "Reading libpdfium.so from $apk"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  unzip -o -q "$apk" 'lib/*/libpdfium.so' -d "$tmp" || true
  found=0
  for pair in "arm64-v8a:arm64" "armeabi-v7a:arm" "x86_64:x64"; do
    abi_dir="${pair%%:*}"
    arch="${pair##*:}"
    if [[ -n "$only_abi" && "$only_abi" != "$arch" ]]; then continue; fi
    lib="$tmp/lib/$abi_dir/libpdfium.so"
    if [[ -f "$lib" ]]; then
      seed "$lib" "$arch"
      found=1
    fi
  done
  if [[ "$found" -eq 0 ]]; then
    echo "This APK contains no libpdfium.so for the requested ABI." >&2
    exit 1
  fi
  exit 0
fi

if [[ ! -f "$source_lib" ]]; then
  echo "No such file: $source_lib" >&2
  exit 1
fi
seed "$source_lib" "${only_abi:-arm64}"
