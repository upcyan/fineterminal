#!/usr/bin/env python3
# 自测：连接 ws、创建会话、执行命令、读回输出
import asyncio, json, os, re, struct, sys

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
    w.write((f"GET /ws?ft={token} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await w.drain()
    status = await r.readline()
    assert b"101" in status, status
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
        payload = await r.readexactly(n) if n else b""
        return op, payload
    return await asyncio.wait_for(one(), timeout)

async def main():
    r, w = await ws_connect(SOCK)
    print("handshake-ok")
    await send_text(w, json.dumps({"type": "create", "id": 1, "cols": 100, "rows": 30}))
    op, p = await recv(r)
    assert json.loads(p)["type"] == "created", p
    print("created-ok")
    await send_bin(w, struct.pack(">I", 1) + b"echo FINETERMINAL_OK_12345\r")
    out = b""
    while b"FINETERMINAL_OK_12345" not in out:
        op, p = await recv(r)
        if op == 0x2:
            sid = struct.unpack(">I", p[:4])[0]
            assert sid == 1
            out += p[4:]
        else:
            m = json.loads(p)
            if m.get("type") == "exit":
                sys.exit("exited early")
    print("pty-output-ok:", b"FINETERMINAL_OK_12345" in out)
    # resize
    await send_text(w, json.dumps({"type": "resize", "id": 1, "cols": 120, "rows": 40}))
    # 结束会话
    await send_text(w, json.dumps({"type": "kill", "id": 1}))
    print("ALL TESTS PASSED")
    w.close()

asyncio.run(main())
