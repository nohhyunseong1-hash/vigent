#!/usr/bin/env python3
r"""setup_wizard.py — 첫 실행 마법사(1차: 명령줄). [USB 1차 계획 3, 설계서 §4]

설치된 기기에서 돈다:  <Target>\python\python.exe <Target>\app\scripts\deploy\setup_wizard.py
  (앱 뿌리 = 이 파일의 parents[2] = <Target>\app. vigent-core 모듈을 그대로 쓴다 — 마법사가 앱과 다른 파일을 쓰면 안 된다)

순서 — ★각 입력 직후 검증한다(전부 입력하고 마지막에 한꺼번에 틀렸다고 하면 어디가 문제인지 모른다):
  1 기기명            형식(영문·숫자·하이픈)                        → data/site_setup.json
  2 현장 프로파일      default | academy (기기엔 deploy/academy 가 없어 **필수 보호구 기본값만** 고른다)
  3 카메라(반복)       ① rtsp://user:pass@ip:port/path 형식 ② **프레임 1장 수신**(worker._open_capture — 워커와 같은 열기 경로)
                      → camera_registry.upsert(enabled=True): 원본은 data/camera_secrets.json, 공개 cameras.json 은 마스킹
  4 텔레그램          토큰·chat_id → notify.yaml 기록 → **getMe ok=true** (dispatcher.selftest_channels)
  5 이메일(선택)       SMTP → 연결·STARTTLS 만(로그인 안 함 — 계정 잠금 위험) · 건너뛰면 **경고**(채널 하나뿐)
  6 필수 보호구        프로파일 기본값 제시 → config/tuning.yaml 의 ppe.required 로 기록
  7 파일 생성 확인     만들어진 파일이 **실제로 있는지** 같은 실행에서 확인(규칙 11) + 비밀 파일 icacls

보안: 토큰·비밀번호는 **화면에 다시 찍지 않는다**. USB 에 저장하지 않는다(기기의 config/notify.yaml·data/camera_secrets.json 에만).
비대화식: --answers answers.json (테스트·자동화). 검증기는 순수 함수라 단위 테스트가 실제 카메라·망 없이 돈다.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

APP = Path(__file__).resolve().parents[2]          # <Target>\app  (저장소에서는 저장소 뿌리)
CORE = APP / "vigent-core"
sys.path.insert(0, str(CORE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

PROFILES: dict[str, dict[str, Any]] = {
    "default": {"required_ppe": ["NO-Hardhat", "NO-Safety-Vest", "NO-Mask"], "desc": "코드 기본값(분진 작업장: 마스크 포함)"},
    "academy": {"required_ppe": ["NO-Hardhat", "NO-Safety-Vest"], "desc": "학원 현장(마스크는 필수 보호구 아님 — 08-28 결정)"},
}
_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{1,31}$")
_RTSP_RE = re.compile(r"^rtsp://(?:[^:@/\s]+:[^@/\s]+@)?[^:/\s]+(?::\d{1,5})?(?:/\S*)?$")
_CAMID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,23}$")


# ── 검증기(순수 함수) ──────────────────────────────────────────────────────────
def check_device_name(s: str) -> str | None:
    return None if _DEVICE_RE.match(s or "") else "기기명은 영문·숫자·하이픈 2~32자(첫 글자는 영문·숫자)"


def check_camera_id(s: str) -> str | None:
    return None if _CAMID_RE.match(s or "") else "카메라 id 는 소문자·숫자·_-, 1~24자(예: cam1)"


def check_rtsp(url: str) -> str | None:
    u = (url or "").strip()
    if not _RTSP_RE.match(u):
        return "형식이 rtsp://user:pass@ip:port/path 가 아니다"
    if "@" not in u:
        return None                                   # 자격증명 없는 주소도 허용(공개 스트림)
    return None


def check_chat_id(s: str) -> str | None:
    return None if re.match(r"^-?\d{3,20}$", (s or "").strip()) else "chat_id 는 숫자(그룹은 음수)여야 한다"


def grab_one_frame(source: str, timeout_s: float = 8.0) -> tuple[bool, str]:
    """워커와 **같은 열기 경로**로 프레임 1장. (worker._open_capture: FFMPEG·TCP·5초 타임아웃)"""
    try:
        import worker
        cap = worker._open_capture(source)
        if not cap.isOpened():
            return False, "열기 실패(주소·자격증명·네트워크)"
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                cap.release()
                return True, f"{frame.shape[1]}x{frame.shape[0]}"
        cap.release()
        return False, f"{timeout_s:.0f}초 안에 프레임이 오지 않음"
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {ex}"


def write_required_ppe(tuning_path: Path, classes: list[str]) -> str:
    """config/tuning.yaml 의 ppe.required 를 기록한다. 활성 `ppe:` 블록이 있으면 그 안의 required 를 바꾸고,
    없으면(기본 파일은 주석 처리돼 있다) 끝에 블록을 덧붙인다. 반환: 'replaced' | 'appended'."""
    text = tuning_path.read_text(encoding="utf-8") if tuning_path.exists() else ""
    lines = text.splitlines()
    val = "[" + ", ".join(classes) + "]"
    # 활성 최상위 ppe: 블록 찾기
    start = next((i for i, ln in enumerate(lines) if re.match(r"^ppe:\s*(#.*)?$", ln)), None)
    if start is not None:
        end = next((j for j in range(start + 1, len(lines)) if lines[j] and not lines[j].startswith((" ", "\t", "#"))), len(lines))
        for k in range(start + 1, end):
            if re.match(r"^\s+required:\s*", lines[k]):
                lines[k] = f"  required: {val}   # [setup_wizard] 필수 보호구"
                tuning_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return "replaced"
        lines.insert(start + 1, f"  required: {val}   # [setup_wizard] 필수 보호구")
        tuning_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "replaced"
    block = ["", "# [setup_wizard] 첫 실행 마법사가 기록한 필수 보호구 집합 — 기본 파일의 ppe: 는 주석이라 여기 덧붙인다",
             "ppe:", f"  required: {val}"]
    tuning_path.write_text(text.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8")
    return "appended"


def lock_secret_file(p: Path) -> None:
    """비밀 파일 권한: 관리자·SYSTEM·설치 사용자(M)만. Windows 아니면 아무것도 안 한다."""
    if os.name != "nt" or not p.exists():
        return
    user = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
    try:
        subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", "Administrators:F", "SYSTEM:F", f"{user}:M"],
                       capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001  권한 잠금 실패가 설정을 막지는 않는다 — 결과에 기록만
        pass


# ── 마법사 본체 ─────────────────────────────────────────────────────────────────
class Wizard:
    def __init__(self, answers: dict[str, Any] | None = None, *,
                 frame_grabber: Callable[[str], tuple[bool, str]] = grab_one_frame,
                 telegram_check: Callable[[], dict[str, Any]] | None = None,
                 smtp_check: Callable[[], dict[str, Any]] | None = None,
                 app_root: Path = APP, out=print):
        self.a = answers
        self.grab = frame_grabber
        self.tg_check = telegram_check
        self.smtp_check = smtp_check
        self.app = app_root
        self.out = out
        self.summary: dict[str, Any] = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cameras": [], "warnings": []}

    # 입력: answers 가 있으면 그것을, 없으면 대화식
    def ask(self, key: str, prompt: str, secret: bool = False, default: str = "") -> str:
        if self.a is not None:
            v = self.a.get(key, default)
            return str(v) if v is not None else ""
        if secret:
            return getpass.getpass(prompt + ": ")
        v = input(f"{prompt}{' [' + default + ']' if default else ''}: ").strip()
        return v or default

    def ask_until(self, key: str, prompt: str, check: Callable[[str], str | None], secret: bool = False, default: str = "") -> str:
        while True:
            v = self.ask(key, prompt, secret=secret, default=default)
            err = check(v)
            if err is None:
                return v
            self.out(f"  ✗ {err}")
            if self.a is not None:
                raise SystemExit(f"[{key}] {err}")          # 비대화식은 재입력이 없다 — 실패로 끝낸다

    def run(self) -> dict[str, Any]:
        self.out("=== VIGENT 첫 실행 마법사 ===")
        # 1 기기명
        name = self.ask_until("device_name", "1) 기기명(영문·숫자·하이픈)", check_device_name)
        self.summary["device_name"] = name
        # 2 프로파일
        prof = self.ask("profile", "2) 현장 프로파일 (default | academy)", default="academy").strip().lower()
        if prof not in PROFILES:
            raise SystemExit(f"[profile] 없는 프로파일: {prof} (가능: {', '.join(PROFILES)})")
        self.summary["profile"] = prof
        self.out(f"  프로파일 {prof}: {PROFILES[prof]['desc']}")
        # 3 카메라
        import camera_registry
        cams = self.a.get("cameras", []) if self.a is not None else None
        idx = 0
        while True:
            if cams is not None:
                if idx >= len(cams):
                    break
                c = cams[idx]; idx += 1
                cid, cname, src = str(c.get("id", "")), str(c.get("name", "")), str(c.get("source", ""))
            else:
                cid = input(f"3) 카메라 {idx + 1} id (비우면 끝): ").strip()
                if not cid:
                    break
                idx += 1
                cname = input("   이름: ").strip() or cid
                src = getpass.getpass("   RTSP 주소(rtsp://user:pass@ip:port/path — 화면에 안 보임): ").strip()
            for chk, val in ((check_camera_id, cid), (check_rtsp, src)):
                err = chk(val)
                if err:
                    self.out(f"  ✗ 카메라 {cid or idx}: {err}")
                    raise SystemExit(f"[camera {cid}] {err}") if self.a is not None else None
            if err:
                idx -= 1; continue
            ok, info = self.grab(src)
            if not ok:
                self.out(f"  ✗ 카메라 {cid}: 프레임 수신 실패 — {info}")
                if self.a is not None:
                    raise SystemExit(f"[camera {cid}] 프레임 수신 실패: {info}")
                idx -= 1; continue
            camera_registry.upsert(cid, name=cname, source=src, enabled=True, fps=2.0)
            self.summary["cameras"].append({"id": cid, "name": cname, "frame": info})
            self.out(f"  ✓ 카메라 {cid}({cname}) 프레임 수신 {info} → 등록(enabled)")
        if not self.summary["cameras"]:
            self.summary["warnings"].append("카메라 0대 — 서비스는 뜨지만 감시할 것이 없다")
        # 4 텔레그램
        import setup_console
        tok = self.ask_until("telegram_token", "4) 텔레그램 봇 토큰(화면에 안 보임)", lambda s: None if len(s.strip()) >= 20 else "토큰이 너무 짧다", secret=True)
        chat = self.ask_until("telegram_chat", "   chat_id", check_chat_id)
        setup_console.write_notify({"telegram_token": tok.strip(), "telegram_chat": chat.strip()})
        res = (self.tg_check or self._default_tg_check)()
        if res.get("state") != "ok":
            raise SystemExit(f"[telegram] getMe 실패: {res.get('reason') or res.get('state')} — 토큰을 확인하라")
        self.summary["telegram"] = {"ok": True, "bot": res.get("bot")}
        self.out(f"  ✓ 텔레그램 getMe ok (bot @{res.get('bot')})")
        # 5 이메일(선택)
        host = self.ask("smtp_host", "5) SMTP 호스트(비우면 건너뜀 — 경고)", default="")
        if host.strip():
            port = self.ask("smtp_port", "   포트", default="587")
            user = self.ask("smtp_user", "   계정")
            pw = self.ask("smtp_pass", "   비밀번호(화면에 안 보임)", secret=True)
            to = self.ask("email_to", "   수신 주소")
            setup_console.write_notify({"telegram_token": "", "telegram_chat": chat.strip(), "smtp_host": host.strip(), "smtp_port": port.strip(),
                                        "smtp_user": user.strip(), "smtp_pass": pw.strip(), "email_to": to.strip()})
            sres = (self.smtp_check or self._default_smtp_check)()
            self.summary["email"] = {"state": sres.get("state"), "reason": sres.get("reason")}
            if sres.get("state") == "ok":
                self.out("  ✓ SMTP 연결·STARTTLS 확인(로그인은 하지 않음)")
            else:
                self.summary["warnings"].append(f"SMTP 확인 안 됨({sres.get('reason')}) — 실제 전송 때 드러난다")
                self.out(f"  ⚠ SMTP 확인 안 됨: {sres.get('reason')}")
        else:
            self.summary["email"] = {"state": "skipped"}
            self.summary["warnings"].append("이메일 채널 없음 — 채널이 하나뿐이면 그것이 죽는 순간 경보가 아무에게도 가지 않는다(2026-08-21 실제 사고, 20일간 213건 유실)")
            self.out("  ⚠ " + self.summary["warnings"][-1])
        # 6 필수 보호구
        default_ppe = PROFILES[prof]["required_ppe"]
        raw = self.ask("required_ppe", f"6) 필수 보호구(쉼표, 기본 {','.join(default_ppe)})", default=",".join(default_ppe))
        classes = [c.strip() for c in raw.split(",") if c.strip()]
        allowed = {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"}
        bad = [c for c in classes if c not in allowed]
        if bad or not classes:
            raise SystemExit(f"[required_ppe] 허용 값 {sorted(allowed)} 만 가능: {bad or '비어 있음'}")
        how = write_required_ppe(self.app / "config" / "tuning.yaml", classes)
        self.summary["required_ppe"] = {"classes": classes, "tuning_yaml": how}
        self.out(f"  ✓ ppe.required = {classes} ({how})")
        # 7 파일 확인 + 잠금
        must = {"config/notify.yaml": self.app / "config" / "notify.yaml",
                "data/cameras.json": self.app / "data" / "cameras.json",
                "data/camera_secrets.json": self.app / "data" / "camera_secrets.json"}
        missing = [k for k, p in must.items() if not (p.is_file() and p.stat().st_size > 0)]
        if self.summary["cameras"] == [] and "data/cameras.json" in missing:
            missing = [m for m in missing if not m.startswith("data/")]      # 카메라 0대면 레지스트리 파일이 없는 게 정상
        if missing:
            raise SystemExit(f"[files] 만들어져야 할 파일이 없다: {missing}")
        for k in ("config/notify.yaml", "data/camera_secrets.json"):
            lock_secret_file(must[k])
        # 공개 레지스트리에 비밀이 새지 않았는지 — 같은 실행에서 확인
        pub = must["data/cameras.json"]
        if pub.is_file():
            txt = pub.read_text(encoding="utf-8")
            for c in (self.a.get("cameras", []) if self.a is not None else []):
                m = re.match(r"^rtsp://([^:@/]+):([^@/]+)@", str(c.get("source", "")))
                if m and m.group(2) in txt:
                    raise SystemExit("[files] cameras.json 에 비밀번호가 평문으로 들어갔다 — 마스킹 실패")
        (self.app / "data").mkdir(parents=True, exist_ok=True)
        (self.app / "data" / "site_setup.json").write_text(json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.out(f"=== 완료: 카메라 {len(self.summary['cameras'])}대 · 경고 {len(self.summary['warnings'])}건 → data/site_setup.json ===")
        return self.summary

    @staticmethod
    def _default_tg_check() -> dict[str, Any]:
        from agents import dispatcher
        return dispatcher.selftest_channels(force=True)

    @staticmethod
    def _default_smtp_check() -> dict[str, Any]:
        from agents import dispatcher
        return dispatcher.selftest_smtp()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", default="", help="비대화식 답변 JSON(테스트·자동화)")
    a = ap.parse_args()
    answers = json.loads(Path(a.answers).read_text(encoding="utf-8")) if a.answers else None
    Wizard(answers).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
