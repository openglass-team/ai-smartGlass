/*
 * wifi_audio.h — WiFi TCP 音频桥接
 *
 * ESP32 通过 WiFi 连接电脑，TCP 透传麦克风 PCM 和 TTS 音频。
 * 替代不稳定的 BLE 音频通道 (19B10001/19B10004)。
 *
 * 协议（纯二进制，无包头）：
 *   上行: ESP32 → PC   [2字节 length_be] [PCM data]  循环发送
 *   下行: PC → ESP32   [2字节 length_be] [PCM data]  实时写入 BoneSpeaker
 */

#pragma once
#include <Arduino.h>
#include <WiFi.h>

class WifiAudio {
public:
    struct Config {
        const char *ssid     = "YourWiFi";
        const char *password = "YourPassword";
        const char *host     = "192.168.1.100";  // PC 的 IP
        uint16_t    port     = 8888;              // TCP 端口
    };

    bool begin(const Config &cfg);
    void end();
    bool is_connected() const { return _tcp && _tcp->connected(); }

    // 发送麦克风 PCM（上行）
    void send_mic_pcm(const uint8_t *pcm, size_t len);

    // 接收 TTS PCM（下行），非阻塞，返回接收到的字节数
    size_t recv_tts_pcm(uint8_t *buf, size_t max_len);

    // loop 中每帧调用
    void loop();

private:
    Config       _cfg;
    WiFiClient  *_tcp = nullptr;
    unsigned long _last_reconnect = 0;
    void _reconnect();
    void _read_tts();
};

extern WifiAudio wifiAudio;
