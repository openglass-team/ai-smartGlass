/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"
#include "soc/soc_caps.h"
#include "driver/i2s_pdm.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "sdkconfig.h"
#include "i2s_pdm_example.h"
#include "i2s_pdm_mic.h"
#include "i2s_example_pins.h"

#define EXAMPLE_PDM_RX_CLK_IO           EXAMPLE_I2S_BCLK_IO1      // PDM RX clock GPIO
#define EXAMPLE_PDM_RX_DIN_IO           EXAMPLE_I2S_DIN_IO1       // PDM RX data in GPIO
#if SOC_I2S_PDM_MAX_RX_LINES == 4
#define EXAMPLE_PDM_RX_DIN1_IO          EXAMPLE_I2S_DIN1_IO1
#define EXAMPLE_PDM_RX_DIN2_IO          EXAMPLE_I2S_DIN2_IO1
#define EXAMPLE_PDM_RX_DIN3_IO          EXAMPLE_I2S_DIN3_IO1
#endif

static const char *TAG = "i2s_pdm_mic";

/* Stream buffer: I2S reader task writes PCM frames, encoder task reads them */
static StreamBufferHandle_t s_pcm_stream_buf = NULL;

/* Stream buffer size: hold ~4 frames (4 * ~640 bytes = ~2560, round up) */
#define PCM_STREAM_BUF_SIZE      (audio_frame_bytes() * 8)

static i2s_chan_handle_t i2s_mic_init_rx(void)
{
#if SOC_I2S_SUPPORTS_PDM2PCM
    ESP_LOGI(TAG, "I2S PDM RX microphone (PCM format)");
#else
    ESP_LOGI(TAG, "I2S PDM RX microphone (raw PDM format)");
#endif

    i2s_chan_handle_t rx_chan;
    i2s_chan_config_t rx_chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&rx_chan_cfg, NULL, &rx_chan));

    i2s_pdm_rx_config_t pdm_rx_cfg = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(CONFIG_AUDIO_SAMPLE_RATE_HZ),
#if SOC_I2S_SUPPORTS_PDM2PCM
        .slot_cfg = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
#else
        .slot_cfg = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
#endif
        .gpio_cfg = {
            .clk = EXAMPLE_PDM_RX_CLK_IO,
#if SOC_I2S_PDM_MAX_RX_LINES == 4
            .dins = {
                EXAMPLE_PDM_RX_DIN_IO,
                EXAMPLE_PDM_RX_DIN1_IO,
                EXAMPLE_PDM_RX_DIN2_IO,
                EXAMPLE_PDM_RX_DIN3_IO,
            },
#else
            .din = EXAMPLE_PDM_RX_DIN_IO,
#endif
            .invert_flags = {
                .clk_inv = false,
            },
        },
    };
#if CONFIG_IDF_TARGET_ESP32S3
    pdm_rx_cfg.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
    pdm_rx_cfg.slot_cfg.slot_mask = I2S_PDM_LINE_SLOT_ALL;
#endif
    ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx_chan, &pdm_rx_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(rx_chan));
    return rx_chan;
}

void i2s_mic_init(void)
{
    /* Create stream buffer for passing PCM frames between tasks */
    s_pcm_stream_buf = xStreamBufferCreate(PCM_STREAM_BUF_SIZE, audio_frame_bytes());
    if (s_pcm_stream_buf == NULL) {
        ESP_LOGE(TAG, "Failed to create PCM stream buffer");
        abort();
    }
    ESP_LOGI(TAG, "PCM stream buffer created: %d bytes, trigger level: %d",
             PCM_STREAM_BUF_SIZE, audio_frame_bytes());
}

StreamBufferHandle_t i2s_mic_get_stream_buffer(void)
{
    return s_pcm_stream_buf;
}

void i2s_mic_start_read(void *pvParameters)
{
    i2s_chan_handle_t rx_chan = i2s_mic_init_rx();

    /* Allocate a buffer for I2S DMA reads */
    int16_t *read_buf = (int16_t *)calloc(1, EXAMPLE_BUFF_SIZE);
    assert(read_buf);
    size_t r_bytes = 0;

    ESP_LOGI(TAG, "Microphone read task started, sample rate: %d Hz, frame: %d ms (%d samples)",
             CONFIG_AUDIO_SAMPLE_RATE_HZ, CONFIG_AUDIO_FRAME_DURATION_MS, audio_frame_samples());

    while (1) {
        /* Read PCM data from I2S */
        esp_err_t ret = i2s_channel_read(rx_chan, read_buf, EXAMPLE_BUFF_SIZE, &r_bytes, pdMS_TO_TICKS(100));
        if (ret == ESP_OK && r_bytes > 0) {
            /* Write PCM data to stream buffer.
             * xStreamBufferSend will block until there's space or trigger level reached.
             * We send byte by byte or in chunks; the consumer reads full frames. */
            size_t sent = 0;
            while (sent < r_bytes) {
                size_t chunk = (r_bytes - sent > 512) ? 512 : (r_bytes - sent);
                size_t written = xStreamBufferSend(s_pcm_stream_buf,
                                                   (uint8_t *)read_buf + sent,
                                                   chunk,
                                                   pdMS_TO_TICKS(10));
                sent += written;
                if (written < chunk) {
                    /* Buffer full, wait a bit */
                    vTaskDelay(pdMS_TO_TICKS(1));
                }
            }
        } else if (ret == ESP_ERR_TIMEOUT) {
            /* Timeout is ok, just retry */
        } else {
            ESP_LOGW(TAG, "I2S read error: %d", ret);
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
    free(read_buf);
    vTaskDelete(NULL);
}
