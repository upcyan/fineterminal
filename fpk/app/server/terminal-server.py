#!/usr/bin/env python3
# FineTerminal fpk 后端：Unix socket 上的 HTTP 静态服务 + WebSocket + PTY 终端会话
# 仅用 Python3 标准库，无第三方依赖。
#
# 会话模型（保留会话）：
# - 会话与页面连接解耦：页面关闭（WS 断开）且"保留会话"开启时，shell 继续存活；
#   页面重开后通过 list/attach 重新绑定，标签与会话自动恢复。
# - 脱离超过 DETACH_GRACE 秒仍未重连的会话被回收，避免残留 shell。
# - "保留会话"关闭时，WS 断开即杀掉该连接创建的会话（旧行为）。
# - 注意：终端服务进程本身重启会导致全部会话丢失（master fd 关闭）。
#
# 安全机制：
# 1. 访问入口只在 fnOS 统一网关后（NAS 登录态鉴权），本服务仅监听本地 Unix socket。
# 2. WebSocket 握手动态同源判定（DSH 同款：Sec-Fetch-Site 自证 + X-Forwarded-Host
#    兜底比对），无静态域名白名单，fn Connect / 中继 / 局域网域名天然满足。
# 3. 会话按网关身份（X-Trim-Userid 头）隔离：list/attach/输入只对自己的会话生效，
#    普通用户之间互相不可见，防止互拿 root shell。
# 4. 可选应用级密码锁：设置后所有新连接必须先通过 auth 才能 list/attach/输入，
#    密码只存加盐哈希；连续失败节流延迟。
import asyncio
import base64
import fcntl
import hashlib
import json
import os
import signal
import struct
import sys
import termios
import time
import urllib.parse

SOCKET_PATH = os.environ.get("SOCKET_PATH", "./app.sock")
WWW_ROOT = os.environ.get("HTTP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "../www"))
SHELL = os.environ.get("FINETERMINAL_SHELL", "/bin/bash")
DETACH_GRACE = 600  # 脱离 10 分钟未重连则回收
HIST_CAP = 512 * 1024  # 每会话输出历史上限（附着时回放用）
CONF_PATH = os.path.join(os.path.dirname(os.path.abspath(SOCKET_PATH)) or ".", "sessconf.json")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# key "user:uid" -> {"pid","master","ws","title","detach","hist","user","uid"}
sessions = {}
persist_sessions = True
pw_hash = b""
pw_salt = b""

# 页面能力令牌：服务端发 HTML 时注入一次性 token，WS 握手必须携带。
# 同源页面才能拿到 token（跨站脚本读不到），因此天然防跨站 WS 劫持，
# 且与接入域名完全无关（局域网 / fn Connect / 中继 / 未来新域名统统天然满足）。
TOKENS = {}  # token -> 签发时间
TOKEN_TTL = 12 * 3600


def issue_token():
    now = time.time()
    token = os.urandom(16).hex()
    TOKENS[token] = now
    # 清理过期令牌
    for t in [k for k, v in TOKENS.items() if now - v > TOKEN_TTL]:
        TOKENS.pop(t, None)
    # 防内存膨胀：最多保留 500 个
    while len(TOKENS) > 500:
        oldest = min(TOKENS, key=lambda k: TOKENS[k])
        TOKENS.pop(oldest, None)
    return token


def token_valid(token):
    if not token or token not in TOKENS:
        return False
    if time.time() - TOKENS[token] > TOKEN_TTL:
        TOKENS.pop(token, None)
        return False
    TOKENS[token] = time.time()  # 滑动续期：长期使用的页面不掉线
    return True


def log(msg):
    sys.stderr.write("%s fineterminal-server: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    sys.stderr.flush()


def ukey(user, uid):
    return "%s:%d" % (user, uid)


# ---------- 配置与密码 ----------

def load_conf():
    global persist_sessions, pw_hash, pw_salt
    try:
        with open(CONF_PATH, "r") as f:
            conf = json.load(f)
        persist_sessions = bool(conf.get("persist", True))
        pw_hash = bytes(str(conf.get("password_hash", "")), "utf-8")
        pw_salt = bytes(str(conf.get("password_salt", "")), "utf-8")
    except Exception:
        persist_sessions = True


def save_conf():
    try:
        with open(CONF_PATH, "w") as f:
            json.dump({
                "persist": persist_sessions,
                "password_hash": pw_hash.decode("utf-8", "replace"),
                "password_salt": pw_salt.decode("utf-8", "replace"),
            }, f)
        os.chmod(CONF_PATH, 0o600)
    except Exception as e:
        log("save conf failed: %s" % e)


def hash_password(plain, salt_hex):
    # 与 Qt 桌面版一致：加盐 + 万轮 SHA-256
    data = salt_hex + plain.encode("utf-8")
    for _ in range(10000):
        data = hashlib.sha256(data).digest()
    return data.hex().encode("utf-8")


def has_password():
    return bool(pw_hash)


def verify_password(plain):
    if not pw_hash:
        return True
    return hash_password(plain, pw_salt) == pw_hash


def set_password(plain):
    global pw_hash, pw_salt
    if not plain:
        pw_hash = b""
        pw_salt = b""
    else:
        pw_salt = os.urandom(16).hex().encode("utf-8")
        pw_hash = hash_password(plain, pw_salt)
    save_conf()


# ---------- PTY 会话 ----------

def pty_pair():
    import pty as _pty
    return _pty.openpty()


def set_winsize(fd, cols, rows):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def spawn_shell(cols, rows, shell):
    master, slave = pty_pair()
    pid = os.fork()
    if pid == 0:  # 子进程
        os.close(master)
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        if slave > 2:
            os.close(slave)
        env = {
            "TERM": "xterm-256color",
            "HOME": "/root",
            "USER": "root",
            "SHELL": shell,
            "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": os.environ.get("LANG", "zh_CN.UTF-8"),
        }
        try:
            os.execve(shell, [shell, "-l"], env)
        except Exception:
            os._exit(127)
    os.close(slave)
    set_winsize(master, cols, rows)
    return pid, master


def reap(key):
    sess = sessions.pop(key, None)
    if not sess:
        return
    fd = sess["master"]
    # 关键：关闭前必须注销 asyncio reader。否则 fd 号被新会话复用时，
    # selector 里残留的旧键会让 add_reader 走"事件掩码未变"分支而跳过
    # epoll_ctl，新会话的输出将永远不会触发回调（页面上表现为无输出）。
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.remove_reader(fd)
    except Exception:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.waitpid(sess["pid"], os.WNOHANG)
    except ChildProcessError:
        pass


def kill_session(key):
    sess = sessions.get(key)
    if not sess:
        return
    try:
        os.kill(sess["pid"], signal.SIGHUP)
    except ProcessLookupError:
        pass
    reap(key)


async def pty_write(fd, data):
    """向非阻塞 PTY 完整写入：处理部分写与 EAGAIN（队列满），带超时兜底。"""
    off = 0
    deadline = time.time() + 5
    while off < len(data):
        try:
            n = os.write(fd, data[off:])
            if n == 0:
                return
            off += n
        except BlockingIOError:
            if time.time() > deadline:
                log("pty write timeout, dropped %d/%d bytes" % (len(data) - off, len(data)))
                return
            await asyncio.sleep(0.01)
        except OSError as ex:
            if os.environ.get("FINETERMINAL_DEBUG"):
                log("pty write err: %s" % ex)
            return


def session_list(user):
    return [
        {"id": s["uid"], "title": s.get("title", "")}
        for s in sessions.values()
        if s.get("user") == user
    ]


def start_pty_reader(key):
    """独立于任何 WS 连接的 PTY 读取任务：输出发送给会话当前绑定的 WS。"""
    sess = sessions.get(key)
    if not sess:
        return
    master = sess["master"]
    uid = sess["uid"]
    loop = asyncio.get_event_loop()

    async def push(chunk):
        cur = sessions.get(key)
        if not cur or not cur.get("ws"):
            return
        target = cur["ws"]
        if not target.alive:
            return
        await target.send_binary(struct.pack(">I", uid) + chunk)

    def on_read():
        try:
            data = os.read(master, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError as e:
            if os.environ.get("FINETERMINAL_DEBUG"):
                log("read err key=%s fd=%d: %s" % (key, master, e))
            try:
                loop.remove_reader(master)
            except Exception:
                pass
            return
        if os.environ.get("FINETERMINAL_DEBUG"):
            log("read key=%s fd=%d n=%d" % (key, master, len(data)))
        if not data:
            try:
                loop.remove_reader(master)
            except Exception:
                pass
            return
        # 同步追加到会话输出历史（脱离期间也保留，附着时回放）
        cur = sessions.get(key)
        if cur is not None:
            h = cur.setdefault("hist", bytearray())
            h.extend(data)
            if len(h) > HIST_CAP:
                del h[:-HIST_CAP]
        asyncio.ensure_future(push(data))

    loop.add_reader(master, on_read)
    if os.environ.get("FINETERMINAL_DEBUG"):
        log("reader registered key=%s fd=%d" % (key, master))


def watch_child(key, uid, pid):
    async def _watch():
        while True:
            await asyncio.sleep(1)
            cur = sessions.get(key)
            if not cur or cur.get("pid") != pid:
                # 会话已回收，或该 id 已被新会话复用：本监控失效，勿误伤新会话
                return
            try:
                wpid, st = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                wpid, st = pid, 0
            if wpid == pid and wpid != 0:
                cur = sessions.get(key)
                if cur and cur.get("pid") == pid:
                    target = cur.get("ws")
                    if target and target.alive:
                        try:
                            code = os.waitstatus_to_exitcode(st)
                        except Exception:
                            code = 0
                        await target.send_text(json.dumps({"type": "exit", "id": uid, "code": code}))
                    reap(key)
                return
    asyncio.ensure_future(_watch())


async def reaper():
    """定期回收脱离过久的会话。"""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for key in list(sessions.keys()):
            sess = sessions.get(key)
            if not sess:
                continue
            if sess.get("ws") is None and sess.get("detach") and now - sess["detach"] > DETACH_GRACE:
                log("reap detached session %s (age %ds)" % (key, int(now - sess["detach"])))
                kill_session(key)


# ---------- WebSocket ----------

class WS:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.alive = True
        self.tasks = []

    async def send_frame(self, opcode, payload):
        if not self.alive:
            return
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([n])
        elif n < 65536:
            header += bytes([126]) + struct.pack(">H", n)
        else:
            header += bytes([127]) + struct.pack(">Q", n)
        try:
            self.writer.write(header + payload)
            await self.writer.drain()
        except (ConnectionError, BrokenPipeError):
            self.alive = False

    async def send_text(self, s):
        await self.send_frame(0x1, s.encode())

    async def send_binary(self, b):
        await self.send_frame(0x2, b)

    async def recv_frame(self):
        head = await self.reader.readexactly(2)
        opcode = head[0] & 0x0F
        masked = head[1] & 0x80
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await self.reader.readexactly(8))[0]
        mask = await self.reader.readexactly(4) if masked else None
        payload = await self.reader.readexactly(n) if n else b""
        if mask:
            payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        return opcode, payload


async def handle_ws(ws, user):
    my_sessions = set()
    authed = not has_password()
    auth_fails = 0

    async def notify_locked(bad=False):
        await ws.send_text(json.dumps({"type": "auth_state", "locked": True, "bad": bad}))

    async def handle_control(text):
        nonlocal authed, auth_fails
        global persist_sessions
        try:
            msg = json.loads(text)
        except ValueError:
            return
        t = msg.get("type")

        # 应用密码锁：未认证前只接受 auth
        if t == "auth":
            plain = str(msg.get("password", ""))
            if verify_password(plain):
                authed = True
                auth_fails = 0
                log("auth ok user=%s" % user)
                await ws.send_text(json.dumps({"type": "unlock"}))
            else:
                auth_fails += 1
                log("auth fail user=%s fails=%d" % (user, auth_fails))
                await asyncio.sleep(min(0.5 * auth_fails, 3.0))  # 失败节流
                await notify_locked(bad=True)
            return
        if not authed:
            await notify_locked()
            return

        if t == "create":
            uid = int(msg.get("id", 0))
            cols = int(msg.get("cols", 80))
            rows = int(msg.get("rows", 24))
            shell = msg.get("shell") or SHELL
            shell = shell if shell.startswith("/") and os.path.exists(shell) else SHELL
            key = ukey(user, uid)
            if key in sessions:
                kill_session(key)  # 同 id 重复创建：先清理旧会话
            log("create %s shell=%s" % (key, shell))
            pid, master = spawn_shell(cols, rows, shell)
            flags = fcntl.fcntl(master, fcntl.F_GETFL)
            fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            sessions[key] = {"pid": pid, "master": master, "ws": ws,
                             "title": "", "detach": None, "hist": bytearray(),
                             "user": user, "uid": uid}
            my_sessions.add(key)
            await ws.send_text(json.dumps({"type": "created", "id": uid}))
            start_pty_reader(key)
            watch_child(key, uid, pid)

        elif t == "list":
            await ws.send_text(json.dumps({
                "type": "sessions",
                "items": session_list(user),
                "persist": persist_sessions,
            }))

        elif t == "attach":
            uid = int(msg.get("id", 0))
            key = ukey(user, uid)
            sess = sessions.get(key)
            if sess:
                my_sessions.add(key)
                log("attach %s" % key)
                # 回放：横幅+历史快照，循环补发直到追平（消除回放窗口内的输出
                # 丢失），追平后与绑定之间不再有 await —— 绑定后新输出实时投递
                banner = "\r\n\x1b[33m== 已恢复之前的会话，继续使用 ==\x1b[0m\r\n"
                h_sent = 0
                blob = banner.encode() + bytes(sess.get("hist", b""))
                h_sent = len(sess.get("hist", b""))
                await ws.send_binary(struct.pack(">I", uid) + blob)
                while True:
                    cur = bytes(sess.get("hist", b""))
                    if len(cur) <= h_sent:
                        break
                    await ws.send_binary(struct.pack(">I", uid) + cur[h_sent:])
                    h_sent = len(cur)
                sess["ws"] = ws
                sess["detach"] = None
                # 强制 TUI 全量重绘：制造一次尺寸变化触发 SIGWINCH
                cols = int(msg.get("cols", 0))
                rows = int(msg.get("rows", 0))
                if cols > 0 and rows > 1:
                    set_winsize(sess["master"], cols, rows - 1)

                    async def _restore_size():
                        await asyncio.sleep(0.15)
                        cur = sessions.get(key)
                        if cur and cur.get("ws") is ws:
                            set_winsize(cur["master"], cols, rows)
                    asyncio.ensure_future(_restore_size())
            else:
                await ws.send_text(json.dumps({"type": "missing", "id": uid}))

        elif t == "title":
            uid = int(msg.get("id", 0))
            sess = sessions.get(ukey(user, uid))
            if sess:
                sess["title"] = str(msg.get("title", ""))[:200]

        elif t == "config":
            if "persist" in msg:
                persist_sessions = bool(msg["persist"])
                save_conf()
                log("persist=%s" % persist_sessions)
            if "password" in msg:
                # 仅已认证连接可改密码（无密码时天然通过）
                set_password(str(msg.get("password", "")))
                log("password updated user=%s set=%s" % (user, bool(msg.get("password"))))
                await ws.send_text(json.dumps({"type": "pw_set", "set": bool(msg.get("password"))}))

        elif t == "resize":
            uid = int(msg.get("id", 0))
            sess = sessions.get(ukey(user, uid))
            if sess:
                set_winsize(sess["master"], int(msg.get("cols", 80)), int(msg.get("rows", 24)))

        elif t == "kill":
            uid = int(msg.get("id", 0))
            key = ukey(user, uid)
            my_sessions.discard(key)
            kill_session(key)

        elif t == "ping":
            await ws.send_text(json.dumps({"type": "pong"}))

    try:
        # 保活：定期 ping 探测死链（远程/移动网络下半开连接会卡住输入）
        async def keepalive():
            while ws.alive:
                await asyncio.sleep(25)
                try:
                    await ws.send_frame(0x9, b"ka")
                except Exception:
                    ws.alive = False
                    return
        ws.tasks.append(asyncio.ensure_future(keepalive()))
        if not authed:
            await notify_locked()
        while ws.alive:
            opcode, payload = await ws.recv_frame()
            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping
                await ws.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                await handle_control(payload.decode("utf-8", "replace"))
            elif opcode == 0x2:
                # 未认证时丢弃全部输入
                if not authed:
                    continue
                if len(payload) >= 4:
                    uid = struct.unpack(">I", payload[:4])[0]
                    sess = sessions.get(ukey(user, uid))
                    if os.environ.get("FINETERMINAL_DEBUG"):
                        log("input %s:%d n=%d sess=%s" % (user, uid, len(payload) - 4, bool(sess)))
                    if sess:
                        # 完整写入循环：master 是非阻塞的，单次 os.write 可能
                        # 部分写入或 EAGAIN——旧版静默丢弃会导致粘贴内容缺失/乱码
                        await pty_write(sess["master"], payload[4:])
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        ws.alive = False
        for t in ws.tasks:
            t.cancel()
        # 会话处置：保留则脱离（shell 存活等待重连），否则按旧行为回收
        for key in my_sessions:
            sess = sessions.get(key)
            if not sess or sess.get("ws") is not ws:
                continue
            sess["ws"] = None
            sess["detach"] = time.time()
            if persist_sessions:
                log("session %s detached (persist)" % key)
            else:
                kill_session(key)


# ---------- HTTP ----------

def serve_static(path):
    if path in ("/", "") or not os.path.splitext(path)[1]:
        path = "/index.html"
    full = os.path.realpath(os.path.join(WWW_ROOT, "." + urllib.parse.unquote(path)))
    root = os.path.realpath(WWW_ROOT)
    if not full.startswith(root + os.sep) and full != root:
        return b"403", "403 Forbidden", "text/plain"
    if not os.path.isfile(full):
        return b"404", "404 Not Found", "text/plain"
    ext = os.path.splitext(full)[1].lower()
    with open(full, "rb") as f:
        body = f.read()
    if ext == ".html":
        # 注入页面能力令牌：WS 握手必须携带，跨站页面拿不到
        token = issue_token()
        marker = b"<head>"
        if marker in body:
            body = body.replace(
                marker,
                marker + b'<script>window.__FT_TOKEN="' + token.encode() + b'";</script>',
                1)
    return body, "200 OK", MIME.get(ext, "application/octet-stream")


def same_origin(headers):
    """已弃用：被页面能力令牌（issue_token / token_valid）取代。
    原因：网关会改写 Host 且不转发 Sec-Fetch-Site / X-Forwarded-Host，
    任何基于请求头的来源比对在网关层都不可靠；令牌由同源 HTML 页面
    持有，跨站拿不到，与接入域名无关。"""
    return True


async def handle_conn(reader, writer):
    try:
        line = await asyncio.wait_for(reader.readline(), 10)
        if not line:
            return
        method, target, _ = line.decode("latin1").split(" ", 2)
        path = urllib.parse.urlparse(target).path
        log("%s %s" % (method, target))
        headers = {}
        while True:
            hl = await reader.readline()
            if hl in (b"\r\n", b"\n", b""):
                break
            k, _, v = hl.decode("latin1").partition(":")
            headers[k.strip().lower()] = v.strip()

        if path.endswith("/ws") and headers.get("upgrade", "").lower() == "websocket":
            # 页面能力令牌校验：只有拿到同源 HTML 注入令牌的连接才放行
            # （令牌与接入域名无关，跨站页面无法获取）
            query = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
            ft = (query.get("ft") or [""])[0]
            if not token_valid(ft):
                log("ws rejected: invalid/missing page token (ft=%s..., origin=%s)" % (
                    ft[:8], headers.get("origin", "-")))
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            # 网关身份：会话按用户隔离
            user = (headers.get("x-trim-userid")
                    or headers.get("x-trim-username")
                    or "anon")
            log("ws upgrade user=%s token=ok" % user)

            key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            writer.write((
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
            ).encode())
            await writer.drain()
            ws = WS(reader, writer)
            await handle_ws(ws, user)
            return

        body, status, ctype = serve_static(path)
        writer.write((
            "HTTP/1.1 %s\r\n"
            "Content-Type: %s\r\n"
            "Content-Length: %d\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n" % (status, ctype, len(body))
        ).encode() + body)
        await writer.drain()
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, ConnectionError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    load_conf()
    # 清理陈旧 socket
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    os.makedirs(os.path.dirname(SOCKET_PATH) or ".", exist_ok=True)
    server = await asyncio.start_unix_server(handle_conn, path=SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o660)
    log("listening on %s (www=%s, persist=%s, password=%s)" % (
        SOCKET_PATH, WWW_ROOT, persist_sessions, has_password()))
    asyncio.ensure_future(reaper())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
