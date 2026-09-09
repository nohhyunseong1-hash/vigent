#!/usr/bin/env python3
"""현장 프로파일 드리프트 검사 — 전역 기본값에 키가 추가돼도 프로파일이 뒤처지지 않게.

★배경(2026-08-24): 학원 프로파일은 `copy` 로 **파일 전체를 덮는다**(deploy/academy/
README_academy.md). 그래서 전역 기본값에 키가 추가될 때마다 프로파일은 **조용히
뒤처진다** — 실제로 6개 키가 누락돼, 프로파일을 적용하는 순간 [F5](전역 구역 폴백
차단)와 [F6](자동 파기 스레드)이 학원에서 무효화되는 상태였다. 아무 경고도 없었다.

검사 3종(기준: deploy/academy/profile_intent.yaml):
  1) **누락** — 기본값에 있는 키가 프로파일에 없다  → 드리프트. 무조건 실패.
  2) **미선언 값 변경** — 값이 다른데 intent 에 선언이 없다 → 실패.
     (프로파일의 존재 이유가 '값을 바꾸는 것'이므로 차이 자체는 정상이나,
      **무엇을 왜 바꿨는지 적혀 있어야** 나중에 되돌릴 수 있다.)
  3) **미선언 추가 키** — 프로파일에만 있는데 선언이 없다 → 실패.
  4) ★[CODE_REVIEW M7-1, 2026-09-06] **읽히지 않는 키** — 파일에 적힌 (섹션.키)가 코드 어디서도
     읽히지 않는다 → 실패. 실사고: 최상위 `alerts:` 가 두 번 있어 앞 블록 8키가 파싱 결과에서 사라졌는데
     이 검사는 파싱 결과만 비교해 잡지 못했다. 이제 로더가 중복 키를 거부하고(tuning.load_file), 이 검사가
     "파일에 적힌 키 ⊆ 코드가 읽는 키" 를 보장한다(죽은 설정·오타 키 차단).

사용:
    python scripts/check_profile_drift.py           # 검사만(게이트용, 실패 시 exit 1)
    python scripts/check_profile_drift.py --fix     # 누락 키를 기본값으로 채워 넣는다

★--fix 는 **누락만** 채운다. 값 변경·추가 키는 사람이 판단할 문제라 손대지 않는다.
  주석을 보존하기 위해 YAML 재직렬화가 아니라 **줄 단위 삽입**으로 넣는다
  (프로파일 파일의 17KB 주석은 실측 근거 기록이라 잃으면 안 된다).
"""
from __future__ import annotations

import argparse
import re as _re
import sys
from pathlib import Path
from typing import Any

import yaml

try:   # Windows 콘솔(cp949)이 한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
import tuning  # noqa: E402  [M7-1] 엄격 로더(중복 키 거부)를 게이트도 그대로 쓴다

_INTENT = _ROOT / "deploy" / "academy" / "profile_intent.yaml"
_CORE = _ROOT / "vigent-core"

# 코드가 tuning 값을 읽는 3가지 형태(모듈 별칭 tuning/_tun/_tuning 포함):
#   tuning.val("sec", "key", …) · tuning.section("sec")[.get("key")] · tv(_tun, 형변환, "sec", "key", …)
_RE_VAL = _re.compile(r'\.val\(\s*"([A-Za-z_]+)"\s*,\s*"([A-Za-z_]+)"')
_RE_VAL_DYN = _re.compile(r'\.val\(\s*"([A-Za-z_]+)"\s*,(?=\s*[^\s"])')   # 키가 변수(래퍼 함수, 예: relay._v) → 섹션 통째
_RE_SECTION = _re.compile(r'\.section\(\s*"([A-Za-z_]+)"\s*\)(?:\s*\.get\(\s*"([A-Za-z_]+)")?')
_RE_TV = _re.compile(r'\btv\(.*?"([A-Za-z_]+)"\s*,\s*"([A-Za-z_]+)"')   # 형변환 인자에 람다(괄호)가 와도 같은 줄이면 잡는다


def code_read_keys(core: Path = _CORE) -> set[str]:
    """코드가 읽는 (섹션.키) 집합. 섹션을 통째로 읽으면 '섹션.*' 로 표기한다."""
    out: set[str] = set()
    for p in core.rglob("*.py"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _RE_VAL.finditer(t):
            out.add(f"{m.group(1)}.{m.group(2)}")
        for m in _RE_VAL_DYN.finditer(t):
            out.add(f"{m.group(1)}.*")
        for m in _RE_TV.finditer(t):
            out.add(f"{m.group(1)}.{m.group(2)}")
        for m in _RE_SECTION.finditer(t):
            out.add(f"{m.group(1)}.{m.group(2)}" if m.group(2) else f"{m.group(1)}.*")
    return out


def unread_keys(path: Path, read: set[str] | None = None) -> list[str]:
    """path 의 2단계 (섹션.키) 중 코드가 읽지 않는 것. 섹션 통째 읽기('섹션.*')면 그 아래는 전부 읽힌 것으로 본다."""
    read = code_read_keys() if read is None else read
    data = tuning.load_file(path)
    out: list[str] = []
    for sec, body in data.items():
        if f"{sec}.*" in read:
            continue
        keys = list(body) if isinstance(body, dict) else [None]
        for k in keys:
            name = f"{sec}.{k}" if k is not None else str(sec)
            if name not in read:
                out.append(name)
    return sorted(out)


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    """중첩 딕셔너리를 'a.b.c' 평면 키로. 리스트는 잎으로 취급(순서·내용 통째 비교)."""
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flat(v, key))
        else:
            out[key] = v
    return out


def _load(p: Path) -> dict:
    return tuning.load_file(p)   # [M7-1] 중복 키·파싱 오류는 예외(조용한 덮어쓰기 금지)


def check_one(name: str, spec: dict) -> list[str]:
    """한 쌍(기본값↔프로파일)을 검사해 문제 목록을 돌려준다(빈 목록 = 통과)."""
    base_p, prof_p = _ROOT / spec["base"], _ROOT / spec["profile"]
    if not base_p.exists() or not prof_p.exists():
        return [f"[{name}] 파일 없음: {spec['base']} 또는 {spec['profile']}"]
    fb, fp = _flat(_load(base_p)), _flat(_load(prof_p))
    declared_over = spec.get("overrides") or {}
    declared_only = spec.get("profile_only") or {}
    # [F-34 후속, 2026-09-10] 의도적 **누락** 선언(`omitted`) — 키 또는 접두(하위 키 전부). 이유 없는 누락은 여전히 실패.
    #   예: 학원 프로파일이 judgment.ergonomics.joints 를 통째로 비워 근골격 규칙을 끈다(ErgonomicsTracker 는 joints 가 없으면 비활성).
    declared_omit = spec.get("omitted") or {}
    problems: list[str] = []

    def _omitted(key: str) -> bool:
        return any(key == o or key.startswith(o + ".") for o in declared_omit)

    for k in fb:
        if k not in fp and not _omitted(k):
            problems.append(
                f"[{name}] ★누락: '{k}' 이 프로파일에 없다(기본값 {fb[k]!r}). "
                f"프로파일을 적용하면 이 설정이 사라진다 — --fix 로 채우거나 의도라면 intent 에 적어라")
    for k in fp:
        if k not in fb and k not in declared_only:
            problems.append(f"[{name}] 미선언 추가 키: '{k}' — intent 의 profile_only 에 이유와 함께 선언하라")
    for k, v in fp.items():
        if k in fb and fb[k] != v and k not in declared_over:
            problems.append(
                f"[{name}] 미선언 값 변경: '{k}' {fb[k]!r} → {v!r} — "
                f"intent 의 overrides 에 **왜 바꿨는지** 적어야 나중에 되돌릴 수 있다")
    return problems


def _insert_missing(prof_p: Path, missing: dict[str, Any]) -> list[str]:
    """누락 키를 프로파일 파일에 **줄 단위로** 삽입(주석 보존). 2단계 키만 지원."""
    lines = prof_p.read_text(encoding="utf-8").splitlines()
    added: list[str] = []
    for key in sorted(missing):
        parts = key.split(".")
        if len(parts) != 2:
            print(f"  ⚠ 건너뜀(중첩 3단 이상, 수동 처리 필요): {key}")
            continue
        sec, leaf = parts
        val = missing[key]
        dumped = yaml.safe_dump({leaf: val}, allow_unicode=True, default_flow_style=False).strip()
        # 섹션 헤더를 찾아 그 블록 끝에 삽입한다.
        #   ★꼬리 주석을 허용해야 한다 — "proximity:   # 협착 감지" 같은 줄을 정확일치로
        #     찾으면 실패하고, 그러면 **중복 섹션을 새로 만들어** YAML 뒤쪽-우선 규칙 때문에
        #     원래 섹션이 통째로 가려진다(2026-08-24 실제로 파일을 망가뜨렸다 — 위 안전장치가 잡음).
        _hdr = _re.compile(r"^" + _re.escape(sec) + r":\s*(#.*)?$")
        try:
            si = next(i for i, ln in enumerate(lines) if _hdr.match(ln.rstrip()))
        except StopIteration:
            lines.append(f"{sec}:")
            lines.append(f"  {dumped}    # [드리프트 보충] 전역 기본값에서 상속")
            added.append(f"{key} (새 섹션 {sec})")
            continue
        end = si + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        while end > si + 1 and not lines[end - 1].strip():   # 뒤쪽 빈 줄 앞에 넣는다
            end -= 1
        lines.insert(end, f"  {dumped}    # [드리프트 보충] 전역 기본값에서 상속")
        added.append(key)
    if not added:
        return added
    # ★안전장치: 쓰기 전에 **결과를 검증**한다. 설정 파일을 망가뜨리는 것이 드리프트보다 나쁘다.
    #   ①YAML 로 파싱되는가 ②원래 있던 키가 하나라도 사라지거나 값이 바뀌지 않았는가
    #   ③넣으려던 키가 실제로 들어갔는가 — 하나라도 어긋나면 **쓰지 않고 중단**한다.
    #   (2026-08-24: 꼬리주석 때문에 섹션을 못 찾아 중복 섹션을 만들어 파일을 망가뜨린 적이 있다.)
    before = _flat(yaml.safe_load(prof_p.read_text(encoding="utf-8")) or {})
    candidate = "\n".join(lines) + "\n"
    try:
        after = _flat(yaml.safe_load(candidate) or {})
    except Exception as ex:  # noqa: BLE001
        print(f"  ❌ 중단: 결과가 YAML 로 파싱되지 않는다({type(ex).__name__}) — 파일을 건드리지 않았다")
        return []
    lost = [k for k, v in before.items() if k not in after or after[k] != v]
    if lost:
        print(f"  ❌ 중단: 기존 키 {len(lost)}건이 사라지거나 바뀐다 {lost[:5]} — 파일을 건드리지 않았다")
        return []
    not_added = [k for k in missing if k not in after]
    if not_added:
        print(f"  ❌ 중단: 넣으려던 키가 반영되지 않았다 {not_added[:5]} — 파일을 건드리지 않았다")
        return []
    prof_p.write_text(candidate, encoding="utf-8")
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="누락 키를 기본값으로 채운다(값 변경은 손대지 않음)")
    args = ap.parse_args()

    intent = _load(_INTENT)
    if args.fix:
        for name, spec in intent.items():
            fb = _flat(_load(_ROOT / spec["base"]))
            prof_p = _ROOT / spec["profile"]
            fp = _flat(_load(prof_p))
            missing = {k: v for k, v in fb.items() if k not in fp}
            if not missing:
                print(f"[{name}] 누락 없음")
                continue
            print(f"[{name}] 누락 {len(missing)}건 채우는 중…")
            for k in _insert_missing(prof_p, missing):
                print(f"  + {k}")

    all_problems: list[str] = []
    for name, spec in intent.items():
        try:
            all_problems += check_one(name, spec)
        except tuning.TuningConfigError as ex:
            all_problems.append(f"[{name}] ★설정 파일 오류(중복 키/파싱): {ex}")
            continue
        # [M7-1] 검사 4: 파일에 적힌 키 ⊆ 코드가 읽는 키(기본값·프로파일 둘 다) — tuning.yaml 계열만
        #   (vision.yaml 은 vision_loader/agents 가 구조로 읽어 키 단위 대조 대상이 아니다)
        if not str(spec["base"]).endswith("tuning.yaml"):
            continue
        read = code_read_keys()
        for label, rel in (("기본값", spec["base"]), ("프로파일", spec["profile"])):
            for k in unread_keys(_ROOT / rel, read):
                all_problems.append(f"[{name}] ★읽히지 않는 키({label} {rel}): '{k}' — 코드 어디서도 읽지 않는다(오타·죽은 설정)")

    if all_problems:
        print(f"\n❌ 프로파일 드리프트 {len(all_problems)}건")
        for p in all_problems:
            print(f"  · {p}")
        print("\n누락은 `python scripts/check_profile_drift.py --fix` 로 채울 수 있다.")
        return 1
    print("✅ 프로파일 드리프트 없음 — 기본값의 모든 키가 프로파일에 있고, 모든 차이가 선언됨")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
