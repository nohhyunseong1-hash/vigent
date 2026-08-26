"""테스트 공용 — 소스에서 **함수 본문**을 안정적으로 뽑는다.

★[2026-08-26] 이 헬퍼가 생긴 이유: 소스 검사 테스트들이 `src[i:i+400]` 처럼
**고정 길이로 잘라** 검사했는데, 주석이 길어지자 검사 대상이 범위 밖으로 밀려
**오탐 실패**가 났다. 문서를 자세히 쓸수록 테스트가 깨지는 구조는 잘못됐다.

또 주석에는 "이전에는 이렇게 했다" 같은 **옛 코드가 인용**되기 마련이라,
주석을 포함해 검사하면 `assertNotIn` 이 엉뚱하게 걸린다. 그래서 주석을 걷어낸
**실행 코드만** 돌려준다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def function_source(rel_path: str, func_name: str) -> str:
    """`rel_path` 안 `func_name` 의 본문을 다음 최상위 def/class 직전까지 돌려준다."""
    src = (ROOT / rel_path).read_text(encoding="utf-8")
    i = src.index(f"def {func_name}")
    rest = src[i:]
    ends = [p for p in (rest.find("\ndef ", 1), rest.find("\nclass ", 1),
                        rest.find("\n@", 1)) if p > 0]
    return rest[:min(ends)] if ends else rest


def executable_lines(body: str) -> str:
    """주석을 걷어낸 실행 코드만(주석에 인용된 옛 코드에 속지 않도록)."""
    return "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())


def code_of(rel_path: str, func_name: str) -> str:
    return executable_lines(function_source(rel_path, func_name))
