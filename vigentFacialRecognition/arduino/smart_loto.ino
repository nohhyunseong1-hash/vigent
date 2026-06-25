/*
 * smart_loto.ino — VIGENT Smart LOTO 프로토타입 펌웨어
 *
 * 역할: PC(VIGENT)의 시리얼 명령으로 잠금 볼트(서보)와 상태 LED를 제어한다.
 *   LOCKED  = 잠금 볼트 전개 → 기계 비활성(안전)
 *   UNLOCKED= 잠금 볼트 후퇴 → 기계 기동 허용
 *
 * 안전(페일세이프): 부팅 시 항상 LOCKED(안전). 시리얼이 끊겨도 마지막 안전상태 유지.
 *  ※ 본 서보는 프로토타입 표시·보조 인터록이며, 작업자 물리 패드락/인증 안전회로를
 *    대체하지 않는다(SMART_LOTO_DESIGN.md §0).
 *
 * 배선: 서보 D9, RED D7(잠김), GREEN D8(해제), BUZZER D6(선택). 시리얼 9600 8N1.
 * 프로토콜: 수신 LOCK/UNLOCK/PING(줄 단위) → 송신 STATE:LOCKED / STATE:UNLOCKED / PONG
 */
#include <Servo.h>

const uint8_t PIN_SERVO = 9;
const uint8_t PIN_RED   = 7;
const uint8_t PIN_GREEN = 8;
const uint8_t PIN_BUZZER= 6;

const int ANGLE_LOCKED   = 10;   // 볼트 전개(기계 비활성)
const int ANGLE_UNLOCKED = 100;  // 볼트 후퇴(기동 허용)

Servo bolt;
bool locked = true;              // 페일세이프 기본값
String line = "";

void applyState(bool lock) {
  locked = lock;
  bolt.write(lock ? ANGLE_LOCKED : ANGLE_UNLOCKED);
  digitalWrite(PIN_RED,   lock ? HIGH : LOW);
  digitalWrite(PIN_GREEN, lock ? LOW  : HIGH);
  // 상태 전환 시 짧은 알림음(선택)
  tone(PIN_BUZZER, lock ? 600 : 1200, 120);
  Serial.println(lock ? "STATE:LOCKED" : "STATE:UNLOCKED");
}

void setup() {
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  bolt.attach(PIN_SERVO);
  Serial.begin(9600);
  applyState(true);              // 부팅 = 잠금(안전)
}

void handle(const String &cmd) {
  if (cmd == "LOCK")        applyState(true);
  else if (cmd == "UNLOCK") applyState(false);
  else if (cmd == "PING")   Serial.println("PONG");
  else if (cmd == "STATUS") Serial.println(locked ? "STATE:LOCKED" : "STATE:UNLOCKED");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      line.trim();
      if (line.length()) handle(line);
      line = "";
    } else if (line.length() < 16) {
      line += c;
    }
  }
}
