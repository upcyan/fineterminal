# FineTerminal — fnOS 终端

飞牛 fnOS 的 Web 终端（fpk 应用）：xterm.js + 纯 Python3 标准库后端，
fnOS 应用中心一键安装，桌面图标直接打开，手机浏览器也能用。

## 安装

```bash
# 在 fnOS 应用中心手动安装 dist/fineterminal.fpk，或命令行：
sudo appcenter-cli install-fpk dist/fineterminal.fpk
# 注意：应用中心覆盖安装要求版本号递增（fpk/manifest 的 version）
```

- 桌面入口「飞牛终端」→ fnOS 桌面窗口内打开（统一网关 `/app/fineterminal`，复用 NAS 登录态）
- 多标签、7 套配色主题、字号缩放、复制/粘贴、快捷命令、保留会话（关闭窗口 shell 继续存活，重开恢复画面）
- 后端零依赖（纯 Python3 标准库），PTY + WebSocket over Unix socket
- 修改源码后重新打包：`./fpk/build.sh`（产物输出到 `dist/`）；
  本机直接升级并校验版本：`./fpk/build.sh --install`

### 安全机制

| 层 | 机制 |
|---|---|
| 入口 | fnOS 统一网关 NAS 登录态鉴权（未登录返回 `invalid token`），服务仅监听本地 Unix socket，无 TCP 暴露 |
| 传输 | **页面能力令牌**：下发 HTML 时注入一次性随机令牌，WS 握手必须携带 `?ft=<token>`；跨站页面拿不到令牌，且与接入域名无关（局域网 / fn Connect / 中继天然满足） |
| 隔离 | 会话按网关身份（`X-Trim-Userid`）隔离，用户之间互相 list/attach/kill 不到对方的 root shell |
| 应用锁 | 可选密码锁（工具栏 🔒 设置）：新连接必须先解锁才能操作；加盐万轮 SHA-256 存储、失败节流延迟 |
| 文件 | 静态文件服务 `realpath` 前缀校验，配置文件 `0600` |
| 回收 | 脱离 10 分钟未重连的会话自动清理，避免残留 shell |

**注意**：shell 以 root 运行（与飞牛官方终端一致），请勿将 NAS 暴露公网；开启应用锁可为共享账号场景加一道门槛。

## 功能

- **多标签终端**：`+` 新建、标签可关闭拖动，标题跟随 shell 动态变化；最后一个标签关闭时自动新开防误触
- **增强**：7 套配色主题、字号缩放（A-/A+）、复制/粘贴、快捷命令栏（一键发送常用命令）
- **保留会话**：关闭窗口 shell 继续存活（10 分钟内重开自动恢复），恢复时回放 512KB 输出历史，
  并触发 SIGWINCH 让 htop/vim 等 TUI 全量重绘
- **安全认证**：锁屏密码（加盐万轮 SHA-256）、连续输错节流、断线自动重连与页面自刷新

## 从源码构建

```bash
./fpk/build.sh              # 内联生成单文件页面 → fnpack 打包 → dist/fineterminal.fpk
./fpk/build.sh --install    # 构建 + 本机升级安装 + 版本校验（install-local）
```

> 需要 fnOS 自带的 `fnpack`；发新版前 bump `fpk/manifest` 的 `version`。

## 测试

`tests/` 为针对后端的全链路自测（WebSocket + PTY，需 root 运行本机测试服务）：

```bash
# 起一个测试服务实例
sudo env SOCKET_PATH=$PWD/test.sock HTTP_DIR=$PWD/fpk/app/www \
  python3 fpk/app/server/terminal-server.py &

sudo python3 tests/fpK_test_ws.py              # 基础收发
sudo python3 tests/fpK_test_attach_resize.py   # 恢复附着与 SIGWINCH 重绘
sudo python3 tests/fpK_test_persist.py         # 保留会话（关窗存活、重开恢复）
sudo python3 tests/fpK_test_input.py           # 大段粘贴/大输出不丢字节
sudo python3 tests/fpK_test_security.py        # 令牌鉴权、用户隔离、密码锁
```

## 目录结构

```
fpk/manifest                 应用清单（版本、入口）
fpk/app/server/terminal-server.py   后端：HTTP 静态 + WebSocket + PTY（纯标准库）
fpk/app/www/                 单文件页面（gen_index.py 生成，含内联 xterm.js）
fpk/www-src/                 前端源码（app.js / 模板 / vendor）
fpk/cmd/                     生命周期脚本（start/stop/status）
fpk/config/ fpk/wizard/      权限声明与安装向导
fpk/gen_index.py             前端内联打包脚本
tests/                       全链路自测
```

## 已知限制

- 仅 amd64（fnOS 常见架构）
- 应用锁为应用级保护，退出应用后仍受系统账户保护
- 服务进程重启会丢失全部会话（PTY 固有限制）

## 历史说明

早期版本包含 Qt5 桌面原生形态（.deb），因 fnOS Web 桌面无法启动原生窗口、
且功能与 Web 版完全重叠，已于 v1.0.13 后移除。
