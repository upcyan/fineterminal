#!/usr/bin/env python3
# 测试：大段输入不丢字节（非阻塞 PTY 部分写/EAGAIN）+ 大输出帧 + 回放完整性
import asyncio, json, os, re, struct, sys, os

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
    w.write(((f"GET /ws?ft={token} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n".encode()) +
             (b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")))
    await w.drain()
    assert b"101" in await r.readline()
    while True:
        line = await r.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    return r, w

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
    w.write(mask_frame(0x1, s.encode())); await w.drain()

async def send_bin(w, b):
    w.write(mask_frame(0x2, b)); await w.drain()

async def recv(r, timeout=15):
    async def one():
        head = await r.readexactly(2)
        op = head[0] & 0x0F
        n = head[1] & 0x7F
        if n == 126: n = struct.unpack(">H", await r.readexactly(2))[0]
        elif n == 127: n = struct.unpack(">Q", await r.readexactly(8))[0]
        return op, (await r.readexactly(n) if n else b"")
    return await asyncio.wait_for(one(), timeout)

async def wait_marker(r, sid, marker, timeout=20):
    out = b""
    while marker not in out:
        op, p = await recv(r, timeout)
        if op == 0x2 and len(p) >= 4 and struct.unpack(">I", p[:4])[0] == sid:
            out += p[4:]
        elif op == 0x1 and json.loads(p).get("type") == "exit":
            sys.exit("session exited early: %r" % out[-200:])
    return out

async def main():
    r, w = await ws_connect(SOCK)
    await send_text(w, json.dumps({"type": "create", "id": 1, "cols": 100, "rows": 30}))
    while True:
        op, p = await recv(r)
        if op == 0x1 and json.loads(p)["type"] == "created":
            break

    # ---- 1. 30KB 单帧输入（N_TTY 队列仅 4KB，必然触发部分写/EAGAIN）----
    NLINES = 100
    lines = "\n".join("A" * 300 for _ in range(NLINES))
    expected = NLINES * 301  # 300 字符 + 换行
    payload = ("cat > /tmp/pt_in.txt <<'XEOF'\n" + lines + "\nXEOF\nwc -c < /tmp/pt_in.txt\n").encode()
    assert len(payload) > 30000, len(payload)
    await send_bin(w, struct.pack(">I", 1) + payload)
    out = await wait_marker(r, 1, str(expected).encode())
    print("input-integrity ok: %d bytes survived single-frame paste (%d bytes sent)" % (expected, len(payload)))

    # ---- 2. 200KB 大输出（走 8 字节长度帧路径；marker 拼接构造避免被命令回显提前命中）----
    await send_bin(w, struct.pack(">I", 1) + b"python3 -c \"print('Z'*200000); print('OUT_' + 'BIG' + '_OK')\"\r")
    out = await wait_marker(r, 1, b"OUT_BIG_OK", timeout=30)
    zcount = out.count(b"Z")
    print("big-output ok: received %d Z chars (expect 200000)" % zcount)
    assert zcount >= 200000, "大输出丢字节: %d" % zcount

    # ---- 3. 断开重连回放包含全部历史 ----
    w.close()
    await asyncio.sleep(0.5)
    r2, w2 = await ws_connect(SOCK)
    await send_text(w2, json.dumps({"type": "list"}))
    while True:
        op, p = await recv(r2)
        if op == 0x1 and json.loads(p).get("type") == "sessions":
            assert any(i["id"] == 1 for i in json.loads(p)["items"])
            break
    await send_text(w2, json.dumps({"type": "attach", "id": 1, "cols": 100, "rows": 30}))
    replay = await wait_marker(r2, 1, b"OUT_BIG_OK")
    assert "已恢复".encode() in replay, "回放应含横幅"
    print("replay-integrity ok: %d bytes replayed incl. big output" % len(replay))

    await send_text(w2, json.dumps({"type": "kill", "id": 1}))
    w2.close()
    try: os.remove("/tmp/pt_in.txt")
    except OSError: pass
    print("ALL INPUT TESTS PASSED")

asyncio.run(main())
