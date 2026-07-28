/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 *
 * I2S PDM Microphone → Opus Encoder → WebSocket Cloud Streaming
 *
 * Pipeline:
 *   PDM Mic → I2S RX → Stream Buffer → VAD → Opus Encode → Send Queue → WSS → Cloud
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"
#include "esp_log.h"
#include "sdkconfig.h"
#include "i2s_pdm_example.h"
#include "i2s_pdm_mic.h"
#include "wifi_sta.h"
#include "opus_encoder.h"
#include "wss_streamer.h"
#include "audio_vad.h"

static const char *TAG = "app_main";

/*
 * VAD + Encode task:
 * Reads PCM frames from the stream buffer, runs VAD,
 * encodes speech frames with Opus, and queues them for WebSocket sending.
 */
static void vad_encode_task(void *pvParameters)
{
    int frame_samples = audio_frame_samples();
    int frame_bytes = audio_frame_bytes();
    StreamBufferHandle_t stream_buf = i2s_mic_get_stream_buffer();

    /* Allocate buffers */
    int16_t *pcm_frame = (int16_t *)calloc(1, frame_bytes);
    uint8_t *opus_pkt = (uint8_t *)malloc(frame_bytes); /* Opus packet < PCM size */
    assert(pcm_frame);
    assert(opus_pkt);

    ESP_LOGI(TAG, "VAD+Encode task started. Frame: %d samples, %d bytes",
             frame_samples, frame_bytes);

    while (1) {
        /* Read exactly one PCM frame from the stream buffer.
         * xStreamBufferReceive will block until trigger_level bytes are available. */
        size_t received = xStreamBufferReceive(stream_buf,
                                               (void *)pcm_frame,
                                               frame_bytes,
                                               pdMS_TO_TICKS(100));
        if (received < frame_bytes) {
            /* Timeout or incomplete frame; skip */
            ESP_LOGW(TAG, "Stream buffer underrun: got %d of %d bytes", received, frame_bytes);
            continue;
        }

        /* VAD: skip silent frames to save bandwidth and CPU */
        if (!audio_vad_detect(pcm_frame, frame_samples)) {
            continue; /* Silence — don't encode or send */
        }

        /* Encode PCM → Opus */
        int encoded_len = opus_encode_frame(pcm_frame, opus_pkt, frame_bytes);
        if (encoded_len <= 0) {
            continue; /* Encode error */
        }

        /* Queue for WebSocket sending */
        wss_streamer_send_opus_packet(opus_pkt, encoded_len);

        ESP_LOGD(TAG, "Sent Opus packet: %d bytes (PCM: %d bytes, ratio: %.1fx)",
                 encoded_len, frame_bytes, (float)frame_bytes / encoded_len);
    }

    free(pcm_frame);
    free(opus_pkt);
    vTaskDelete(NULL);
}

void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "PDM Mic -> Opus -> WebSocket Streaming");
    ESP_LOGI(TAG, "========================================");

    /* Step 1: Connect Wi-Fi */
    ESP_LOGI(TAG, "[1/5] Connecting Wi-Fi...");
    wifi_init_sta();
    if (!wifi_is_connected()) {
        ESP_LOGE(TAG, "Wi-Fi connection failed. Aborting.");
        return;
    }

    /* Step 2: Initialize I2S PDM microphone (stream buffer) */
    ESP_LOGI(TAG, "[2/5] Initializing I2S PDM microphone...");
    i2s_mic_init();

    /* Step 3: Initialize Opus encoder */
    ESP_LOGI(TAG, "[3/5] Initializing Opus encoder...");
    audio_opus_encoder_init();

    /* Step 4: Initialize WebSocket client */
    ESP_LOGI(TAG, "[4/5] Connecting WebSocket...");
    wss_streamer_init();

    /* Wait a moment for WSS to establish */
    int wait_count = 0;
    while (!wss_is_connected() && wait_count < 50) {
        vTaskDelay(pdMS_TO_TICKS(200));
        wait_count++;
    }
    if (!wss_is_connected()) {
        ESP_LOGW(TAG, "WebSocket not connected yet, will retry in background");
    }

    /* Step 5: Start processing pipeline */
    ESP_LOGI(TAG, "[5/5] Starting audio pipeline tasks...");

    /* Task A: WSS sender (consumes the send queue) */
    xTaskCreate(wss_streamer_send_task, "wss_sender", 6144, NULL, 5, NULL);

    /* Task B: VAD + Opus encoder (consumes PCM stream buffer, produces Opus packets) */
    xTaskCreate(vad_encode_task, "vad_encode", 8192, NULL, 6, NULL);

    /* Task C: I2S PDM microphone reader (highest priority to avoid DMA overflow) */
    xTaskCreate(i2s_mic_start_read, "i2s_mic_read", 4096, NULL, 8, NULL);

    ESP_LOGI(TAG, "Audio streaming pipeline started!");
    ESP_LOGI(TAG, "Speak into the microphone to send Opus audio to: %s", CONFIG_WSS_URL);

    /* Main task can do other things or just monitor; for now, sleep */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        ESP_LOGI(TAG, "Heartbeat: Wi-Fi=%d, WSS=%d",
                 wifi_is_connected(), wss_is_connected());
    }
}
