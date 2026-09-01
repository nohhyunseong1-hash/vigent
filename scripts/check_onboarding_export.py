#!/usr/bin/env python3
"""[반출 검사] 합류 후보용 문서 묶음을 넘기기 전에 검사한다.

★왜 있는가 (CLAUDE.md 규칙 11)
  "반출 전에 확인한다"를 절차서에만 적으면 급할 때 건너뛴다. 코드로 만든다.
  문서를 외부에 넘기는 것은 **되돌릴 수 없다** — 넘긴 뒤에 발견하면 늦는다.

검사 항목
  1. ⛔이미지·영상 파일이 섞여 있는가 (얼굴·고객사 설비 유출 경로)
  2. ⛔토큰·키·비밀번호 값이 인용됐는가
  3. ⛔`.env` / `camera_secrets` 의 **실제 값**이 들어갔는가
  4. 🟡현장 상호·주소·담당자명 (익명화 여부는 **사람이 정한다** — 위치만 보고)
  5. 🟡저장소 내부 경로·개인 PC 경로 노출
  6. 출처 없는 수치가 있는지 (표본·날짜 표기 힌트가 없는 % 값)

사용:
    python scripts/check_onboarding_export.py docs/onboarding
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MEDIA = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".mp4", ".avi", ".mov", ".webp", ".pdf"}

# ⛔ 차단 — 비밀값이 실제로 인용된 흔적
SECRET = [
    (r"(?i)\b(bot)?token\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}", "토큰 값으로 보이는 문자열"),
    (r"(?i)\bapi[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", "API 키 값"),
    (r"(?i)\bpassword\s*[:=]\s*['\"]?\S{6,}", "비밀번호 값"),
    (r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}", "텔레그램 봇 토큰 형식"),
    (r"rtsp://[^<\s]*:[^<@\s]+@", "RTSP 자격증명이 들어간 주소"),
    (r"(?i)\bchat[_-]?id\s*[:=]\s*['\"]?-?\d{6,}", "텔레그램 chat_id 값"),
]

# 🟡 사람이 판단 — 현장 식별 정보
SITE = [
    (r"삼영중장비", "고객사 상호"),
    (r"\b\d{2,3}-\d{3,4}-\d{4}\b", "전화번호 형식"),
    (r"(?:시|군|구)\s?\S+(?:로|길)\s?\d+", "주소 형식"),
    # ★성씨로 시작하는 이름 + 직함만 잡는다. 처음엔 `[가-힣]{2,3}+직함` 이었는데
    #   "분포를 **대표**하지" · "**과장**이 있다고" 같은 보통명사를 전부 잡아 늑대소년이 됐다.
    (r"(?:김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|전|홍|고|문|양|손|배|백|허|유)"
     r"[가-힣]{1,2}\s*(?:사장|대표|팀장|과장|주임|반장|소장|담당자)(?![하되며])", "인명+직함"),
    (r"[가-힣]{2,4}\s?(?:사장|대표|팀장|과장|주임|반장|소장)님", "인명+직함(님)"),
]

# 🟡 경로 노출
PATHS = [
    (r"C:\\Users\\[A-Za-z0-9_.\-]+", "개인 PC 사용자 경로"),
    (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "이메일 주소"),
]


def scan(root: Path) -> int:
    if not root.is_dir():
        print(f"❌ 폴더 없음: {root}")
        return 2

    md = sorted(root.rglob("*.md"))
    other = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() != ".md"]
    if not md:
        # ★규칙 11 — 대상이 0개면 통과가 아니라 "검사하지 못함"
        print(f"❌ 검사할 .md 가 없다: {root}")
        return 1

    print(f"■ 반출 검사 — {root}")
    print(f"   문서 {len(md)}개 · 그 밖의 파일 {len(other)}개\n")

    block = 0
    review: list[str] = []

    # 1. 미디어
    media = [p for p in other if p.suffix.lower() in MEDIA]
    if media:
        block += len(media)
        print(f"  ⛔ 이미지·영상·PDF {len(media)}개 — **반출 금지**")
        for p in media[:10]:
            print(f"       · {p.relative_to(root)}")
    else:
        print("  ✅ 이미지·영상·PDF 없음 (문서만)")

    if other and not media:
        print(f"  🟡 md 외 파일 {len(other)}개 — 내용 확인 필요")
        for p in other[:10]:
            print(f"       · {p.relative_to(root)}")

    # 2~6. 본문 검사
    sec_hits: list[str] = []
    site_hits: list[str] = []
    path_hits: list[str] = []
    for p in md:
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for pat, why in SECRET:
                if re.search(pat, line):
                    sec_hits.append(f"{p.name}:{i} — {why}")
            for pat, why in SITE:
                if re.search(pat, line):
                    site_hits.append(f"{p.name}:{i} — {why}: {line.strip()[:70]}")
            for pat, why in PATHS:
                if re.search(pat, line):
                    path_hits.append(f"{p.name}:{i} — {why}: {line.strip()[:70]}")

    if sec_hits:
        block += len(sec_hits)
        print(f"\n  ⛔ 비밀값 의심 {len(sec_hits)}건 — **반출 금지**")
        for x in sec_hits[:10]:
            print(f"       · {x}")
    else:
        print("  ✅ 토큰·키·비밀번호 값 인용 없음")

    if site_hits:
        review.append(f"현장 식별 정보 {len(site_hits)}건")
        print(f"\n  🟡 현장 식별 정보 {len(site_hits)}건 — ★익명화 여부는 **사람이 정한다**")
        for x in site_hits[:15]:
            print(f"       · {x}")
    else:
        print("  ✅ 현장 상호·주소·인명 없음")

    if path_hits:
        review.append(f"경로·이메일 노출 {len(path_hits)}건")
        print(f"\n  🟡 개인 경로·이메일 {len(path_hits)}건 — 확인 필요")
        for x in path_hits[:10]:
            print(f"       · {x}")
    else:
        print("  ✅ 개인 PC 경로·이메일 없음")

    # 출처 없는 수치(힌트 검사 — 참고용)
    noref = 0
    for p in md:
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"\d{1,3}\.\d%|\d{1,3}%", line) and not re.search(
                    r"출처|프레임|장|건|표본|dev|소크|v1\.[12]|benchmarks|audit|reports|SAFETY_REVIEW|FINDINGS|COVERAGE|EVAL|기준|이상|이내|초과|미만|§|\[0[0-9]\]|같은 데이터|삭제", line):
                noref += 1
    print(f"\n  {'🟡' if noref else '✅'} 출처 힌트 없는 % 표현: {noref}건"
          f"{' — 눈으로 확인 권장' if noref else ''}")

    # 판정
    print("\n" + "─" * 60)
    if block:
        print(f"❌ **반출 불가** — 차단 항목 {block}건. 위 ⛔ 항목을 먼저 제거하라.")
        return 1
    print(f"✅ 확인함 — 차단 항목 0건. 문서 {len(md)}개 검사 완료.")
    if review:
        print(f"   🟡 사람이 정할 것: {' · '.join(review)}")
    print("   ★저장소 접근·현장 사진은 이 묶음에 포함돼 있지 않다.")
    return 0


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/onboarding")
    return scan(root)


if __name__ == "__main__":
    raise SystemExit(main())
