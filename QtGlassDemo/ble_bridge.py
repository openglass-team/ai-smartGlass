"""
OpenGlass BLE 桥接脚本
启动方式: python ble_bridge.py

功能：
  - ESP32 照片数据接收 → WebSocket → Qt 桌面端
  - ESP32 麦克风数据接收 → 转发给 AI 处理
  - TTS 音频 → BLE → ESP32 → 骨传导喇叭播放
"""
import asyncio
import struct
import sys
import websockets
import json
import wave
import io
import os

# ====== ESP32 BLE 设备配置 ======
TARGET_NAME = "OpenGlass"
TARGET_ADDRESS = "7C:4F:AD:20:9C:59"

# BLE UUID (与固件端 firmware.ino 保持一致)
SERVICE_UUID        = "19b10000-e8f2-537e-4f6c-d104768a1214"
AUDIO_DATA_UUID     = "19b10001-e8f2-537e-4f6c-d104768a1214"  # 上行：麦克风 PCM (NOTIFY)
AUDIO_CODEC_UUID    = "19b10002-e8f2-537e-4f6c-d104768a1214"  # 编解码器 ID (READ)
AUDIO_PLAYBACK_UUID = "19b10004-e8f2-537e-4f6c-d104768a1214"  # 下行：TTS 播放 (WRITE)
PHOTO_DATA_UUID     = "19b10005-e8f2-537e-4f6c-d104768a1214"  # 照片 (NOTIFY)
PHOTO_CONTROL_UUID  = "19b10006-e8f2-537e-4f6c-d104768a1214"  # 拍照控制 (WRITE)

QT_WS_URL = "ws://localhost:9000"

CHUNK_SIZE = 200
AUDIO_SAMPLE_RATE = 16000  # 固件端麦克风采样率

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    print("请先安装 bleak: python -m pip install bleak")
    sys.exit(1)


# ========================== 音频数据接收器 ==========================

class AudioReceiver:
    """接收 ESP32 麦克风 PCM 数据，攒够一定量后交给 AI 处理"""

    def __init__(self, sample_rate=AUDIO_SAMPLE_RATE, channels=1, sample_width=2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.buffer = bytearray()
        self.accumulated_seconds = 0.0

    def append(self, pcm_bytes: bytes):
        """追加 PCM 数据"""
        self.buffer.extend(pcm_bytes)
        self.accumulated_seconds = len(self.buffer) / (
            self.sample_rate * self.channels * self.sample_width)

    def clear(self):
        self.buffer = bytearray()
        self.accumulated_seconds = 0.0

    def dump_wav_bytes(self) -> bytes:
        """将当前缓冲区导出为 WAV 格式（可发给 Whisper 使用）"""
        if len(self.buffer) == 0:
            return b''
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(self.buffer)
        return buf.getvalue()


# ========================== AI 语音交互处理器 ==========================
# 可以在这里调用 STT / LLM / TTS
# 目前提供骨架，后续阶段接入实际 API

class AIVoiceProcessor:
    """AI 语音交互处理器：STT → LLM → TTS

    依赖 ai_pipeline.py，通过 play_pcm 把 TTS 音频通过 BLE 发到眼镜播放
    """

    def __init__(self, playback_writer):
        self.playback_writer = playback_writer

    async def process(self, wav_bytes: bytes) -> str | None:
        """
        处理语音输入：STT → LLM → TTS → 骨传导喇叭播放
        """
        if len(wav_bytes) < 1600:  # < 0.1 秒，忽略噪音
            return None

        try:
            from ai_pipeline import ai_voice_pipeline
            return await ai_voice_pipeline(wav_bytes, self.playback_writer)
        except ImportError as e:
            print(f"[AI] ⚠ ai_pipeline.py 加载失败: {e}")
            print("[AI] 请确保 ai_pipeline.py 在同目录，且安装了依赖:"
                  "  pip install openai httpx pydub")
            return None


# ========================== 照片拼装器（保持不变） ==========================

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
        if packet_id == 0 and self.chunks:
            self.assemble()
        self.chunks[packet_id] = data

    def end_of_photo(self):
        self.assemble()

    def assemble(self):
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
        print(f"[Photo] {len(jpeg)} bytes, {len(ids)} chunks, {gaps} gaps")

        self.chunks.clear()

        if self.ws:
            asyncio.create_task(self._send_to_qt(jpeg))

    async def _send_to_qt(self, jpeg: bytes):
        try:
            await self.ws.send(jpeg)
            print(f"[WS] Sent {len(jpeg)} bytes to Qt")
        except Exception as e:
            print(f"[WS] Send failed: {e}")

    async def send_audio_to_qt(self, pcm_wav_bytes: bytes):
        """将音频 WAV 数据通过 WebSocket 发给 Qt 端（文本通道，base64）"""
        if not self.ws:
            return
        try:
            import base64
            msg = json.dumps({
                "type": "audio",
                "format": "wav",
                "sample_rate": AUDIO_SAMPLE_RATE,
                "data": base64.b64encode(pcm_wav_bytes).decode()
            })
            await self.ws.send(msg)
        except Exception as e:
            print(f"[WS] Audio send failed: {e}")


# ========================== BLE 回调处理 ==========================

async def ble_handler(client: BleakClient, assembler: PhotoAssembler,
                       audio_rx: AudioReceiver, audio_bridge: 'AudioBridge'):
    """注册所有 BLE 特征的回调"""

    # --- 照片数据回调 ---
    def photo_callback(_handle: int, data: bytearray):
        if len(data) < 2:
            return
        b0, b1 = data[0], data[1]
        if b0 == 0xFF and b1 == 0xFF:
            assembler.end_of_photo()
        else:
            packet_id = b0 + (b1 << 8)
            assembler.add_chunk(packet_id, bytes(data[2:]))

    await client.start_notify(PHOTO_DATA_UUID, photo_callback)
    print("[BLE] Subscribed to photo data (19B10005)")

    # --- 音频数据回调 (麦克风上行) ---
    def audio_callback(_handle: int, data: bytearray):
        if len(data) < 3:
            return
        # 固件协议: data[0..1] = 帧序号, data[2] = 标志, data[3..] = PCM
        pcm = bytes(data[3:])
        audio_rx.append(pcm)

    # 先读取编解码器 ID，确认格式
    try:
        codec_bytes = await client.read_gatt_char(AUDIO_CODEC_UUID)
        codec_id = codec_bytes[0] if codec_bytes else 1
        codec_names = {1: "PCM 8kHz", 11: "MuLaw 8kHz", 20: "Opus 16kHz"}
        print(f"[BLE] Audio codec: {codec_names.get(codec_id, 'Unknown')} (ID={codec_id})")
    except Exception as e:
        print(f"[BLE] Warning: cannot read codec ID: {e}")
        codec_id = 1

    await client.start_notify(AUDIO_DATA_UUID, audio_callback)
    print("[BLE] Subscribed to audio data (19B10001)")

    # --- 将 BLE 播放写入能力注入 AudioBridge ---
    audio_bridge.client = client
    print("[BLE] Audio playback ready (19B10004)")

    # 启动拍照
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


class AudioBridge:
    """暴露给 AI 处理器的 BLE 音频播放接口"""
    def __init__(self):
        self.client: BleakClient | None = None

    async def play_pcm(self, pcm_bytes: bytes):
        """通过 BLE 发送 PCM 音频到 ESP32 骨传导喇叭"""
        if not self.client or not self.client.is_connected:
            print("[AudioBridge] BLE not connected")
            return

        # BLE 每包最多 ~200 bytes，分段发送
        MAX_PAYLOAD = 200
        offset = 0
        while offset < len(pcm_bytes):
            chunk = pcm_bytes[offset:offset + MAX_PAYLOAD]
            try:
                await self.client.write_gatt_char(AUDIO_PLAYBACK_UUID, chunk, response=False)
            except Exception as e:
                print(f"[AudioBridge] Write failed: {e}")
                break
            offset += len(chunk)
            await asyncio.sleep(0.01)  # 给 BLE 栈喘息时间

        print(f"[AudioBridge] Sent {len(pcm_bytes)} bytes PCM in {(len(pcm_bytes) + MAX_PAYLOAD - 1) // MAX_PAYLOAD} chunks)")


# ========================== 主循环 ==========================

async def main():
    audio_bridge = AudioBridge()
    assembler = PhotoAssembler()
    audio_rx = AudioReceiver()
    ai_processor = AIVoiceProcessor(audio_bridge.play_pcm)

    print(f"[BLE] Looking for: {TARGET_NAME} ({TARGET_ADDRESS})")

    # 寻找 ESP32 (优先按 MAC 地址查找)
    device = await BleakScanner.find_device_by_address(TARGET_ADDRESS, timeout=10.0)
    if not device:
        devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
        for d, adv in devices.values():
            if d.name and TARGET_NAME.lower() in d.name.lower():
                device = d
                print(f"[BLE] Found: {d.name} [{d.address}]")
                break

    if not device:
        print(f"[BLE] {TARGET_NAME} not found. Retrying every 3s...")
        while not device:
            await asyncio.sleep(3)
            device = await BleakScanner.find_device_by_address(TARGET_ADDRESS, timeout=5.0)
            if not device:
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
        await ble_handler(client, assembler, audio_rx, audio_bridge)

        # 音频累积处理循环（与 BLE 保持连接并行运行）
        async def audio_process_loop():
            while client.is_connected:
                await asyncio.sleep(2.0)
                if audio_rx.accumulated_seconds >= 1.0:
                    wav = audio_rx.dump_wav_bytes()
                    if wav:
                        await assembler.send_audio_to_qt(wav)
                        answer = await ai_processor.process(wav)
                        audio_rx.clear()
                        if answer:
                            print(f"[AI] Answer: {answer}")

        await audio_process_loop()

    print("[BLE] Disconnected. Restarting in 3s...")
    await asyncio.sleep(3)
    await main()


if __name__ == "__main__":
    print("=" * 55)
    print("  OpenGlass BLE Bridge (Audio + Photo)")
    print("  ESP32 ←→ Python ←→ Qt")
    print("=" * 55)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
