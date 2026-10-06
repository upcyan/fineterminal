#!/usr/bin/env bash
# FineTerminal 一键构建 + 打包 .deb
# 用法: ./build.sh        构建并打包
#       ./build.sh --run  构建后本地运行（不打包）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="$ROOT/build/app"
PKG="$ROOT/build/pkg"
DEB_ROOT="$PKG/root"
VERSION="$(grep -oP "project\(FineTerminal VERSION \K[0-9.]+" "$ROOT/CMakeLists.txt")"

# fnOS 的 TrimRepo 精简了 libqtermwidget5-1-dev，缺头文件时自动从 Debian 镜像解包
DEPS="$BUILD/deps-root"
if [ ! -f "$DEPS/usr/include/qtermwidget5/qtermwidget.h" ]; then
    echo "==> 获取 qtermwidget5 开发头文件"
    mkdir -p "$DEPS"
    URL="http://mirrors.aliyun.com/debian/pool/main/q/qtermwidget/libqtermwidget5-1-dev_1.2.0-2_amd64.deb"
    curl -fsSL "$URL" -o "$DEPS/dev.deb"
    dpkg -x "$DEPS/dev.deb" "$DEPS"
    # 让 CMake target 指向系统运行库（跨设备无法建软链，直接复制）
    sed -i 's#/usr/lib/x86_64-linux-gnu/libutf8proc.so#/usr/lib/x86_64-linux-gnu/libutf8proc.so.2#' \
        "$DEPS/usr/lib/x86_64-linux-gnu/cmake/qtermwidget5/qtermwidget5-targets.cmake"
    cp /usr/lib/x86_64-linux-gnu/libqtermwidget5.so.1.2.0 "$DEPS/usr/lib/x86_64-linux-gnu/"
    ln -sfn libqtermwidget5.so.1.2.0 "$DEPS/usr/lib/x86_64-linux-gnu/libqtermwidget5.so.1"
fi

echo "==> CMake 配置"
cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release \
    -DQTERMWIDGET5_ROOT="$DEPS"

echo "==> 编译"
cmake --build "$BUILD" -j"$(nproc)"

if [ "${1:-}" = "--run" ]; then
    exec "$BUILD/fineterminal"
fi

echo "==> 组装 .deb"
rm -rf "$DEB_ROOT"
install -Dm755 "$BUILD/fineterminal"            "$DEB_ROOT/usr/bin/fineterminal"
install -Dm644 "$ROOT/packaging/fineterminal.desktop" "$DEB_ROOT/usr/share/applications/fineterminal.desktop"
install -Dm644 "$ROOT/resources/fineterminal.svg"     "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/fineterminal.svg"
mkdir -p "$DEB_ROOT/DEBIAN"
chmod 755 "$DEB_ROOT/DEBIAN"
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: fineterminal
Version: $VERSION
Architecture: amd64
Maintainer: FineTerminal <dev@fnos.local>
Depends: libqt5widgets5 (>= 5.15), libqtermwidget5-1 (>= 1.2.0), libqt5svg5
Section: utils
Priority: optional
Homepage: https://www.fnnas.com
Description: fnOS 多标签终端
 支持多标签、配色主题、字体缩放、快捷命令工具栏、
 锁屏密码保护与空闲自动锁定的桌面终端模拟器。
EOF
echo "标准版本" > "$DEB_ROOT/DEBIAN/changelog"

DEB="$PKG/fineterminal_${VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB"
echo "==> 完成: $DEB"
