#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SS_PIN 5
#define RST_PIN 4
#define BUZZER_PIN 27
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
const char* WIFI_SSID = "CHANGE_ME";
const char* WIFI_PASSWORD = "CHANGE_ME";
const char* SERVER_URL = "http://192.168.1.10:5000/api/meal/scan";
MFRC522 rfid(SS_PIN, RST_PIN);
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

void showMessage(String message) {
  display.clearDisplay(); display.setCursor(0, 0); display.println(message);
  display.display(); tone(BUZZER_PIN, 1800, 120);
}
void setup() {
  Serial.begin(115200); SPI.begin(18, 19, 23, SS_PIN); rfid.PCD_Init();
  Wire.begin(21, 22); display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD); display.setTextSize(1); display.setTextColor(SSD1306_WHITE);
  display.println("Connecting..."); display.display();
  while (WiFi.status() != WL_CONNECTED) delay(300);
}
void loop() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  String uid = ""; for (byte i = 0; i < rfid.uid.size; i++) { if (rfid.uid.uidByte[i] < 16) uid += "0"; uid += String(rfid.uid.uidByte[i], HEX); }
  HTTPClient http; http.begin(SERVER_URL); http.addHeader("Content-Type", "application/json");
  int status = http.POST("{\"uid\":\"" + uid + "\"}");
  String response = http.getString(); http.end();
  showMessage(status == 201 ? "APPROVED\n" + uid : "DENIED\n" + response);
  rfid.PICC_HaltA(); delay(2000);
}
