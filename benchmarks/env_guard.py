"""benchmarks/env_guard.py — 지연·속도 측정 스크립트용 환경 오염 경고
(2026-08-07 Docker/WSL2 설치 후 신설, 2026-08-10 GPU(cu130) 전환 후에도 유효 — 아래 참고).

Docker Desktop(WSL2 백엔드)이 떠 있으면 백그라운드에 vmmem(WSL2 VM) 프로세스가 CPU 코어를
점유해 추론 시간(guard.detect/model.predict 등) 측정값이 실제보다 느리게 나올 수 있다 —
GPU 전환(2026-08-10) 후에도 전처리·후처리·디코드 등 CPU 구간은 남아있어 이 오염 경로가
유효하다(`docs/benchmark_measurement_hygiene.md`). **측정을 막지는 않는다**(사용자 지시),
결과에 경고만 표기한다.

윈도우 전용(이 프로젝트 개발 환경 기준) — 다른 OS에서는 아무것도 하지 않고 조용히 통과한다.
psutil 등 신규 의존성을 추가하지 않기 위해 표준 라이브러리(subprocess)로만 구현했다.
"""
from __future__ import annotations

import subprocess
import sys

_DOCKER_PROCESS_NAMES = (
    "Docker Desktop.exe", "com.docker.backend.exe", "com.docker.build.exe",
    "com.docker.service", "vmmem", "vmmemWSL",
)


def _running_docker_processes() -> list[str]:
    """tasklist 로 확인한, 실행 중인 Docker/WSL VM 관련 프로세스 이름(발견된 것만). 최선노력 —
    Docker Desktop 버전에 따라 정확한 실행 파일명이 다를 수 있어 못 잡을 가능성이 있다
    (그래서 _wsl_running_distros 를 함께 쓴다 — wsl.exe 는 윈도우 내장이라 더 신뢰할 수 있음)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=5, check=False).stdout
    except Exception:  # noqa: BLE001
        return []
    low = out.lower()
    return [name for name in _DOCKER_PROCESS_NAMES if name.lower() in low]


def _wsl_running_distros() -> list[str]:
    """wsl.exe -l --running 으로 확인한 실행 중인 배포 목록(Docker Desktop 은 docker-desktop /
    docker-desktop-data 배포를 씀). wsl.exe 출력은 UTF-16LE라 명시적으로 디코드한다(cp949 등
    콘솔 코드페이지로 읽으면 깨짐 — 이 저장소에서 실측 확인된 이슈)."""
    if sys.platform != "win32":
        return []
    try:
        psi_out = subprocess.run(
            ["wsl.exe", "-l", "--running"], capture_output=True, timeout=5, check=False,
        ).stdout
        text = psi_out.decode("utf-16-le", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    lines = [ln.strip().strip("*").strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln and "설치된" not in ln and "없습니다" not in ln]


def docker_contamination_sources() -> list[str]:
    """오염 가능성 신호 전부(중복 제거 없이 원인별로) — 빈 리스트면 Docker/WSL VM 미감지."""
    found = list(_running_docker_processes())
    distros = _wsl_running_distros()
    if distros:
        found.append(f"wsl 실행중 배포: {', '.join(distros)}")
    return found


def warn_if_docker_running(script_name: str = "") -> bool:
    """오염 가능성이 있으면 stderr 에 경고를 출력하고 True 반환(측정은 막지 않음). docs/
    benchmark_measurement_hygiene.md 의 절차(Docker Desktop 종료 + wsl --shutdown)를 안내한다."""
    found = docker_contamination_sources()
    if not found:
        return False
    label = f"[{script_name}] " if script_name else ""
    print(
        f"⚠️  {label}Docker/WSL2 VM 실행 중 감지({'; '.join(found)}) — "
        "추론 시간 측정값이 오염됐을 수 있습니다(vmmem 이 CPU 점유 — GPU 추론이어도 전처리/후처리 CPU 구간 영향). "
        "정확한 측정이 필요하면 Docker Desktop 종료 + `wsl --shutdown` 후 재실행하세요 "
        "(절차: docs/benchmark_measurement_hygiene.md).",
        file=sys.stderr,
    )
    return True
