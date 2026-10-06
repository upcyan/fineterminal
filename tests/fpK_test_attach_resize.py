#!/usr/bin/env python3
# 测试：attach 携带尺寸后 PTY 最终尺寸正确（尺寸抖动触发 WINCH 强制重绘）
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
    w.write((f"GET /ws?ft={token} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
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
    return header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))

async def send_text(w, s):
    w.write(mask_frame(0x1, s.encode())); await w.drain()

async def send_bin(w, b):
    w.write(mask_frame(0x2, b)); await w.drain()

async def recv(r, timeout=8):
    async def one():
        head = await r.readexactly(2)
        op = head[0] & 0x0F
        n = head[1] & 0x7F
        if n == 126: n = struct.unpack(">H", await r.readexactly(2))[0]
        elif n == 127: n = struct.unpack(">Q", await r.readexactly(8))[0]
        return op, (await r.readexactly(n) if n else b"")
    return await asyncio.wait_for(one(), timeout)

async def wait_binary(r, sid, timeout=8):
    async def loop_until():
        while True:
            op, p = await recv(r, timeout)
            if op == 0x2 and len(p) >= 4 and struct.unpack(">I", p[:4])[0] == sid:
                return p[4:]
    return await asyncio.wait_for(loop_until(), timeout)

async def main():
    # 创建 100x30 会话
    r1, w1 = await ws_connect(SOCK)
    await send_text(w1, json.dumps({"type": "create", "id": 1, "cols": 100, "rows": 30}))
    op, p = await recv(r1)
    assert json.loads(p)["type"] == "created"
    await send_bin(w1, struct.pack(">I", 1) + b"stty size\r")
    out = b""
    while b"30 100" not in out:
        out += await wait_binary(r1, 1)
    print("created size ok: 30 100")
    w1.close()
    await asyncio.sleep(0.5)

    # 附着到不同尺寸 80x40：应先抖到 39 行再复原 40 行
    r2, w2 = await ws_connect(SOCK)
    await send_text(w2, json.dumps({"type": "list"}))
    while True:
        op, p = await recv(r2)
        if op == 0x1 and json.loads(p).get("type") == "sessions":
            assert any(i["id"] == 1 for i in json.loads(p)["items"])
            break
    await send_text(w2, json.dumps({"type": "attach", "id": 1, "cols": 80, "rows": 40}))
    await asyncio.sleep(0.5)  # 等抖动复原完成
    await send_bin(w2, struct.pack(">I", 1) + b"stty size\r")
    out = b""
    while b"40 80" not in out:
        out += await wait_binary(r2, 1)
    print("attached size ok: 40 80")

    # 同尺寸附着 80x40：抖动 39→40 应仍触发尺寸变化（最终不变）
    w2.close()
    await asyncio.sleep(0.5)
    r3, w3 = await ws_connect(SOCK)
    await send_text(w3, json.dumps({"type": "attach", "id": 1, "cols": 80, "rows": 40}))
    await asyncio.sleep(0.5)
    await send_bin(w3, struct.pack(">I", 1) + b"stty size\r")
    out = b""
    while b"40 80" not in out:
        out += await wait_binary(r3, 1)
    print("same-size attach ok")
    await send_text(w3, json.dumps({"type": "kill", "id": 1}))
    w3.close()
    print("ALL RESIZE-ON-ATTACH TESTS PASSED")

asyncio.run(main())
