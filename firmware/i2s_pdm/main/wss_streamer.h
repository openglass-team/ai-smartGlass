/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialize the WebSocket Secure client.
 *
 * Connects to the WSS URL configured via menuconfig.
 * Must be called after Wi-Fi is connected.
 */
void wss_streamer_init(void);

/**
 * @brief Send an Opus-encoded audio packet via WebSocket.
 *
 * @param data  Opus-encoded packet data.
 * @param len   Length of the packet in bytes.
 */
void wss_streamer_send_opus_packet(const uint8_t *data, int len);

/**
 * @brief Check if the WebSocket connection is currently established.
 * @return true if connected, false otherwise.
 */
bool wss_is_connected(void);

/**
 * @brief Background task: consume send queue and dispatch to WebSocket.
 *
 * Runs indefinitely. Reads Opus packets from the internal send queue
 * and sends them via WebSocket binary frames.
 *
 * @param pvParameters  Task parameters (unused).
 */
void wss_streamer_send_task(void *pvParameters);

#ifdef __cplusplus
}
#endif
