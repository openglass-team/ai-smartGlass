"""
OpenGlass AI 语音交互管线

STT (讯飞) -> LLM (智谱 GLM-4-Flash) -> TTS (微软 Edge TTS)

全部免费:
  - STT: 讯飞语音听写 (每天 500 次)
  - LLM: 智谱 GLM-4-Flash (免费)
  - TTS: 微软 Edge TTS (免费不限量)

安装依赖:
  pip install edge-tts httpx pydub websocket-client
  pydub 需要 ffmpeg

讯飞 KEY: https://console.xfyun.cn/ -> 控制台 -> 语音听写 -> 领取免费包
"""

import os
import io
import json
import base64
import hashlib
import hmac
import tempfile
import asyncio
import httpx
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

# Load .env
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    with open(_ENV_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# API keys
XFYUN_APP_ID     = os.getenv("XFYUN_APP_ID", "")
XFYUN_API_KEY    = os.getenv("XFYUN_API_KEY", "")
XFYUN_API_SECRET = os.getenv("XFYUN_API_SECRET", "")
ZHIPU_API_KEY    = os.getenv("EXPO_PUBLIC_ZHIPU_API_KEY", "")
ZHIPU_BASE       = "https://open.bigmodel.cn/api/paas/v4"


# ========================== Xfyun WebSocket URL ==========================

def _xfyun_create_url() -> str:
    host = "iat-api.xfyun.cn"
    path = "/v2/iat"
    now = datetime.utcnow()
    date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

    sign_raw = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    sign_sha = hmac.new(XFYUN_API_SECRET.encode(), sign_raw.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(sign_sha).decode()

    auth_raw = f'api_key="{XFYUN_API_KEY}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
    authorization = base64.b64encode(auth_raw.encode()).decode()

    params = {"authorization": authorization, "date": date, "host": host}
    return f"wss://{host}{path}?" + urlencode(params)


# ========================== STT (Xfyun IAT) ==========================

async def speech_to_text(wav_bytes: bytes) -> str | None:
    """Xfyun speech recognition — 500 free calls/day"""
    if not all([XFYUN_APP_ID, XFYUN_API_KEY, XFYUN_API_SECRET]):
        print("[STT] Xfyun key missing. Get from https://console.xfyun.cn/")
        return None
    if len(wav_bytes) < 1600:
        return None

    try:
        import websocket

        # Strip WAV header (44 bytes) to get raw 16kHz/16bit/mono PCM
        pcm_data = wav_bytes[44:] if wav_bytes[:4] == b'RIFF' else wav_bytes
        if len(pcm_data) < 1600:
            return None

        loop = asyncio.get_running_loop()

        def _run():
            ws_url = _xfyun_create_url()
            result = []

            def on_open(ws):
                ws.send(json.dumps({
                    "common": {"app_id": XFYUN_APP_ID},
                    "business": {
                        "language": "zh_cn",
                        "domain": "iat",
                        "accent": "mandarin",
                        "vad_eos": 3000,
                        "ptt": 0,
                    },
                    "data": {
                        "status": 0,
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": base64.b64encode(pcm_data).decode(),
                    },
                }))

            def on_message(ws, msg):
                data = json.loads(msg)
                if data.get("code") != 0:
                    print(f"[STT] error: {data.get('message')}")
                    ws.close()
                    return
                r = data.get("data", {}).get("result", {})
                for ws_item in r.get("ws", []):
                    for cw in ws_item.get("cw", []):
                        if cw.get("w"):
                            result.append(cw["w"])
                if data.get("data", {}).get("status") == 2:
                    ws.close()

            def on_error(ws, err):
                print(f"[STT] ws error: {err}")

            ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_error=on_error, on_open=on_open)
            ws.run_forever()
            return "".join(result) if result else None

        text = await loop.run_in_executor(None, _run)
        if text:
            print(f"[STT] text OK")
        return text

    except ImportError:
        print("[STT] pip install websocket-client")
        return None
    except Exception as e:
        print(f"[STT] {e}")
        return None


# ========================== LLM (Zhipu GLM-4-Flash) ==========================

async def ai_chat(question: str, image_context: str | None = None) -> str | None:
    """Zhipu GLM-4-Flash — free, native Chinese"""
    if not ZHIPU_API_KEY:
        print("[LLM] Key not set")
        return None

    system_prompt = (
        "You are a smart AI assistant on smart glasses. "
        "Answer concisely in Chinese, like chatting with a friend. "
        "Keep answers under 50 characters."
    )

    if image_context:
        system_prompt += f"\n\nCurrent view: {image_context}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ZHIPU_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "glm-4-flash",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 256,
                },
            )
            if resp.status_code == 200:
                answer = resp.json()["choices"][0]["message"]["content"].strip()
                print(f"[LLM] Answer OK")
                return answer
            print(f"[LLM] HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"[LLM] {e}")
        return None


# ========================== TTS (Edge TTS) ==========================

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

async def text_to_speech(text: str, voice: str = DEFAULT_VOICE) -> bytes | None:
    """Edge TTS — free, unlimited"""
    try:
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            await edge_tts.Communicate(text, voice).save(tmp_path)
            with open(tmp_path, "rb") as f:
                mp3 = f.read()
            print(f"[TTS] {len(mp3)} bytes MP3")
            return mp3
        finally:
            try: os.unlink(tmp_path)
            except OSError: pass
    except ImportError:
        print("[TTS] pip install edge-tts")
        return None
    except Exception as e:
        print(f"[TTS] {e}")
        return None


# ========================== Audio: MP3 -> PCM ==========================

def mp3_to_pcm(mp3_bytes: bytes, target_sample_rate: int = 16000) -> bytes | None:
    """MP3 -> 16kHz 16-bit mono PCM"""
    # Method 1: pydub
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
        audio = audio.set_channels(1).set_frame_rate(target_sample_rate).set_sample_width(2)
        print(f"[Audio] pydub: MP3({len(mp3_bytes)}) -> PCM({len(audio.raw_data)})")
        return audio.raw_data
    except ImportError:
        pass
    except Exception as e:
        print(f"[Audio] pydub: {e}")

    # Method 2: ffmpeg
    try:
        import subprocess
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            mp3_path = f.name
        pcm_path = mp3_path + ".pcm"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_path,
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(target_sample_rate), "-ac", "1", pcm_path,
            ], check=True, capture_output=True)
            with open(pcm_path, "rb") as f:
                pcm = f.read()
            print(f"[Audio] ffmpeg: MP3({len(mp3_bytes)}) -> PCM({len(pcm)})")
            return pcm
        finally:
            try: os.unlink(mp3_path); os.unlink(pcm_path)
            except OSError: pass
    except FileNotFoundError:
        print("[Audio] ffmpeg not found")
        return None
    except Exception as e:
        print(f"[Audio] ffmpeg: {e}")
        return None


# ========================== Full Voice Pipeline ==========================

async def ai_voice_pipeline(wav_bytes: bytes, play_pcm, image_context: str | None = None) -> str | None:
    """Full pipeline: WAV -> STT -> LLM -> TTS -> PCM -> play via BLE"""
    question = await speech_to_text(wav_bytes)
    if not question:
        return None

    answer = await ai_chat(question, image_context)
    if not answer:
        return None

    mp3_bytes = await text_to_speech(answer)
    if not mp3_bytes:
        return answer

    pcm_bytes = mp3_to_pcm(mp3_bytes)
    if pcm_bytes:
        await play_pcm(pcm_bytes)

    return answer
