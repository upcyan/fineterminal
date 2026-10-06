#!/usr/bin/env python3
# 测试：关闭 WS 后会话保留，重连 list/attach 能恢复并继续交互
import asyncio, json, re, struct, sys

SOCK = sys.argv[1] if len(sys.argv) > 1 else "./test.sock"



async def get_token(path):
    """从服务端下发的 HTML 里提取页面能力令牌（WS 握手必须携带）。"""
    r, w = await asyncio.open_unix_connection(path)
    w.write(b"GET /index.html HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    await w.drain()
    data = b""
    while True:
        chunk = await r.read(65536)
        if not chunk:
            break
        data += chunk
    w.close()
    m = re.search(rb'__FT_TOKEN="([0-9a-f]+)"', data)
    return m.group(1).decode() if m else ""

async def ws_connect(path):
    token = await get_token(path)
    r, w = await asyncio.open_unix_connection(path)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    w.write((f"GET /ws?ft={token} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
             f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await w.drain()
    assert b"101" in await r.readline()
    while True:
        line = await r.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    return r, w


def mask_frame(opcode, payload):
    import os as _os
    mask = _os.urandom(4)
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    masked = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
    return header + mask + masked


async def send_text(w, s):
    w.write(mask_frame(0x1, s.encode()))
    await w.drain()


async def send_bin(w, b):
    w.write(mask_frame(0x2, b))
    await w.drain()


async def recv(r, timeout=8):
    async def one():
        head = await r.readexactly(2)
        op = head[0] & 0x0F
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await r.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await r.readexactly(8))[0]
        return op, (await r.readexactly(n) if n else b"")
    return await asyncio.wait_for(one(), timeout)


async def echo_ok(w, r, sid, marker):
    await send_bin(w, struct.pack(">I", sid) + ("echo %s\r" % marker).encode())
    out = b""
    while marker.encode() not in out:
        op, p = await recv(r)
        if op == 0x2 and len(p) >= 4 and struct.unpack(">I", p[:4])[0] == sid:
            out += p[4:]
        elif op == 0x1 and json.loads(p).get("type") == "exit":
            sys.exit("session exited early")
    print("echo-%s-ok" % marker)


async def main():
    # ---- 第一段连接：创建会话并验证 ----
    r1, w1 = await ws_connect(SOCK)
    await send_text(w1, json.dumps({"type": "create", "id": 1, "cols": 100, "rows": 30}))
    op, p = await recv(r1)
    assert json.loads(p)["type"] == "created"
    await echo_ok(w1, r1, 1, "BEFORE_CLOSE")
    print("phase1: create+echo ok")

    # ---- 关闭连接：服务端应保留会话 ----
    w1.close()
    await asyncio.sleep(0.5)

    # ---- 第二段连接：list + attach + 继续交互 ----
    r2, w2 = await ws_connect(SOCK)
    await send_text(w2, json.dumps({"type": "list"}))
    while True:
        op, p = await recv(r2)
        if op == 0x1:
            m = json.loads(p)
            if m.get("type") == "sessions":
                items = m["items"]
                assert m.get("persist") is True, "persist 应默认开启"
                break
    assert any(i["id"] == 1 for i in items), "list 应包含保留的会话 1, got %s" % items
    print("phase2: list restored session ok:", items)

    await send_text(w2, json.dumps({"type": "attach", "id": 1, "cols": 100, "rows": 30}))
    # 附着后服务端应立即回放 横幅+历史（含之前输出的标记）
    replay = b""
    while b"BEFORE_CLOSE" not in replay:
        op, p = await recv(r2)
        if op == 0x2 and len(p) >= 4 and struct.unpack(">I", p[:4])[0] == 1:
            replay += p[4:]
    assert "已恢复" in replay.decode("utf-8", "replace"), "回放应含横幅"
    print("phase3a: history replay ok (%d bytes)" % len(replay))

    await echo_ok(w2, r2, 1, "AFTER_RESTORE")
    print("phase3: attach+echo ok")

    # ---- config 开关 ----
    await send_text(w2, json.dumps({"type": "config", "persist": False}))
    await send_text(w2, json.dumps({"type": "list"}))
    while True:
        op, p = await recv(r2)
        if op == 0x1 and json.loads(p).get("type") == "sessions":
            assert json.loads(p)["persist"] is False, "persist 应为 False"
            break
    await send_text(w2, json.dumps({"type": "config", "persist": True}))
    print("phase4: config persist toggle ok")

    await send_text(w2, json.dumps({"type": "kill", "id": 1}))
    w2.close()
    print("ALL PERSIST TESTS PASSED")


asyncio.run(main())
