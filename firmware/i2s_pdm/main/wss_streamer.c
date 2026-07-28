/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_tls.h"
#include "sdkconfig.h"
#include "esp_websocket_client.h"
#include "wss_streamer.h"

static const char *TAG = "wss_streamer";

static esp_websocket_client_handle_t s_ws_client = NULL;
static bool s_ws_connected = false;

/* Queue item for Opus packets to be sent */
typedef struct {
    uint8_t data[256];
    int len;
} wss_packet_t;

static QueueHandle_t s_send_queue = NULL;

/* Authorization header for WebSocket connection */
#define AUTH_HEADER_KEY   "Authorization"

static void wss_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "WebSocket connected");
            s_ws_connected = true;
            break;
        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "WebSocket disconnected");
            s_ws_connected = false;
            break;
        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "WebSocket error");
            s_ws_connected = false;
            break;
        case WEBSOCKET_EVENT_DATA:
            /* Receive server response (e.g., ASR result text) */
            if (data->data_len > 0 && data->op_code == 0x01) {
                ESP_LOGI(TAG, "Received: %.*s", data->data_len, (char *)data->data_ptr);
            } else if (data->data_len > 0 && data->op_code == 0x02) {
                ESP_LOGI(TAG, "Received binary: %d bytes", data->data_len);
            }
            break;
        default:
            break;
    }
}

void wss_streamer_init(void)
{
    s_send_queue = xQueueCreate(CONFIG_AUDIO_SEND_QUEUE_SIZE, sizeof(wss_packet_t));
    if (s_send_queue == NULL) {
        ESP_LOGE(TAG, "Failed to create send queue");
        return;
    }

    esp_websocket_client_config_t ws_cfg = {
        .uri = CONFIG_WSS_URL,
        .task_stack = 6144,
        .task_prio = 5,
        .buffer_size = 4096,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 10000,
    };

#if CONFIG_WSS_SKIP_CERT_VERIFY
    ws_cfg.skip_cert_common_name_check = true;
    ESP_LOGW(TAG, "TLS certificate verification DISABLED (testing mode)");
#endif

    s_ws_client = esp_websocket_client_init(&ws_cfg);
    if (s_ws_client == NULL) {
        ESP_LOGE(TAG, "Failed to init WebSocket client");
        return;
    }

    /* Set Authorization header: "Authorization: Bearer <token>"
     * Must be called BEFORE esp_websocket_client_start() */
    const char *token = CONFIG_WSS_AUTH_TOKEN;
    if (token != NULL && strlen(token) > 0) {
        char auth_value[256];
        snprintf(auth_value, sizeof(auth_value), "Bearer %s", token);
        esp_websocket_client_append_header(s_ws_client, AUTH_HEADER_KEY, auth_value);
        ESP_LOGI(TAG, "Authorization: Bearer *** (token set)");
    }

    esp_websocket_register_events(s_ws_client, WEBSOCKET_EVENT_ANY, &wss_event_handler, NULL);
    esp_websocket_client_start(s_ws_client);

    ESP_LOGI(TAG, "WebSocket client started, URL: %s", CONFIG_WSS_URL);
}

void wss_streamer_send_opus_packet(const uint8_t *data, int len)
{
    if (s_ws_client == NULL || !s_ws_connected) {
        return; /* Not connected yet; drop packet */
    }

    if (len <= 0 || len > 256) {
        ESP_LOGW(TAG, "Invalid packet length: %d", len);
        return;
    }

    /* Try queuing: if full, drop oldest and try again */
    wss_packet_t pkt;
    memcpy(pkt.data, data, len);
    pkt.len = len;

    if (xQueueSend(s_send_queue, &pkt, 0) != pdTRUE) {
        /* Queue full — drop oldest packet to make room */
        wss_packet_t old_pkt;
        xQueueReceive(s_send_queue, &old_pkt, 0);
        xQueueSend(s_send_queue, &pkt, 0);
        ESP_LOGW(TAG, "Send queue full, dropped oldest packet");
    }
}

bool wss_is_connected(void)
{
    return s_ws_connected;
}

/*
 * Background task: consume send queue and dispatch to WebSocket.
 * This decouples encoding from network I/O.
 */
void wss_streamer_send_task(void *pvParameters)
{
    wss_packet_t pkt;

    while (1) {
        if (xQueueReceive(s_send_queue, &pkt, pdMS_TO_TICKS(100)) == pdTRUE) {
            if (s_ws_connected && s_ws_client != NULL) {
                int ret = esp_websocket_client_send_bin(s_ws_client,
                                                        (const char *)pkt.data,
                                                        pkt.len,
                                                        pdMS_TO_TICKS(200));
                if (ret < 0) {
                    ESP_LOGW(TAG, "Send failed: %d", ret);
                }
            }
        }
    }
    vTaskDelete(NULL);
}
