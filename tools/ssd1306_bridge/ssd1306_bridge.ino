/*
 * Smart Arena SSD1306 串口桥
 *
 * 电脑 --USB串口--> 本固件 --I2C--> SSD1306 OLED
 *
 * 协议: 0xAA | control(1) | len_lo(1) | len_hi(1) | payload(len)
 *   control = 0x00  命令
 *   control = 0x40  显存数据
 *
 * 默认: 地址 0x3C, 串口 115200, 128x32/128x64 均由上位机初始化。
 * 只依赖 Arduino 自带的 Wire/Serial，不依赖第三方 OLED 库。
 */

#include <Wire.h>

static const uint8_t  SSD1306_ADDR = 0x3C;
static const uint8_t  FRAME_MAGIC  = 0xAA;
static const uint16_t MAX_PAYLOAD  = 1024;
static const uint16_t I2C_CHUNK    = 16;

static uint8_t  payload[MAX_PAYLOAD];
static uint8_t  state = 0;          // 0=等魔数, 1=控制字节, 2=长度, 3=载荷
static uint8_t  control = 0;
static uint16_t expected = 0;
static uint16_t received = 0;
static uint32_t lastByteAt = 0;

static void resetParser() {
  state = 0;
  control = 0;
  expected = 0;
  received = 0;
}

static bool writeI2C(uint8_t controlByte, const uint8_t *data, uint16_t len) {
  for (uint16_t offset = 0; offset < len; offset += I2C_CHUNK) {
    uint16_t part = min((uint16_t)I2C_CHUNK, (uint16_t)(len - offset));
    Wire.beginTransmission(SSD1306_ADDR);
    Wire.write(controlByte);
    Wire.write(data + offset, part);
    if (Wire.endTransmission() != 0) {
      return false;
    }
  }
  return true;
}

static void handleFrame() {
  if (control == 0x00 || control == 0x40) {
    writeI2C(control, payload, expected);
  }
  resetParser();
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);
  lastByteAt = millis();
}

void loop() {
  while (Serial.available() > 0) {
    uint8_t b = (uint8_t)Serial.read();
    lastByteAt = millis();

    switch (state) {
      case 0:
        if (b == FRAME_MAGIC) state = 1;
        break;
      case 1:
        control = b;
        state = 2;
        break;
      case 2:
        expected = b;
        state = 3;
        break;
      case 3:
        expected |= ((uint16_t)b << 8);
        received = 0;
        if (expected == 0) {
          handleFrame();
        } else if (expected > MAX_PAYLOAD) {
          resetParser();
        } else {
          state = 4;
        }
        break;
      case 4:
        payload[received++] = b;
        if (received >= expected) handleFrame();
        break;
      default:
        resetParser();
        break;
    }
  }

  // 半帧超时保护，避免串口噪声把解析器卡死。
  if (state != 0 && (uint32_t)(millis() - lastByteAt) > 1000) {
    resetParser();
  }
}