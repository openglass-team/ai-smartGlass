"""
tcp_server.py — WiFi TCP 音频服务器（替代 BLE 桥接）

启动方式: python tcp_server.py
监听端口: 8888

协议:
  ESP32 → PC  [2 bytes len_be] [PCM data 16kHz 16-bit mono]
  PC → ESP32  [2 bytes len_be] [PCM data 16kHz 16-bit mono]

AI Pipeline 在语音结束时自动触发:
  PCM累积 → WAV → 讯飞 STT → 智谱 LLM → Edge TTS → MP3→PCM → 发回ESP32
"""

import asyncio
import struct
import io
import wave
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'QtGlassDemo'))

from ai_pipeline import ai_voice_pipeline
from bone_pcm import pcm_player

HOST = '0.0.0.0'
PORT = 8888

AUDIO_SAMPLE_RATE = 16000
VOICE_TIMEOUT = 1.5  # 1.5 秒无新数据 = 语音结束


class VoiceSession:
    """累积 PCM 并检测语音结束"""

    def __init__(self, writer):
        self.writer = writer
        self.buffer = bytearray()
        self.last_packet = asyncio.get_event_loop().time()

    def add(self, pcm: bytes):
        self.buffer.extend(pcm)
        self.last_packet = asyncio.get_event_loop().time()

    def is_speech_ended(self) -> bool:
        return (asyncio.get_event_loop().time() - self.last_packet) > VOICE_TIMEOUT

    def dump_wav(self) -> bytes:
        """导出累积的 PCM 数据为 WAV 格式"""
        if len(self.buffer) < 3200:  # < 0.1 秒
            return b''
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_SAMPLE_RATE)
            wf.writeframes(self.buffer)
        return buf.getvalue()


async def handle_client(reader, writer):
    """TCP 客户端连接处理"""
    addr = writer.get_extra_info('peername')
    print(f'[TCP] Connected: {addr}')
    session = VoiceSession(writer)

    try:
        while True:
            # 读取 2 字节长度头
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
            length = (hdr[0] << 8) | hdr[1]
            if length == 0 or length > 65535:
                continue

            # 读取 PCM 数据
            pcm = await asyncio.wait_for(reader.readexactly(length), timeout=5.0)
            if not pcm:
                break

            session.add(pcm)

            # 检测语音结束（停顿 1.5 秒无人声）
            if session.is_speech_ended() and len(session.buffer) > 3200:
                wav = session.dump_wav()
                session.buffer.clear()

                print(f'[Voice] {len(wav)} bytes WAV — processing…')

                # === AI Pipeline ===
                async def play_to_esp32(pcm_chunk: bytes):
                    """把 TTS 的 PCM 通过 TCP 发回 ESP32"""
                    if len(pcm_chunk) > 65535:
                        return
                    writer.write(struct.pack('>H', len(pcm_chunk)))
                    writer.write(pcm_chunk)
                    await writer.drain()

                result = await ai_voice_pipeline(wav, play_to_esp32)
                if result:
                    print(f'[AI] Answer: {result}')
                else:
                    print('[AI] No answer (STT failed or LLM empty)')

    except (asyncio.IncompleteReadError, ConnectionResetError, TimeoutError):
        pass
    except Exception as e:
        print(f'[TCP] Error: {e}')
    finally:
        print(f'[TCP] Disconnected: {addr}')
        writer.close()


async def main():
    server = await asyncio.start_server(handle_client, HOST, PORT)
    print(f'[TCP] Listening on {HOST}:{PORT}')
    print(f'[TCP] Waiting for ESP32 connection…')
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[TCP] Server stopped')
