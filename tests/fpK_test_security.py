#!/usr/bin/env python3
# 安全测试：Origin 校验、按用户隔离会话、应用密码锁
import asyncio, base64, hashlib, json, re, struct, sys, os

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

async def ws_connect(path, headers=None):
    token = await get_token(path)
    r, w = await asyncio.open_unix_connection(path)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    extra = ""
    for k, v in (headers or {}).items():
        extra += "%s: %s\r\n" % (k, v)
    w.write((
        "GET /ws?ft=%s HTTP/1.1\r\nHost: nas.local:5666\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n%s\r\n" % (token, key, extra)
    ).encode())
    await w.drain()
    status = await r.readline()
    while True:
        line = await r.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    return status.decode(), r, w


def mask_frame(opcode, payload):
    mask = os.urandom(4)
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))


async def send_text(w, s):
    w.write(mask_frame(0x1, s.encode()))
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


async def next_json(r, timeout=8):
    while True:
        op, p = await recv(r, timeout)
        if op == 0x1:
            return json.loads(p)


async def main():
    # ---- 1. 页面能力令牌（取代 Origin/域名判定：跨站页面拿不到令牌）----
    # 无令牌 → 403（无论 Origin 是什么）
    r1, w1 = await asyncio.open_unix_connection(SOCK)
    w1.write(("GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
              "Connection: Upgrade\r\nOrigin: http://evil.example\r\n"
              "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await w1.drain()
    st = (await r1.readline()).decode()
    assert "403" in st, "无令牌应被拒绝, got: %s" % st
    w1.close()
    print("sec1: no token rejected ok")

    # 伪造令牌 → 403
    fake = "0" * 32
    r2, w2 = await asyncio.open_unix_connection(SOCK)
    w2.write(("GET /ws?ft=" + fake + " HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
              "Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
              "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    await w2.drain()
    st = (await r2.readline()).decode()
    assert "403" in st, "伪造令牌应被拒绝, got: %s" % st
    w2.close()
    print("sec1b: fake token rejected ok")

    # 合法令牌：任何接入域名（含未来新域名、恶意 Origin）都放行——令牌即同源证明
    token = await get_token(SOCK)
    r3, w3 = await asyncio.open_unix_connection(SOCK)
    w3.write(("GET /ws?ft=" + token + " HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
              "Connection: Upgrade\r\nOrigin: http://evil.example\r\n"
              "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await w3.drain()
    st = (await r3.readline()).decode()
    assert "101" in st, "合法令牌应放行（Origin 不参与判定）, got: %s" % st
    w3.close()
    print("sec2: valid token allowed (origin-independent) ok")

    # 合法令牌 + 从未见过的新接入域名 → 放行（动态、无白名单）
    r4, w4 = await asyncio.open_unix_connection(SOCK)
    w4.write(("GET /ws?ft=" + token + " HTTP/1.1\r\nHost: nas.local:5666\r\nUpgrade: websocket\r\n"
              "Connection: Upgrade\r\nOrigin: https://brand-new-relay.example-cdn.io:8443\r\n"
              "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await w4.drain()
    st = (await r4.readline()).decode()
    assert "101" in st, "新域名+合法令牌应放行, got: %s" % st
    w4.close()
    print("sec2b: unknown future origin with valid token allowed ok")


    # ---- 2. 按网关用户隔离 ----
    _, ra, wa = await ws_connect(SOCK, {"X-Trim-Userid": "1001"})
    await send_text(wa, json.dumps({"type": "create", "id": 1, "cols": 80, "rows": 24}))
    m = await next_json(ra)
    assert m["type"] == "created"
    print("sec3: user A created session ok")

    _, rb, wb = await ws_connect(SOCK, {"X-Trim-Userid": "2002"})
    await send_text(wb, json.dumps({"type": "list"}))
    m = await next_json(rb)
    assert m["type"] == "sessions" and m["items"] == [], \
        "用户 B 不应看到用户 A 的会话, got %s" % m
    print("sec4: user B list isolated ok")

    # B 尝试 attach A 的会话 → missing；A 会话不受影响
    await send_text(wb, json.dumps({"type": "attach", "id": 1, "cols": 80, "rows": 24}))
    m = await next_json(rb)
    assert m["type"] in ("missing", "auth_state", "sessions"), "unexpected: %s" % m
    print("sec5: cross-user attach blocked ok (%s)" % m["type"])

    # B 尝试 kill A 的会话 → A 仍存活（键不同）
    await send_text(wb, json.dumps({"type": "kill", "id": 1}))
    await send_text(wa, json.dumps({"type": "list"}))
    m = await next_json(ra)
    assert m["type"] == "sessions" and len(m["items"]) == 1, \
        "跨用户 kill 不应生效, got %s" % m
    print("sec6: cross-user kill blocked ok")

    await send_text(wa, json.dumps({"type": "kill", "id": 1}))
    wa.close()
    wb.close()
    await asyncio.sleep(0.3)

    # ---- 3. 应用密码锁 ----
    _, rc, wc = await ws_connect(SOCK, {"X-Trim-Userid": "1001"})
    await send_text(wc, json.dumps({"type": "config", "password": "s3cret"}))
    m = await next_json(rc)
    assert m["type"] == "pw_set" and m["set"] is True
    print("sec7: password set ok")

    # 新连接 → 锁定
    _, rd, wd = await ws_connect(SOCK, {"X-Trim-Userid": "1001"})
    m = await next_json(rd)
    assert m["type"] == "auth_state" and m["locked"] is True, "新连接应锁定, got %s" % m
    # 锁定中 list 被拒（只回 auth_state）
    await send_text(wd, json.dumps({"type": "list"}))
    m = await next_json(rd)
    assert m["type"] == "auth_state", "锁定中 list 应被拒绝, got %s" % m
    print("sec8: locked connection rejects commands ok")

    # 错误密码
    await send_text(wd, json.dumps({"type": "auth", "password": "wrong"}))
    m = await next_json(rd, timeout=15)
    assert m["type"] == "auth_state", "错误密码应保持锁定, got %s" % m
    print("sec9: wrong password rejected ok")

    # 正确密码
    await send_text(wd, json.dumps({"type": "auth", "password": "s3cret"}))
    m = await next_json(rd, timeout=15)
    assert m["type"] == "unlock", "正确密码应解锁, got %s" % m
    await send_text(wd, json.dumps({"type": "list"}))
    m = await next_json(rd)
    assert m["type"] == "sessions", "解锁后 list 应可用, got %s" % m
    print("sec10: correct password unlocks ok")

    # 清除密码，恢复默认（保证后续/用户环境干净）
    await send_text(wd, json.dumps({"type": "config", "password": ""}))
    m = await next_json(rd)
    assert m["type"] == "pw_set" and m["set"] is False
    print("sec11: password cleared ok")

    wd.close()
    wc.close()
    print("ALL SECURITY TESTS PASSED")


asyncio.run(main())
