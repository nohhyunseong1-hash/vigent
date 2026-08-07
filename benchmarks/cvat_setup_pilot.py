#!/usr/bin/env python3
"""[N-1/2/3] CVAT 태스크 생성 + 라벨 import/export 왕복 테스트 (CVAT REST API).

전제: CVAT 가 로컬에서 기동 중이고(http://localhost:8080) superuser 계정이 있어야 한다.
      D:\\cvat 에서 `docker compose up -d` → `docker exec -it cvat_server python3 ~/manage.py createsuperuser`

사용법(호스트 PowerShell 에서 실행 — 샌드박스가 아니라 CVAT 가 보이는 곳에서):
  python benchmarks/cvat_setup_pilot.py setup      # 태스크 2개 생성 + 이미지 업로드
  python benchmarks/cvat_setup_pilot.py inspect    # 라벨 순서·이미지 목록 검증
  python benchmarks/cvat_setup_pilot.py roundtrip  # import→무수정 export→원본 비교
  python benchmarks/cvat_setup_pilot.py export     # 검수 완료 후 labels/ 로 회수(백업 자동)
  python benchmarks/cvat_setup_pilot.py push89     # 89장 초안을 field_eval_89 태스크에 올림
  python benchmarks/cvat_setup_pilot.py export89   # 89장 검수 결과를 rest89/labels/ 로 회수
  → 아이디·비밀번호는 실행 중에 물어본다(비밀번호는 화면에 안 보임).
    규칙5에 따라 명령줄 인자로 비밀번호를 받지 않는다. 자동화가 필요하면 환경변수
    CVAT_USER / CVAT_PASSWORD 를 쓴다(셸 히스토리에 남지 않게 주의).

setup      : "pilot20"(20장) / "field_eval_89"(나머지 89장) 두 태스크 생성 + 이미지 업로드.
             라벨 목록은 data/field_eval/pilot20/classes.txt 의 순서·이름 그대로.
             생성된 task id 는 data/field_eval/pilot20/.cvat_tasks.json 에 기록(재실행 시 재사용).
roundtrip  : 현재 labels/(검수 반영본)를 pilot20 태스크에 import → 무수정 즉시 export →
             export 결과를 풀어 benchmarks/cvat_roundtrip_check.py 로 원본과 비교.
             ★통과 기준: 20/20 파일 완전 일치.

원본 labels_draft/ 및 labels/ 는 이 스크립트가 수정하지 않는다(읽기 전용).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

try:
    import requests
except ImportError:
    raise SystemExit("requests 미설치 — `pip install requests` 후 다시 실행하세요.") from None

_ROOT = Path(__file__).resolve().parent.parent
_FE = _ROOT / "data" / "field_eval"
_PILOT = _FE / "pilot20"
_REST89 = _FE / "rest89"
_TASKS_JSON = _PILOT / ".cvat_tasks.json"

# CVAT 의 YOLO(darknet) 포맷 이름. 서버 버전에 따라 후보가 다를 수 있어 순서대로 시도한다.
_FORMAT_CANDIDATES = ["YOLO 1.1", "Ultralytics YOLO Detection 1.0"]


# ────────────────────────────── API 래퍼 ──────────────────────────────
class Cvat:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.s = requests.Session()
        r = self.s.post(f"{self.url}/api/auth/login", json={"username": user, "password": password}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"로그인 실패({r.status_code}): {r.text[:300]}")
        key = r.json().get("key")
        if key:
            self.s.headers["Authorization"] = f"Token {key}"
        who = self.s.get(f"{self.url}/api/users/self", timeout=30)
        who.raise_for_status()
        print(f"로그인 OK — user={who.json().get('username')} @ {self.url}")

    def _wait_request(self, rq_id: str, what: str, timeout_s: int = 900) -> dict:
        """신형 /api/requests/{rq_id} 폴링. finished 되면 응답 dict 반환."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            r = self.s.get(f"{self.url}/api/requests/{rq_id}", timeout=60)
            r.raise_for_status()
            j = r.json()
            st = j.get("status")
            if st == "finished":
                return j
            if st == "failed":
                raise SystemExit(f"{what} 실패: {j.get('message') or j}")
            time.sleep(2)
        raise SystemExit(f"{what} 타임아웃({timeout_s}s)")

    # ── 태스크 ──
    def find_task(self, name: str) -> int | None:
        r = self.s.get(f"{self.url}/api/tasks", params={"search": name, "page_size": 100}, timeout=60)
        r.raise_for_status()
        for t in r.json().get("results", []):
            if t.get("name") == name:
                return int(t["id"])
        return None

    def create_task(self, name: str, classes: list[str]) -> int:
        labels = [{"name": c, "attributes": []} for c in classes]
        r = self.s.post(f"{self.url}/api/tasks", json={"name": name, "labels": labels}, timeout=60)
        if r.status_code not in (200, 201):
            raise SystemExit(f"태스크 생성 실패({r.status_code}): {r.text[:500]}")
        tid = int(r.json()["id"])
        print(f"  태스크 생성: '{name}' id={tid} (라벨 {len(classes)}개, 순서 classes.txt 그대로)")
        return tid

    def upload_images(self, task_id: int, images: list[Path]) -> None:
        data: dict[str, str] = {
            "image_quality": "95",
            "sorting_method": "lexicographical",
            "use_zip_chunks": "true",
            "use_cache": "true",
        }
        files = []
        handles = []
        try:
            for i, p in enumerate(sorted(images)):
                fh = p.open("rb")
                handles.append(fh)
                files.append((f"client_files[{i}]", (p.name, fh, "image/jpeg")))
            r = self.s.post(f"{self.url}/api/tasks/{task_id}/data", data=data, files=files, timeout=1800)
        finally:
            for fh in handles:
                fh.close()
        if r.status_code not in (200, 201, 202):
            raise SystemExit(f"이미지 업로드 실패({r.status_code}): {r.text[:500]}")
        rq_id = (r.json() or {}).get("rq_id") if r.content else None
        if rq_id:
            self._wait_request(rq_id, "이미지 처리")
        else:
            self._wait_legacy_task_status(task_id)
        print(f"  이미지 {len(images)}장 업로드·처리 완료 (task {task_id})")

    def _wait_legacy_task_status(self, task_id: int, timeout_s: int = 900) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            r = self.s.get(f"{self.url}/api/tasks/{task_id}/status", timeout=60)
            if r.status_code == 404:  # 신형 서버 — status 엔드포인트 없음
                time.sleep(3)
                return
            j = r.json()
            if j.get("state") == "Finished":
                return
            if j.get("state") == "Failed":
                raise SystemExit(f"이미지 처리 실패: {j.get('message')}")
            time.sleep(2)
        raise SystemExit("이미지 처리 타임아웃")

    def task_frames(self, task_id: int) -> list[str]:
        r = self.s.get(f"{self.url}/api/tasks/{task_id}/data/meta", timeout=60)
        r.raise_for_status()
        return [f["name"] for f in r.json().get("frames", [])]

    # ── 어노테이션 ──
    def import_annotations(self, task_id: int, zip_path: Path, fmt: str) -> None:
        with zip_path.open("rb") as fh:
            r = self.s.post(
                f"{self.url}/api/tasks/{task_id}/annotations",
                params={"format": fmt},
                files={"annotation_file": (zip_path.name, fh, "application/zip")},
                timeout=600,
            )
        if r.status_code not in (200, 201, 202):
            raise SystemExit(f"import 실패({r.status_code}): {r.text[:500]}")
        j = r.json() if r.content else {}
        rq_id = j.get("rq_id") if isinstance(j, dict) else None
        if rq_id:
            self._wait_request(rq_id, "annotation import")
            return
        # 구형: 201 나올 때까지 같은 요청 반복
        t0 = time.time()
        while r.status_code == 202 and time.time() - t0 < 900:
            time.sleep(2)
            r = self.s.post(f"{self.url}/api/tasks/{task_id}/annotations", params={"format": fmt}, timeout=600)
        if r.status_code not in (200, 201):
            raise SystemExit(f"import 마무리 실패({r.status_code}): {r.text[:300]}")

    def count_shapes(self, task_id: int) -> int:
        r = self.s.get(f"{self.url}/api/tasks/{task_id}/annotations", timeout=120)
        r.raise_for_status()
        j = r.json()
        return len(j.get("shapes", [])) + len(j.get("tracks", []))

    def clear_annotations(self, task_id: int) -> None:
        r = self.s.delete(f"{self.url}/api/tasks/{task_id}/annotations", timeout=120)
        if r.status_code not in (200, 204):
            raise SystemExit(f"어노테이션 삭제 실패({r.status_code}): {r.text[:300]}")

    def export_annotations(self, task_id: int, fmt: str, out_zip: Path) -> None:
        # 신형: POST /dataset/export → rq_id → result_url
        r = self.s.post(
            f"{self.url}/api/tasks/{task_id}/dataset/export",
            params={"format": fmt, "save_images": "false"},
            timeout=120,
        )
        if r.status_code in (200, 201, 202) and r.content:
            j = r.json()
            rq_id = j.get("rq_id") if isinstance(j, dict) else None
            if rq_id:
                done = self._wait_request(rq_id, "annotation export")
                url = done.get("result_url") or f"{self.url}/api/requests/{rq_id}/download"
                dl = self.s.get(url, timeout=600)
                dl.raise_for_status()
                out_zip.write_bytes(dl.content)
                return
        # 구형: GET /annotations?action=download 를 200 나올 때까지 반복
        t0 = time.time()
        while time.time() - t0 < 900:
            g = self.s.get(
                f"{self.url}/api/tasks/{task_id}/annotations",
                params={"format": fmt, "action": "download"},
                timeout=600,
            )
            if g.status_code == 200:
                out_zip.write_bytes(g.content)
                return
            if g.status_code not in (201, 202):
                raise SystemExit(f"export 실패({g.status_code}): {g.text[:300]}")
            time.sleep(2)
        raise SystemExit("export 타임아웃")


# ────────────────────────────── 보조 ──────────────────────────────
def _classes() -> list[str]:
    return [c.strip() for c in (_PILOT / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]


def _pilot_images() -> list[Path]:
    return sorted((_PILOT / "images").glob("*.jpg"))


def _rest89_images() -> list[Path]:
    pilot_names = {p.name for p in _pilot_images()}
    return sorted(p for p in (_FE / "frames").glob("*.jpg") if p.name not in pilot_names)


def _load_tasks() -> dict:
    if _TASKS_JSON.exists():
        return json.loads(_TASKS_JSON.read_text(encoding="utf-8"))
    return {}


def _save_tasks(d: dict) -> None:
    _TASKS_JSON.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_yolo_zip(labels_dir: Path, images: list[Path], classes: list[str], out_zip: Path) -> int:
    """CVAT 의 YOLO 1.1 export 와 동일한 구조로 zip 생성(그대로 import 가능)."""
    n_boxes = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("obj.names", "\n".join(classes) + "\n")
        z.writestr("obj.data", f"classes = {len(classes)}\ntrain = data/train.txt\nnames = data/obj.names\nbackup = backup/\n")
        train_lines = []
        for img in images:
            train_lines.append(f"data/obj_train_data/{img.name}")
            txt = labels_dir / (img.stem + ".txt")
            body = txt.read_text(encoding="utf-8") if txt.exists() else ""
            n_boxes += len([ln for ln in body.splitlines() if ln.strip()])
            z.writestr(f"obj_train_data/{img.stem}.txt", body)
        z.writestr("train.txt", "\n".join(train_lines) + "\n")
    return n_boxes


def _flatten_export(zip_path: Path, out_dir: Path) -> int:
    """export zip 안의 *.txt 를 평평한 폴더로 추출(obj.names/train.txt 제외)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if not name.endswith(".txt") or name in ("train.txt", "obj.names", "obj.data"):
                continue
            (out_dir / name).write_bytes(z.read(info))
            n += 1
    return n


def _pick_format(api: Cvat) -> str:
    r = api.s.get(f"{api.url}/api/server/annotation/formats", timeout=60)
    if r.status_code != 200:
        return _FORMAT_CANDIDATES[0]
    names = {e.get("name") for e in r.json().get("exporters", [])}
    for cand in _FORMAT_CANDIDATES:
        if cand in names:
            return cand
    raise SystemExit(f"YOLO 계열 포맷을 서버에서 못 찾음. 지원 목록: {sorted(n for n in names if n)}")


# ────────────────────────────── 명령 ──────────────────────────────
def cmd_setup(api: Cvat) -> None:
    classes = _classes()
    tasks = _load_tasks()
    plan = [("pilot20", _pilot_images()), ("field_eval_89", _rest89_images())]
    for name, imgs in plan:
        if not imgs:
            print(f"  [건너뜀] {name}: 이미지 0장")
            continue
        existing = tasks.get(name) or api.find_task(name)
        if existing:
            print(f"  [기존] 태스크 '{name}' id={existing} — 재생성하지 않음")
            tasks[name] = int(existing)
            continue
        tid = api.create_task(name, classes)
        api.upload_images(tid, imgs)
        tasks[name] = tid
    _save_tasks(tasks)
    print(f"\n태스크 id 기록: {_TASKS_JSON}")
    print(json.dumps(tasks, indent=2, ensure_ascii=False))


def cmd_inspect(api: Cvat) -> None:
    """이미 존재하는 태스크가 쓸 만한 상태인지 검증(라벨 순서·이름, 프레임 목록)."""
    classes = _classes()
    tasks = _load_tasks()
    expect = {"pilot20": [p.name for p in _pilot_images()], "field_eval_89": [p.name for p in _rest89_images()]}
    ok_all = True
    for name, want_imgs in expect.items():
        tid = tasks.get(name) or api.find_task(name)
        if not tid:
            print(f"[{name}] 태스크 없음 — setup 필요")
            ok_all = False
            continue
        tid = int(tid)
        r = api.s.get(f"{api.url}/api/tasks/{tid}", timeout=60)
        r.raise_for_status()
        info = r.json()
        lr = api.s.get(f"{api.url}/api/labels", params={"task_id": tid, "page_size": 100}, timeout=60)
        lr.raise_for_status()
        got_labels = [x["name"] for x in sorted(lr.json().get("results", []), key=lambda x: x["id"])]
        try:
            frames = api.task_frames(tid)
        except Exception:  # noqa: BLE001
            frames = []
        print(f"\n[{name}] id={tid} status={info.get('status')} size={info.get('size')}")
        print(f"  라벨({len(got_labels)}): {got_labels}")
        if got_labels == classes:
            print("  → 라벨 순서·이름 classes.txt 와 정확히 일치 ✔")
        else:
            print(f"  → ★불일치. classes.txt = {classes}")
            ok_all = False
        print(f"  프레임 {len(frames)}장 (기대 {len(want_imgs)}장)")
        missing = sorted(set(want_imgs) - set(frames))
        extra = sorted(set(frames) - set(want_imgs))
        if missing or extra:
            print(f"  → ★파일 불일치: 누락 {len(missing)}개 {missing[:5]} / 초과 {len(extra)}개 {extra[:5]}")
            ok_all = False
        elif frames:
            print("  → 이미지 목록 일치 ✔")
    print("\n=== 점검 결과: " + ("전부 정상 — roundtrip 진행 가능 ===" if ok_all else "★문제 있음 — 아래 내용 확인 필요 ==="))
    if not ok_all:
        raise SystemExit(1)


def cmd_roundtrip(api: Cvat) -> None:
    classes = _classes()
    tasks = _load_tasks()
    tid = tasks.get("pilot20") or api.find_task("pilot20")
    if not tid:
        raise SystemExit("pilot20 태스크가 없다 — 먼저 `setup` 을 실행하세요.")
    tid = int(tid)
    fmt = _pick_format(api)
    print(f"\n왕복 테스트 — task id={tid}, 포맷='{fmt}'")

    labels_dir = _PILOT / "labels"
    images = _pilot_images()
    work = Path(tempfile.mkdtemp(prefix="cvat_rt_"))
    try:
        in_zip = work / "import.zip"
        n_boxes = _build_yolo_zip(labels_dir, images, classes, in_zip)
        print(f"  import zip 생성: {len(images)}장 / 박스 {n_boxes}건 (원본 = 현재 labels/, 무수정)")

        api.import_annotations(tid, in_zip, fmt)
        print("  import 완료 — 아무것도 수정하지 않고 즉시 export")

        out_zip = work / "export.zip"
        api.export_annotations(tid, fmt, out_zip)
        after_dir = work / "after"
        n_files = _flatten_export(out_zip, after_dir)
        print(f"  export 완료 — txt {n_files}개 추출\n")

        rc = subprocess.run(
            [sys.executable, str(_ROOT / "benchmarks" / "cvat_roundtrip_check.py"),
             str(labels_dir), str(after_dir), str(labels_dir / "classes.txt")],
            check=False,
        ).returncode
        if rc != 0:
            print("\n★왕복 테스트 실패 — 위 불일치 내역 확인 필요(클래스 순서/좌표 변환 의심).")
            raise SystemExit(1)
        print("\n★왕복 테스트 통과 — CVAT 로 검수해도 데이터가 깨지지 않는다.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_push89(api: Cvat) -> None:
    """rest89(나머지 89장)의 초안 라벨을 field_eval_89 태스크에 올린다(검수 시작 준비)."""
    classes = _classes()
    tasks = _load_tasks()
    tid = tasks.get("field_eval_89") or api.find_task("field_eval_89")
    if not tid:
        raise SystemExit("field_eval_89 태스크가 없다 — 먼저 `setup` 을 실행하세요.")
    tid = int(tid)
    labels_dir = _REST89 / "labels"
    if not labels_dir.exists():
        raise SystemExit(
            f"{labels_dir} 가 없다 — 먼저 초안을 생성하세요:\n"
            "  python benchmarks/generate_pilot20_dataset.py --set rest89"
        )
    images = sorted((_REST89 / "images").glob("*.jpg"))
    fmt = _pick_format(api)

    # ★CVAT 의 어노테이션 업로드는 기존 것을 덮어쓴다 — 2026-08-08 이 동작으로 사용자의
    #   검수 작업(약 50분)이 소실되는 사고가 실제로 발생했다. 그래서 서버에 뭐라도 있으면
    #   '무조건 먼저 파일로 백업'한 뒤에만 진행한다(규칙2). 확인 없이 지우지 않는다.
    cur = api.count_shapes(tid)
    if cur:
        print(f"  ★현재 task {tid} 에 이미 박스 {cur}건이 있다 — 덮어쓰기 전에 먼저 백업한다.")
        _pull_into(api, tid, _REST89 / "labels")
        print("    ↑ 위 백업 폴더에 현재 서버 상태가 보존됐다.")
        print("    이 위에 초안을 새로 올리면 지금까지의 검수 내용이 서버에서는 사라진다.")
        if input("    그래도 진행하려면 'yes' 입력: ").strip().lower() != "yes":
            raise SystemExit("중단했다 — 서버는 그대로다(백업만 만들어졌다).")
        api.clear_annotations(tid)
        print(f"    기존 어노테이션 삭제 완료(남은 박스 {api.count_shapes(tid)}건)")

    work = Path(tempfile.mkdtemp(prefix="cvat_p89_"))
    try:
        z = work / "import.zip"
        n = _build_yolo_zip(labels_dir, images, classes, z)
        print(f"  import zip: {len(images)}장 / 박스 {n}건 → task {tid} ('{fmt}')")
        api.import_annotations(tid, z, fmt)
        got = api.count_shapes(tid)
        print(f"  검증: 서버에 실제로 올라간 박스 {got}건 (기대 {n}건) — " + ("일치 ✔" if got == n else "★불일치"))
        print("  import 완료 — CVAT 에서 field_eval_89 태스크를 열면 초안 박스가 보인다.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_count(api: Cvat) -> None:
    """두 태스크에 실제로 들어있는 박스 수를 서버에서 조회(중복 여부 확인용)."""
    tasks = _load_tasks()
    expect = {"pilot20": 93, "field_eval_89": 320}
    for name in ("pilot20", "field_eval_89"):
        tid = tasks.get(name) or api.find_task(name)
        if not tid:
            print(f"[{name}] 태스크 없음")
            continue
        n = api.count_shapes(int(tid))
        exp = expect[name]
        mark = "일치 ✔" if n == exp else ("★중복 의심(2배)" if n == exp * 2 else "★기대와 다름")
        print(f"[{name}] id={tid} — 서버 박스 {n}건 (참고 기대치 {exp}건) {mark}")
    print("\n※ 기대치는 '검수 전 초안' 기준이다 — 검수를 진행했다면 달라지는 게 정상이다.")


def cmd_export89(api: Cvat) -> None:
    """89장 검수 완료 후 결과를 rest89/labels/ 로 회수(덮어쓰기 전 자동 백업)."""
    tasks = _load_tasks()
    tid = tasks.get("field_eval_89") or api.find_task("field_eval_89")
    if not tid:
        raise SystemExit("field_eval_89 태스크가 없다.")
    _pull_into(api, int(tid), _REST89 / "labels")


def cmd_export(api: Cvat) -> None:
    """검수 완료 후 CVAT 의 pilot20 어노테이션을 내려받아 labels/ 로 되돌린다(덮어쓰기 전 자동 백업)."""
    tasks = _load_tasks()
    tid = tasks.get("pilot20") or api.find_task("pilot20")
    if not tid:
        raise SystemExit("pilot20 태스크가 없다.")
    _pull_into(api, int(tid), _PILOT / "labels")


def _pull_into(api: Cvat, tid: int, labels_dir: Path) -> None:
    """공통 회수 로직 — 태스크 어노테이션을 내려받아 labels_dir 에 반영(백업 먼저)."""
    fmt = _pick_format(api)
    work = Path(tempfile.mkdtemp(prefix="cvat_ex_"))
    try:
        out_zip = work / "export.zip"
        api.export_annotations(tid, fmt, out_zip)
        after = work / "after"
        n = _flatten_export(out_zip, after)
        if n == 0:
            raise SystemExit("export 결과에 txt 가 없다 — 중단(labels/ 를 건드리지 않음).")

        # 규칙2: 덮어쓰기 전 백업부터. 날짜+시각으로 매번 새 폴더.
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = labels_dir.parent / f"labels_backup_{stamp}"
        shutil.copytree(labels_dir, backup)
        print(f"  백업 생성: {backup.name}")

        changed = 0
        for src in sorted(after.glob("*.txt")):
            dst = labels_dir / src.name
            new = src.read_text(encoding="utf-8")
            old = dst.read_text(encoding="utf-8") if dst.exists() else None
            if old != new:
                changed += 1
            dst.write_text(new, encoding="utf-8")
        total_boxes = sum(len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])
                          for p in labels_dir.glob("*.txt") if p.name != "classes.txt")
        print(f"  labels/ 갱신: {n}개 파일 반영(내용 변경 {changed}개) · 현재 총 박스 {total_boxes}건")
        print(f"  되돌리려면: {backup} 의 내용을 labels/ 로 복사")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="CVAT 태스크 생성 + 왕복 테스트 + 검수결과 회수")
    ap.add_argument("command",
                    choices=["setup", "inspect", "roundtrip", "export", "push89", "export89", "count"])
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--user", default=None, help="미지정 시 실행 중 입력받음")
    args = ap.parse_args()

    # 규칙5: 비밀번호를 명령줄·코드·채팅에 남기지 않는다. 환경변수 또는 대화형 입력만 사용.
    user = args.user or os.environ.get("CVAT_USER") or input("CVAT 아이디: ").strip()
    password = os.environ.get("CVAT_PASSWORD") or getpass.getpass("CVAT 비밀번호(화면에 안 보임): ")

    api = Cvat(args.url, user, password)
    if args.command == "setup":
        cmd_setup(api)
    elif args.command == "inspect":
        cmd_inspect(api)
    elif args.command == "export":
        cmd_export(api)
    elif args.command == "push89":
        cmd_push89(api)
    elif args.command == "export89":
        cmd_export89(api)
    elif args.command == "count":
        cmd_count(api)
    else:
        cmd_roundtrip(api)


if __name__ == "__main__":
    main()
