/*
 * wifi_audio.cpp — WiFi TCP 音频桥接实现
 */

#include "wifi_audio.h"
#include "bone_speaker.h"

extern BoneSpeaker speaker;  // 固件全局骨传导喇叭实例

WifiAudio wifiAudio;

// ── begin ─────────────────────────────────────────────────
bool WifiAudio::begin(const Config &cfg) {
    _cfg = cfg;

    WiFi.mode(WIFI_STA);
    WiFi.begin(_cfg.ssid, _cfg.password);

    Serial.printf("[WiFi] Connecting to %s ...\n", _cfg.ssid);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] FAILED — continuing without WiFi");
        return false;
    }

    Serial.printf("[WiFi] Connected! IP = %s\n", WiFi.localIP().toString().c_str());

    _tcp = new WiFiClient();
    _reconnect();
    return true;
}

// ── end ───────────────────────────────────────────────────
void WifiAudio::end() {
    if (_tcp) {
        _tcp->stop();
        delete _tcp;
        _tcp = nullptr;
    }
    WiFi.disconnect(true);
}

// ── loop ──────────────────────────────────────────────────
void WifiAudio::loop() {
    if (!_tcp || !_tcp->connected()) {
        _reconnect();
        return;
    }
    _read_tts();
}

// ── send_mic_pcm ──────────────────────────────────────────
void WifiAudio::send_mic_pcm(const uint8_t *pcm, size_t len) {
    if (!is_connected()) return;
    if (len == 0 || len > 65535) return;

    uint8_t hdr[2] = { (uint8_t)((len >> 8) & 0xFF), (uint8_t)(len & 0xFF) };
    _tcp->write(hdr, 2);
    _tcp->write(pcm, len);
    _tcp->flush();
}

// ── recv_tts_pcm ──────────────────────────────────────────
size_t WifiAudio::recv_tts_pcm(uint8_t *buf, size_t max_len) {
    if (!is_connected()) return 0;

    // 读取 2 字节长度头
    int avail = _tcp->available();
    if (avail < 2) return 0;

    uint8_t hdr[2];
    int peek_result = _tcp->peek();
    if (peek_result < 0) return 0;

    _tcp->readBytes(hdr, 2);
    size_t len = ((size_t)hdr[0] << 8) | hdr[1];
    if (len == 0 || len > max_len) return 0;

    // 等待数据到达
    unsigned long timeout = millis() + 1000;
    while (_tcp->available() < (int)len && millis() < timeout) {
        delay(5);
    }

    size_t got = _tcp->readBytes((char *)buf, len);
    return got;
}

// ── _reconnect ─────────────────────────────────────────────
void WifiAudio::_reconnect() {
    if (!_tcp) return;

    unsigned long now = millis();
    if (now - _last_reconnect < 2000) return;
    _last_reconnect = now;

    if (_tcp->connected()) _tcp->stop();

    Serial.printf("[TCP] Connecting to %s:%d ...\n", _cfg.host, _cfg.port);
    if (_tcp->connect(_cfg.host, _cfg.port)) {
        Serial.println("[TCP] Connected");
    } else {
        Serial.println("[TCP] FAILED — retrying");
    }
}

// ── _read_tts ─────────────────────────────────────────────
void WifiAudio::_read_tts() {
    uint8_t buf[512];
    size_t got = recv_tts_pcm(buf, sizeof(buf));
    if (got > 0) {
        speaker.write((int16_t *)buf, got / 2);
    }
}
