#include "eat_embed.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static uart_port_t link_uart;
static uint32_t millis(void) { return (uint32_t)((uint64_t)esp_timer_get_time() / 1000u); }
static void send_frame(const uint8_t *data, uint32_t length)
{
    int sent = uart_write_bytes(link_uart, data, length);
    ESP_ERROR_CHECK(sent == (int)length ? ESP_OK : ESP_FAIL);
}
static void stub_task(void *argument)
{
    uint8_t bytes[64];
    (void)argument;
    eat_embed_init(millis, send_frame);
    for (;;) {
        int i, received = uart_read_bytes(link_uart, bytes, sizeof bytes, 0);
        ESP_ERROR_CHECK(received >= 0 ? ESP_OK : ESP_FAIL);
        for (i = 0; i < received; ++i) eat_link_rx(bytes[i]);
        eat_stub_poll();
        vTaskDelay(1); /* One tick: keep below heartbeat timeout even at a low tick rate. */
    }
}
/* TODO(port): expose this prototype in your application header; call once, after installing
 * the UART driver and configuring baud/pins/clock with the public IDF APIs. */
esp_err_t eat_port_esp_idf_start(uart_port_t uart, uint32_t stack_bytes, UBaseType_t priority)
{
    link_uart = uart;
    return xTaskCreate(stub_task, "eat_stub", stack_bytes, NULL, priority, NULL) == pdPASS
        ? ESP_OK : ESP_ERR_NO_MEM;
}
