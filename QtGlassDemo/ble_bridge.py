"""
OpenGlass BLE 桥接脚本
在后台运行，接收 ESP32 照片数据，转发给 Qt 桌面端
启动方式: python ble_bridge.py
"""
import asyncio
import struct
import sys
import websockets

# ====== ESP32 BLE 设备配置 ======
TARGET_NAME = "OpenGlass"          # ESP32 蓝牙名称
TARGET_ADDRESS = "7C:4F:AD:20:9C:59"  # ESP32 蓝牙地址 (从 chrome://bluetooth-internals 获取)

# BLE UUID
SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
PHOTO_DATA_UUID = "19b10005-e8f2-537e-4f6c-d104768a1214"
PHOTO_CONTROL_UUID = "19b10006-e8f2-537e-4f6c-d104768a1214"

QT_WS_URL = "ws://localhost:9000"

CHUNK_SIZE = 200

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    print("请先安装 bleak: python -m pip install bleak")
    sys.exit(1)


class PhotoAssembler:
    """缓冲桶：接收 BLE 分片包，拼装完整 JPEG，通过 WebSocket 发给 Qt"""

    def __init__(self):
        self.chunks = {}
        self.ws = None

    async def connect_ws(self):
        """连接 Qt WebSocket 服务器（带重试）"""
        while True:
            try:
                self.ws = await websockets.connect(QT_WS_URL, max_size=10*1024*1024)
                print(f"[WS] Connected to Qt: {QT_WS_URL}")
                return
            except Exception:
                print(f"[WS] Waiting for Qt server... ({QT_WS_URL})")
                await asyncio.sleep(2)

    def add_chunk(self, packet_id: int, data: bytes):
        """添加一个 BLE 数据包"""
        # 收到 chunk 0 = 新照片开始
        if packet_id == 0 and self.chunks:
            self.assemble()
        self.chunks[packet_id] = data

    def end_of_photo(self):
        """收到结束标记 [FF, FF]"""
        self.assemble()

    def assemble(self):
        """拼装照片并发送给 Qt"""
        if not self.chunks:
            return

        ids = sorted(self.chunks.keys())
        last_id = ids[-1]
        total_size = last_id * CHUNK_SIZE + len(self.chunks[last_id])
        buffer = bytearray(total_size)

        gaps = 0
        for i in range(len(ids) - 1):
            if ids[i+1] - ids[i] > 1:
                gaps += ids[i+1] - ids[i] - 1

        for pid in ids:
            offset = pid * CHUNK_SIZE
            chunk = self.chunks[pid]
            buffer[offset:offset+len(chunk)] = chunk

        jpeg = bytes(buffer)
        print(f"[Photo] {len(jpeg)} bytes, {len(ids)} chunks, {gaps} gaps | JPEG: {jpeg[:4].hex()}")

        self.chunks.clear()

        # 异步发送给 Qt
        if self.ws:
            asyncio.create_task(self._send_to_qt(jpeg))

    async def _send_to_qt(self, jpeg: bytes):
        try:
            await self.ws.send(jpeg)
            print(f"[WS] Sent {len(jpeg)} bytes to Qt")
        except Exception as e:
            print(f"[WS] Send failed: {e}")


async def ble_handler(client: BleakClient, assembler: PhotoAssembler):
    """BLE 数据回调"""
    def callback(_handle: int, data: bytearray):
        if len(data) < 2:
            return
        b0, b1 = data[0], data[1]
        if b0 == 0xFF and b1 == 0xFF:
            assembler.end_of_photo()
        else:
            packet_id = b0 + (b1 << 8)
            assembler.add_chunk(packet_id, bytes(data[2:]))

    # 订阅照片数据
    await client.start_notify(PHOTO_DATA_UUID, callback)
    print("[BLE] Subscribed to photo data")

    # 启动拍照：每 5 秒拍一张
    services = client.services
    for s in services:
        for c in s.characteristics:
            if c.uuid == PHOTO_CONTROL_UUID:
                await client.write_gatt_char(c, b'\x05', response=False)
                print("[BLE] Started photo capture (5s interval)")
                break

    # 保持连接
    try:
        while client.is_connected:
            await asyncio.sleep(1)
    except Exception:
        pass


async def main():
    assembler = PhotoAssembler()

    print(f"[BLE] Looking for: {TARGET_NAME} ({TARGET_ADDRESS})")

    # 寻找 ESP32
    device = None
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    for d, adv in devices.values():
        if d.name and TARGET_NAME.lower() in d.name.lower():
            device = d
            print(f"[BLE] Found: {d.name} [{d.address}]")
            break

    if not device:
        print(f"[BLE] {TARGET_NAME} not found. Is the ESP32 powered on?")
        print("[BLE] Retrying every 3 seconds... press Ctrl+C to stop")
        while not device:
            await asyncio.sleep(3)
            devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
            for d, adv in devices.values():
                if d.name and TARGET_NAME.lower() in d.name.lower():
                    device = d
                    break
        print(f"[BLE] Found: {device.name} [{device.address}]")

    # 连接 WebSocket
    await assembler.connect_ws()

    # 连接 BLE
    async with BleakClient(device.address, timeout=30.0) as client:
        print(f"[BLE] Connected: {client.is_connected}")
        await ble_handler(client, assembler)

    print("[BLE] Disconnected. Restarting in 3s...")
    await asyncio.sleep(3)
    # 递归重启
    await main()


if __name__ == "__main__":
    print("=" * 50)
    print("  OpenGlass BLE Bridge")
    print("  ESP32 -> Python -> WebSocket -> Qt")
    print("=" * 50)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
