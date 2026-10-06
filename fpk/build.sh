#!/usr/bin/env bash
# FineTerminal fpk 一键构建：内联生成单文件页面 → fnpack 打包 → 输出到 dist/
# 用法:
#   ./build.sh              构建，产物输出到 ../dist/
#   ./build.sh --install    构建 + 本机安装升级（install-local）+ 版本校验
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

python3 gen_index.py
fnpack build

mkdir -p ../dist
mv -f fineterminal.fpk ../dist/
echo "==> 构建完成: $ROOT/../dist/fineterminal.fpk"

if [ "${1:-}" = "--install" ]; then
    VERSION="$(grep -oP '^version\s*=\s*\K[0-9.]+' manifest)"
    # 注意：install-local 是"卸载重装"语义，会清空应用内的锁屏密码（sessconf.json）。
    # 不要用 install-fpk 做升级——实测它会把包暂存后静默失败（版本号纹丝不动）。
    echo "==> 安装升级 v$VERSION（install-local）..."
    sudo appcenter-cli install-local -d "$ROOT" >/tmp/fineterminal-install.log 2>&1 || true

    INSTALLED="$(grep -oP '^version\s*=\s*\K[0-9.]+' /var/apps/fineterminal/manifest 2>/dev/null || echo none)"
    if [ "$INSTALLED" = "$VERSION" ]; then
        echo "==> 安装成功: 本机版本 $INSTALLED"
    else
        echo "==> 安装失败: 期望 $VERSION，实际 $INSTALLED" >&2
        echo "    完整日志: /tmp/fineterminal-install.log" >&2
        exit 1
    fi
fi
