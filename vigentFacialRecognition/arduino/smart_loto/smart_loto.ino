/*
 * smart_loto.ino — VIGENT Smart LOTO 프로토타입 (버튼 + 무장 ARM)
 *
 * 동작:
 *   - PC가 얼굴 인증 성공 시 "ARM[:LOCK|UNLOCK|TOGGLE]" 전송 → 일정시간(10s) 무장.
 *   - 무장 중 물리 버튼(D2)을 누르면 서보 작동. 무장 안 됐으면 버튼 무시(경고음).
 *   - 직접 제어(LOCK/UNLOCK)도 그대로 동작(웹 앱용).
 * 안전: 부팅 시 잠금(LOCKED), 무장은 시간초과 시 자동 해제.
 *
 * 배선: 서보 D9, RED D7(잠김), GREEN D8(해제), BUZZER D6, BUTTON D2(↔GND, 내부풀업).
 * 프로토콜 수신: LOCK/UNLOCK/ARM[:act]/DISARM/PING/STATUS
 *          송신: STATE:LOCKED|UNLOCKED, ARMED:act, DISARMED, BTN:OK, BTN:DENIED, PONG
 */
#include <Servo.h>

const uint8_t PIN_SERVO  = 9;
const uint8_t PIN_RED    = 7;
const uint8_t PIN_GREEN  = 8;
const uint8_t PIN_BUZZER = 6;
const uint8_t PIN_BTN    = 2;

const int ANGLE_LOCKED   = 10;
const int ANGLE_UNLOCKED = 100;
const unsigned long ARM_MS = 10000;   // 무장 유지 10초

Servo bolt;
bool locked = true;
bool armed = false;
String armedAction = "TOGGLE";
unsigned long armUntil = 0;
String line = "";
int lastBtn = HIGH;
unsigned long lastBtnTime = 0;

void applyState(bool lock) {
  locked = lock;
  bolt.write(lock ? ANGLE_LOCKED : ANGLE_UNLOCKED);
  digitalWrite(PIN_RED,   lock ? HIGH : LOW);
  digitalWrite(PIN_GREEN, lock ? LOW  : HIGH);
  tone(PIN_BUZZER, lock ? 600 : 1200, 120);
  Serial.println(lock ? "STATE:LOCKED" : "STATE:UNLOCKED");
}

void setArmed(bool a, String act) {
  armed = a;
  if (a) {
    armedAction = act;
    armUntil = millis() + ARM_MS;
    tone(PIN_BUZZER, 1500, 70); delay(110); tone(PIN_BUZZER, 1500, 70);  // 무장 알림
    Serial.println("ARMED:" + act);
  } else {
    Serial.println("DISARMED");
  }
}

void doButton() {
  if (!armed) {                          // 무장 안 됨 → 무시 + 경고음
    tone(PIN_BUZZER, 300, 350);
    Serial.println("BTN:DENIED");
    return;
  }
  bool target;
  if (armedAction == "LOCK")        target = true;
  else if (armedAction == "UNLOCK") target = false;
  else                              target = !locked;   // TOGGLE
  applyState(target);
  armed = false;
  Serial.println("BTN:OK");
}

void handle(const String &cmd) {
  if (cmd == "LOCK")        applyState(true);
  else if (cmd == "UNLOCK") applyState(false);
  else if (cmd == "DISARM") setArmed(false, "");
  else if (cmd.startsWith("ARM")) {
    String act = "TOGGLE";
    int c = cmd.indexOf(':');
    if (c >= 0) act = cmd.substring(c + 1);
    setArmed(true, act);
  }
  else if (cmd == "PING")   Serial.println("PONG");
  else if (cmd == "STATUS") Serial.println(locked ? "STATE:LOCKED" : "STATE:UNLOCKED");
}

void setup() {
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BTN, INPUT_PULLUP);
  bolt.attach(PIN_SERVO);
  Serial.begin(9600);
  applyState(true);            // 부팅 = 잠금(안전)
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      line.trim();
      if (line.length()) handle(line);
      line = "";
    } else if (line.length() < 20) {
      line += c;
    }
  }
  // 버튼(액티브 LOW, 디바운스)
  int b = digitalRead(PIN_BTN);
  if (b != lastBtn && millis() - lastBtnTime > 40) {
    lastBtnTime = millis();
    if (lastBtn == HIGH && b == LOW) doButton();   // 눌림 순간
    lastBtn = b;
  }
  // 무장 시간초과 자동 해제
  if (armed && millis() > armUntil) setArmed(false, "");
}
