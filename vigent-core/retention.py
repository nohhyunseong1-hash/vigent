"""retention.py — [Z-2] 디스크 보존 정책. `scripts/retention_sweep.py`가 이 모듈을 호출한다.

기본 비활성(`config/tuning.yaml`의 `retention.enabled: false`) + dry_run 기본(true) — 값을
바꾸지 않으면 이 모듈이 있어도 아무 파일도 지우지 않는다(규칙6, 절대 저하 없음).

그룹(A/B/D)은 `docs/disk_retention_policy.md` 설계와 1:1 대응한다(★C그룹(office/sports 개인
모니터링)은 [Z-3, 2026-08-10] office/sports 기능 자체가 영구 삭제되며 함께 제거됨 — 아래
GROUP_DIRS에 더는 없다):
  A(안전 증거) evidence·recognition — pin 예외 있음(증거는 pin 되면 어떤 경로로도 삭제 불가)
  B(감사·문서) audit·tbm·risk_assessments
  D(운영 로그) — 삭제 대상이 아니라 `rotate_if_large()`로 별도 처리(go2rtc.log·legal 차단로그)

라이브 검출과 완전히 분리된 별도 프로세스(cron/작업 스케줄러)로 실행하는 것을 전제로 설계했다
— `guard.detect()`의 `DETECT_LOCK`을 잡지 않고, GPU·모델을 전혀 건드리지 않는다(파일시스템
연산만). 그래서 스위퍼가 오래 걸려도 실시간 검출 지연과 무관하다(측정치는 스크립트가 자체
보고).
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import tuning

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent

# 그룹별 데이터 루트 — data_engine.py·audit_store.py·tbm_store.py·agents/scribe.py 가 실제로
# 쓰는 경로와 동일해야 한다(중복 정의, 이유: retention.py가 이 모듈들을 전부 import하면
# 불필요한 결합이 생긴다 — 경로 상수만 복제).
GROUP_DIRS: dict[str, Path] = {
    "evidence": _ROOT / "data" / "evidence",
    "recognition": _ROOT / "data" / "recognition",
    "audit": _ROOT / "data" / "audit",
    "tbm": _ROOT / "data" / "tbm",
    "risk_assessments": _ROOT / "data" / "risk_assessments",
}
GROUP_LABEL: dict[str, str] = {
    "evidence": "A(안전 증거)", "recognition": "A(안전 증거)",
    "audit": "B(감사·문서)", "tbm": "B(감사·문서)", "risk_assessments": "B(감사·문서)",
}
PINNABLE_GROUPS = {"evidence", "recognition"}   # pin 예외 그룹 — [M6-10] 발송 경보의 그날 인식 로그도 pin 대상

STATUS_PATH = _ROOT / "data" / "retention_status.json"
DELETION_LOG_DIR = _ROOT / "data" / "retention"
# [CODE_REVIEW M6-5] NSSM 서비스 회전본(logs/vigent.err-*·vigent.out-*) — 개수 상한이 없어 크래시 루프에 8,139개가
#   쌓였다. 최근 N개만 유지(개인정보 아님, D그룹 성격). 현재 로그(vigent.err.log)·앱 로그(vigent.log)는 대상 아님.
LOG_DIR = _ROOT / "logs"
ROTATED_LOG_PATTERNS = ("vigent.err-*", "vigent.out-*")


def prune_rotated_logs(keep: int | None = None, execute: bool = False) -> dict[str, Any]:
    """회전 로그를 mtime 최신순으로 keep 개만 남기고 나머지를 지운다(execute=False 면 후보만 센다)."""
    keep = int(_retention_config().get("logs_keep_rotated", 50)) if keep is None else int(keep)
    out: dict[str, Any] = {"dir": str(LOG_DIR), "keep": keep, "total": 0, "candidates": 0, "deleted": 0, "errors": []}
    if keep < 1 or not LOG_DIR.exists():
        return out
    for pat in ROTATED_LOG_PATTERNS:
        files = [p for p in LOG_DIR.glob(pat) if p.is_file()]
        out["total"] += len(files)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            out["candidates"] += 1
            if not execute:
                continue
            try:
                if p.resolve().parent != LOG_DIR.resolve():   # 화이트리스트: logs/ 바로 아래만
                    continue
                p.unlink()
                out["deleted"] += 1
            except OSError as ex:
                out["errors"].append(f"{p.name}: {ex}")
    return out

# 디스크 여유공간 경고 임계값 — 근거: 이벤트 1건당 evidence+recognition 합쳐 수백KB 수준
# (실측 기준 §docs/ops_disk_sizing.md)이라, 5GB면 최소 수만 건의 신규 이벤트를 받을 여유가
# 있다고 보고 "지금 당장 위험은 아니되 조치가 필요한" 경계로 잡았다(운영 판단값, 조정 가능).
WARN_FREE_BYTES = 5 * 1024 ** 3


def rotate_if_large(path: Path, max_mb: float) -> bool:
    """path 가 max_mb 를 넘으면 path.1 로 회전(덮어쓰기)하고 True 반환. D그룹(운영 로그) 전용
    — 법적 보관 요구가 없는 로그만 이 함수로 처리한다(A/B/C는 sweep()의 일수 기반 삭제)."""
    try:
        if not path.exists() or path.stat().st_size < max_mb * 1024 * 1024:
            return False
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
        return True
    except OSError:
        return False


def _retention_config() -> dict[str, Any]:
    return tuning.section("retention")


def group_days(name: str) -> int | None:
    cfg = _retention_config()
    groups = cfg.get("groups") if isinstance(cfg.get("groups"), dict) else {}
    g = groups.get(name) if isinstance(groups, dict) else None
    if isinstance(g, dict) and "days" in g:
        try:
            return int(g["days"])
        except (TypeError, ValueError):
            return None
    return None


def allowed_roots() -> list[Path]:
    """[P1b] 삭제 허용 경로 화이트리스트 — **이 목록 밖은 어떤 경우에도 지우지 않는다.**

    GROUP_DIRS 는 코드 상수지만, 설정·코드 실수로 엉뚱한 경로가 들어오면 되돌릴 수 없는
    삭제가 일어난다. 실제 unlink 직전에 이 목록 하위인지 한 번 더 검사하는 방어선이다.
    기본값은 data/ 하위로 제한한다(config retention.allowed_roots 로 조정 가능).
    """
    cfg = _retention_config().get("allowed_roots")
    if isinstance(cfg, list) and cfg:
        return [(_ROOT / str(p)).resolve() for p in cfg]
    # 기본값 = **선언된 그룹 디렉터리 자체**. "data/ 하위 전부"보다 좁아서 더 안전하고,
    #   실제로 쓸어야 할 곳과 정확히 일치한다(그룹 정의가 곧 삭제 허용 범위).
    out: list[Path] = []
    for d in GROUP_DIRS.values():
        try:
            out.append(d.resolve())
        except OSError:
            continue
    return out


def is_path_allowed(p: Path) -> bool:
    """p 가 화이트리스트 하위인가(심링크·상위탈출 방어를 위해 resolve 후 비교)."""
    try:
        rp = p.resolve()
    except OSError:
        return False
    for root in allowed_roots():
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def first_run_pending() -> bool:
    """[P1b/R2-fix] 보류 상태인가 — **삭제 후보를 실제로 보여준 적이 있어야** 해제된다.

    dry_run 을 false 로 바꾸는 순간 대량 삭제가 일어나는 것을 막는 장치다. 운영자가 첫 주기
    로그에서 '무엇이 지워질 예정인지'를 눈으로 확인한 뒤, 다음 주기부터 실제 삭제가 시작된다.

    ★[R2-fix, 2026-08-18] 이전에는 '한 번 돌면' 해제됐다. 그런데 2026-08-18 실측에서 후보가
    0건인 상태로 첫 주기가 돌아 **빈 목록으로 안전장치가 소진**됐다 — 실제 삭제 대상이 생기는
    약 17일 뒤에는 운영자가 목록을 보지 못한 채 삭제가 시작될 상황이었다. 그래서 해제 조건을
    "삭제 후보가 1건 이상 있는 주기를 보여줬을 때"로 바꾼다. 후보 0건 주기는 몇 번을 돌아도
    보류를 유지한다.
    ★마이그레이션: 구 형식 status.json 은 `armed_with_candidates` 키가 없다 → 보류 상태로
    되돌린다(빈 목록으로 소진된 것이므로 되돌리는 게 맞다).
    """
    st = read_status() or {}
    return not (st.get("delete_armed", False) and st.get("armed_with_candidates", False))


def is_enabled() -> bool:
    return bool(_retention_config().get("enabled", False))


def is_dry_run() -> bool:
    return bool(_retention_config().get("dry_run", True))


PIN_FILE_NAME = "pinned.json"   # [M6-1] 어디에 있든 pin 목록 파일 자체는 절대 삭제 후보가 아니다


def _pinned_paths() -> set[Path]:
    """pin 된 파일의 **resolve() 된 절대경로** 집합 — [M6-2] `\\`·`/`·상대/절대 표기와 무관하게 비교한다."""
    try:
        import data_engine
        out: set[Path] = set()
        for rel in data_engine.pinned_paths():
            try:
                out.add((_ROOT / rel).resolve())
            except OSError:
                continue
        return out
    except Exception:  # noqa: BLE001  pin 조회 실패는 "전부 미pin"으로 취급(삭제를 막는 방향 아님 —
        return set()   # 대신 sweep() 자체가 dry_run 기본이라 실수로 지워지지 않는다)


def scan_group(name: str, days: int | None) -> dict[str, Any]:
    """그룹 디렉터리를 스캔 — days 가 None 이면 삭제후보 계산 없이 크기만 낸다(가시성 전용)."""
    root = GROUP_DIRS[name]
    info: dict[str, Any] = {"dir": str(root.relative_to(_ROOT)), "days": days,
                             "exists": root.exists(), "total_bytes": 0, "file_count": 0,
                             "candidates": [], "oldest_age_days": None}
    if not root.exists():
        return info
    now = time.time()
    pinned = _pinned_paths() if name in PINNABLE_GROUPS else set()
    oldest_age = 0.0
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if fp.name == PIN_FILE_NAME:
            continue   # [M6-1] pin 목록 파일 자체(구 위치 잔재 포함)는 크기 집계·후보 모두에서 제외
        try:
            st = fp.stat()
        except OSError:
            continue
        info["total_bytes"] += st.st_size
        info["file_count"] += 1
        age_days = (now - st.st_mtime) / 86400
        oldest_age = max(oldest_age, age_days)
        if days is not None and age_days > days:
            rel = str(fp.relative_to(_ROOT))
            try:
                if fp.resolve() in pinned:
                    continue   # pin된 증거는 후보에서 제외 — 어떤 경로로도 삭제되지 않는다([M6-2] resolve 비교)
            except OSError:
                pass
            info["candidates"].append({"path": rel, "age_days": round(age_days, 1),
                                        "bytes": st.st_size})
    info["oldest_age_days"] = round(oldest_age, 1) if info["file_count"] else None
    return info


def _write_deletion_audit(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    DELETION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(KST)
    logfile = DELETION_LOG_DIR / f"deletion_{ts.strftime('%Y%m%d')}.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def sweep(execute: bool | None = None, only_group: str | None = None) -> dict[str, Any]:
    """전 그룹 스캔 + (활성화·execute 조건 만족 시) 실삭제. 항상 status.json 을 갱신한다
    (가시성은 enabled 여부와 무관하게 항상 계산 — [Z-2] ①가시성 요구사항).

    execute: None 이면 설정(retention.dry_run)을 따른다. True/False 로 명시 전달하면
    CLI --execute 플래그가 설정을 덮어쓴 것 — 단 retention.enabled=false 면 execute 를
    무엇으로 줘도 실삭제하지 않는다(전체 스위치가 최우선)."""
    t0 = time.time()
    enabled = is_enabled()
    dry_run = is_dry_run() if execute is None else (not execute)
    # [P1b] 첫 실행 안전장치 — 설정(dry_run: false)으로 실삭제가 **처음 켜진 주기**에는
    #   목록만 남기고 지우지 않는다. 운영자가 '무엇이 지워질 예정인지' 확인한 뒤 다음 주기부터
    #   실제 삭제가 시작된다.
    #   ★단 CLI 로 `--execute` 를 명시한 경우(execute is not None)는 보류하지 않는다 —
    #     운영자가 지금 지우겠다고 직접 지시한 것이라 의도가 분명하다. 안전장치는 "설정 한 줄
    #     바꿨더니 대량 삭제가 일어났다"를 막기 위한 것이지 명시 실행을 막는 게 아니다.
    explicit = execute is not None       # CLI --execute: 운영자의 명시 지시 → 보류 우회
    armed_stored = not first_run_pending()

    warnings: list[str] = []
    try:
        free = shutil.disk_usage(_ROOT).free
    except OSError:
        free = None
    if free is not None and free < WARN_FREE_BYTES:
        warnings.append(f"디스크 여유공간 {free / 1024**3:.1f}GB < 경고임계 "
                         f"{WARN_FREE_BYTES / 1024**3:.0f}GB — 조치 필요")

    groups_out: dict[str, Any] = {}
    deletion_entries: list[dict[str, Any]] = []
    unused_groups: list[str] = []
    scanned: list[tuple[str, dict[str, Any], int | None]] = []
    for name, root in GROUP_DIRS.items():
        if only_group and name != only_group:
            continue
        if not root.exists():
            groups_out[name] = {"dir": str(root.relative_to(_ROOT)), "exists": False}
            # [R2-fix] 미사용 그룹(디렉터리 자체가 없음)은 경고가 아니라 정보다 —
            #   매 스위프마다 같은 경고가 쌓이면 진짜 경고가 묻힌다.
            unused_groups.append(name)
            continue
        days = group_days(name)
        info = scan_group(name, days)
        scanned.append((name, info, days))
        groups_out[name] = info

    # [R2-fix] 후보를 다 센 뒤에 삭제 여부를 정한다 — 보류 해제는 "후보가 1건 이상"일 때만.
    total_candidates = sum(len(i.get("candidates") or []) for _, i, _ in scanned)
    will_delete = enabled and not dry_run and (explicit or armed_stored)
    first_run_notice = (enabled and not dry_run and not explicit
                        and not armed_stored and total_candidates > 0)

    for name, info, days in scanned:
        deleted: list[str] = []
        if will_delete and days is not None:
            for cand in info["candidates"]:
                fp = _ROOT / cand["path"]
                # [P1b] 화이트리스트 밖은 어떤 경우에도 삭제하지 않는다(되돌릴 수 없는 작업의 마지막 방어선)
                if not is_path_allowed(fp):
                    warnings.append(f"{name}: 화이트리스트 밖이라 삭제 거부 {cand['path']}")
                    continue
                try:
                    fp.unlink()
                    deleted.append(cand["path"])
                    deletion_entries.append({
                        "ts": datetime.now(KST).isoformat(timespec="seconds"),
                        "group": name, "path": cand["path"],
                        "age_days": cand["age_days"], "bytes": cand["bytes"],
                        "reason": f"days={days} 초과",
                    })
                except OSError as ex:
                    warnings.append(f"{name}: 삭제 실패 {cand['path']} ({ex})")
        info["deleted"] = deleted

    _write_deletion_audit(deletion_entries)

    # [M6-4·M6-5] 개인정보가 아닌 운영 데이터 정리 — 경보 큐 행(30일, 최신 config_error 1건 유지)·NSSM 회전본(최근 50개).
    #   only_group 지정 시(그룹 단독 실행)는 건너뛴다. 삭제 여부는 위와 같은 will_delete 를 따른다(첫 주기 보류 포함).
    queue_out: dict[str, Any] = {}
    logs_out: dict[str, Any] = {}
    if not only_group:
        try:
            import alert_queue
            queue_out = alert_queue.prune(days=int(_retention_config().get("alert_queue_days", 30)),
                                          execute=will_delete)
        except Exception as ex:  # noqa: BLE001
            queue_out = {"error": f"{type(ex).__name__}: {ex}"}
            warnings.append(f"alert_queue 정리 실패: {type(ex).__name__}: {ex}")
        logs_out = prune_rotated_logs(execute=will_delete)
        for e in logs_out.get("errors") or []:
            warnings.append(f"logs: 삭제 실패 {e}")

    # [P1b] 첫 주기: 실제로 지우지 않고 '지워질 예정' 목록을 로그로 남긴다.
    if first_run_notice:
        pend = [(n, len(g.get("candidates") or []),
                 sum(c["bytes"] for c in (g.get("candidates") or [])))
                for n, g in groups_out.items() if isinstance(g, dict)]
        total_n = sum(n for _, n, _ in pend)
        total_b = sum(b for _, _, b in pend)
        try:
            import vlog
            lg = vlog.get("vigent.retention")
            lg.warning("★[첫 주기·삭제 보류] 실삭제가 처음 활성화됐습니다. 이번 주기는 목록만 "
                       "남기고 **아무것도 지우지 않습니다**. 다음 주기부터 실제 삭제가 시작됩니다.")
            lg.warning("  삭제 예정 총 %d건 / %.1f MB", total_n, total_b / 1048576)
            for n, cnt, b in pend:
                if cnt:
                    lg.warning("   - %s: %d건 %.1f MB (보존 %s일 초과)",
                               n, cnt, b / 1048576, group_days(n))
            lg.warning("  목록을 확인한 뒤 문제가 없으면 다음 주기를 기다리면 됩니다. "
                       "중단하려면 config/tuning.yaml 의 retention.dry_run 을 true 로 되돌리세요.")
        except Exception:  # noqa: BLE001
            pass

    elapsed = time.time() - t0
    status = {
        "last_run": datetime.now(KST).isoformat(timespec="seconds"),
        "enabled": enabled, "dry_run": dry_run, "executed_delete": will_delete,
        # [P1b/R2-fix] 보류 해제 상태. **후보를 실제로 보여준 주기**에만 해제된다 —
        #   armed_with_candidates 가 True 여야 first_run_pending() 이 False 가 된다.
        #   후보 0건 주기는 몇 번을 돌아도 보류 유지(빈 목록으로 소진되지 않게).
        "delete_armed": bool(armed_stored or first_run_notice),
        "armed_with_candidates": bool(armed_stored or first_run_notice),
        "first_run_notice": first_run_notice,
        "unused_groups": unused_groups,
        "allowed_roots": [str(r) for r in allowed_roots()],
        "deleted_count": sum(len(g.get("deleted") or []) for g in groups_out.values()
                             if isinstance(g, dict)),
        "deleted_bytes": sum(c.get("bytes", 0) for c in
                             [e for e in deletion_entries]),
        "pending_count": sum(len(g.get("candidates") or []) for g in groups_out.values()
                             if isinstance(g, dict)),
        "elapsed_sec": round(elapsed, 3),
        "disk_free_bytes": free,
        "warnings": warnings,
        "groups": groups_out,
        "alert_queue": queue_out,      # [M6-4] {days, candidates, deleted, kept_config_error}
        "logs": logs_out,              # [M6-5] {keep, total, candidates, deleted}
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def read_status() -> dict[str, Any] | None:
    """[Z-2] /health 노출용 — 캐시된 status.json만 읽는다(라이브 경로에서 디렉터리 재스캔 안 함)."""
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
