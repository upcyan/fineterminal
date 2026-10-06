# FineTerminal — fnOS 终端

两个形态的飞牛 fnOS 终端应用：

1. **fpk 应用版**（`fpk/fineterminal.fpk`）：Web 终端，xterm.js + Python3 标准库后端，
   fnOS 应用中心一键安装，桌面图标直接打开，手机浏览器也能用
2. **桌面原生版**（Qt5 + qtermwidget，`.deb`）：本地 Qt 终端模拟器

## fpk 版（推荐安装方式）

```bash
# 在 fnOS 应用中心手动安装 dist/fineterminal.fpk，或命令行：
sudo appcenter-cli install-fpk dist/fineterminal.fpk
# 注意：应用中心覆盖安装要求版本号递增（fpk/manifest 的 version）
```

- 桌面入口「飞牛终端」→ fnOS 桌面窗口内打开（统一网关 `/app/fineterminal`，复用 NAS 登录态）
- 多标签、7 套配色主题、字号缩放、复制/粘贴、快捷命令、保留会话（关闭窗口 shell 继续存活，重开恢复画面）
- 后端零依赖（纯 Python3 标准库），PTY + WebSocket over Unix socket
- 修改 fpk 源码后重新打包：`./fpk/build.sh`（产物输出到 `dist/`）；
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

## 桌面原生版

一个为飞牛 fnOS 打造的 Qt5 桌面终端模拟器，基于 `qtermwidget`（Konsole 内核），
开箱支持中文环境与 fnOS 桌面集成。

## 功能

- **本地终端 + 多标签**：`Ctrl+Shift+T` 新建 / `Ctrl+Shift+W` 关闭 / `Ctrl+Tab` 切换，
  最后一个标签关闭时自动新开，防误触退出；标签标题跟随 shell 动态变化
- **增强功能**：
  - 配色主题（DarkPastels、Solarized、Linux 等 Konsole 全套方案）
  - 字体 / 字号设置，`Ctrl++` `Ctrl+-` `Ctrl+0` 缩放与重置
  - 背景透明度、回滚缓冲行数、光标闪烁
  - 快捷命令工具栏：在设置里自定义常用命令（如 `df -h`），一键发送到当前终端
  - `Ctrl+Shift+C/V` 复制 / 粘贴，多行粘贴确认 + 行尾空白去除
- **安全认证**：
  - 锁屏密码（加盐 + 万轮哈希存储于本地配置）
  - `Ctrl+Shift+L` 手动锁定，启动时锁定，空闲自动锁定（阈值可调）
  - 连续输错 5 次冻结 3 秒

## 安装（fnOS / Debian 12）

在 fnOS 的 SSH 或桌面终端里执行：

```bash
sudo dpkg -i fineterminal_1.0.0_amd64.deb
# 若缺依赖：sudo apt-get -f install
```

安装后在 fnOS 桌面「开始菜单 → 系统」中找到 **飞牛终端 (FineTerminal)**，
或直接运行 `fineterminal`。

## 从源码构建

### fpk 应用版（推荐）

```bash
./fpk/build.sh              # 内联生成单文件页面 → fnpack 打包 → dist/fineterminal.fpk
./fpk/build.sh --install    # 构建 + 本机升级安装 + 版本校验（install-local）
```

### 桌面原生版（.deb）

```bash
sudo apt-get install -y qtbase5-dev cmake   # fnOS 源即可
./build.sh          # 构建 + 打包 build/pkg/fineterminal_*.deb
./build.sh --run    # 构建后直接运行调试
```

> fnOS 的 TrimRepo 精简了 `libqtermwidget5-1-dev`（只有运行库），
> `build.sh` 会自动从 Debian 镜像下载 dev 包解出头文件，无需手动处理。

## 测试

`tests/` 下为针对 fpk 后端的全链路自测（WebSocket + PTY，需 root 运行本机测试服务）：

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
src/main.cpp             入口，启动锁
src/mainwindow.{h,cpp}   主窗口：多标签 / 工具栏 / 快捷键 / 空闲锁定
src/settings.{h,cpp}     QSettings 持久化（外观 / 行为 / 密码哈希 / 快捷命令）
src/settingsdialog.{h,cpp}  设置对话框（外观、行为、快捷命令、安全）
src/lockscreen.{h,cpp}   锁屏 / 首次设密对话框
packaging/               .desktop 桌面入口
resources/               SVG 图标与资源
```

## 已知限制

- 仅 amd64（fnOS 常见架构），arm64 需换对应 dev 包重编
- 锁屏为应用级保护，退出应用后仍受系统账户保护
