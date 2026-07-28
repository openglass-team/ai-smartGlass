"""
ESP32 PDM Mic → Opus → WebSocket 测试服务器

用法:
    pip install websockets
    python test_server.py

然后修改 ESP32 menuconfig:
    WSS_URL = ws://<你电脑的IP>:8765/audio
    WSS_SKIP_CERT_VERIFY = y
    WSS_AUTH_TOKEN = 留空（测试时不需要）

注意: 测试用 ws:// (非加密)，不需要 TLS 证书。
"""

import asyncio
import struct
import time
import websockets
from datetime import datetime

HOST = "0.0.0.0"
PORT = 8765

# 统计信息
stats = {
    "connections": 0,
    "total_packets": 0,
    "total_bytes": 0,
    "start_time": time.time(),
}


async def handle_audio(websocket):
    """接收 ESP32 发来的 Opus 音频包"""
    stats["connections"] += 1
    client_addr = websocket.remote_address
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 新连接: {client_addr}")

    # 保存收到的 opus 数据，便于后续分析
    opus_frames = []
    last_report = time.time()

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                stats["total_packets"] += 1
                stats["total_bytes"] += len(message)
                opus_frames.append(message)

                # 每秒打印一次统计
                now = time.time()
                if now - last_report >= 1.0:
                    elapsed = now - stats["start_time"]
                    kbps = (stats["total_bytes"] * 8 / 1000) / elapsed if elapsed > 0 else 0
                    print(f"  📦 packets: {stats['total_packets']:6d}  |  "
                          f"📊 {stats['total_bytes']/1024:.1f} KB  |  "
                          f"⚡ {kbps:.1f} kbps  |  "
                          f"🔊 frames: {len(opus_frames)}")
                    last_report = now

            elif isinstance(message, str):
                print(f"  📝 收到文本: {message[:100]}")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 断开: {client_addr}")
        stats["connections"] -= 1

        # 保存收到的音频数据
        if opus_frames:
            filename = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.opus"
            with open(filename, "wb") as f:
                for frame in opus_frames:
                    f.write(frame)
            total = sum(len(f) for f in opus_frames)
            print(f"  💾 已保存 {len(opus_frames)} 帧 ({total} bytes) → {filename}")


async def main():
    print("=" * 55)
    print("  ESP32 Opus Audio 测试服务器")
    print(f"  监听地址: ws://{HOST}:{PORT}/audio")
    print("=" * 55)
    print("\n请将此地址配置到 ESP32 menuconfig:")
    print(f'  WSS_URL = "ws://<你的IP>:{PORT}/audio"')
    print('  WSS_SKIP_CERT_VERIFY = y')
    print("  等待连接...\n")

    async with websockets.serve(handle_audio, HOST, PORT, max_size=10 * 1024 * 1024):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
