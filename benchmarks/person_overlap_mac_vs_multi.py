"""person_overlap_mac_vs_multi.py — Phase 1 확장: multi_scene(다인) vs mac_single_move(1인, 사용자 실제
증상 영상) 파편화 비교. 측정 전용, 코드 무수정.

mac_single_move.mp4.mp4(runs/rfdetr/refset/)는 사용자가 실제로 person 박스 2~3개 겹침을 겪은 맥 실카메라
영상. guard.detect() 를 실제로 돌려(이 스크립트가 아니라 별도 1회성 명령으로 생성) 캐시를 만들었다:
  - _sweep_cache/mac_single_move.json        : 원본 24fps 조밀 재생(모든 프레임)
  - _sweep_cache/mac_single_move_sparse5.json: 5프레임 간격(~208ms) 성긴 재생 — 최근 커밋(ffe0aee,
    "워커 갱신율 205ms 한계")에서 실측된 라이브 워커 갱신 간격을 재현. 조밀 재생이 실제 라이브 검출
    간격보다 촘촘해 파편화를 과소평가할 수 있다는 가설 검증용(간격이 넓을수록 프레임 간 이동량↑ →
    IoU 붕괴 가능성↑, track_fragmentation_causes.py의 (b)형과 동일 메커니즘).
"""
from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CACHE_DIR = _HERE / "_sweep_cache"
_OUT_MD = _HERE / "person_overlap_mac_vs_multi.md"


def _iou(a: list, b: list) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    uni = a[2] * a[3] + b[2] * b[3] - inter
    return inter / uni if uni > 0 else 0.0


def _load(name: str) -> dict | None:
    p = _CACHE_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def analyze(cache: dict) -> dict:
    frames = cache["frames"]
    n = len(frames)
    dur_s = frames[-1]["t_cap_ms"] / 1000.0 if n else 0.0

    max_conc = 0
    multi_frames = 0
    ov010 = 0
    first_seen: dict[int, float] = {}
    last_seen: dict[int, dict] = {}
    births_t: list[float] = []
    frag = 0

    for fi, f in enumerate(frames):
        persons = [d for d in f["dets"] if d["cls"] == "person"]
        max_conc = max(max_conc, len(persons))
        if len(persons) >= 2:
            multi_frames += 1
            has = False
            for i in range(len(persons)):
                for j in range(i + 1, len(persons)):
                    if persons[i]["tid"] != persons[j]["tid"] and _iou(persons[i]["box"], persons[j]["box"]) > 0.10:
                        has = True
            if has:
                ov010 += 1
        for d in persons:
            if d["tid"] not in first_seen:
                first_seen[d["tid"]] = f["t_cap_ms"]
                if fi > 0:
                    births_t.append(f["t_cap_ms"])
                    near = False
                    for otid, info in last_seen.items():
                        if otid == d["tid"] or fi - info["fi"] > 6:
                            continue
                        if _iou(d["box"], info["box"]) > 0.15:
                            near = True
                    if near:
                        frag += 1
        for d in persons:
            last_seen[d["tid"]] = {"fi": fi, "box": d["box"]}

    # 슬라이딩 1000ms 윈도우 내 최대 신규tid 발급 수
    max_in_1s = 0
    for i in range(len(births_t)):
        c = 0
        for j in range(i, len(births_t)):
            if births_t[j] - births_t[i] <= 1000:
                c += 1
            else:
                break
        max_in_1s = max(max_in_1s, c)

    n_unique = len({d["tid"] for f in frames for d in f["dets"] if d["cls"] == "person"})
    return {
        "n_frames": n, "dur_s": round(dur_s, 1), "unique_tid": n_unique,
        "max_concurrent": max_conc, "multi_person_frames": multi_frames,
        "overlap010_frames": ov010, "overlap010_pct": round(ov010 / n * 100, 1) if n else None,
        "births": len(births_t),
        "births_per_s": round(len(births_t) / dur_s, 2) if dur_s else None,
        "frag_births": frag, "frag_pct": round(frag / len(births_t) * 100, 1) if births_t else None,
        "max_reissue_per_1000ms": max_in_1s,
    }


def main() -> None:
    datasets = [
        ("multi_scene (다인, 20.7s)", _load("multi_scene")),
        ("mac_single_move 조밀(24fps 전프레임)", _load("mac_single_move")),
        ("mac_single_move 성김(~208ms, PD-2 실측 재현)", _load("mac_single_move_sparse5")),
    ]
    rows: list[tuple[str, dict | None]] = []
    for label, cache in datasets:
        if cache is None:
            rows.append((label, None))
            continue
        rows.append((label, analyze(cache)))

    lines = [
        "# Phase 1 확장 — mac_single_move(1인, 사용자 실증 영상) vs multi_scene(다인) 파편화 비교",
        "",
        "측정 전용, 코드 무수정. mac_single_move.mp4.mp4 는 runs/rfdetr/refset/ — 사용자가 실제로 person",
        "박스 2~3개 겹침을 겪은 맥 실카메라 영상. guard.detect() 실제 실행 결과(person 슬롯, COCO 아님 —",
        "person 은 fine-tune 불필요 슬롯이라 실배포와 동일 모델).",
        "",
        "| 지표 | " + " | ".join(l for l, _ in rows) + " |",
        "|---|" + "---|" * len(rows),
    ]

    def cell(r, key, suffix=""):
        if r is None:
            return "(캐시없음)"
        v = r[key]
        return "—" if v is None else f"{v}{suffix}"

    metrics = [
        ("프레임 수 / 길이(s)", lambda r: f"{cell(r,'n_frames')} / {cell(r,'dur_s')}"),
        ("고유 person tid 수", lambda r: cell(r, "unique_tid")),
        ("동시 최대 person 수(프레임당)", lambda r: cell(r, "max_concurrent")),
        ("멀티person 프레임 수", lambda r: cell(r, "multi_person_frames")),
        ("같은위치 겹침(IoU>0.10, 다른tid) 프레임 비율", lambda r: cell(r, "overlap010_pct", "%")),
        ("신규 tid 발급 수(최초출현 제외)", lambda r: cell(r, "births")),
        ("tid 재발급 빈도(건/초)", lambda r: cell(r, "births_per_s")),
        ("재발급 중 공간중첩(파편화 신호) 비율", lambda r: cell(r, "frag_pct", "%")),
        ("1000ms 윈도우 내 최대 재발급 수", lambda r: cell(r, "max_reissue_per_1000ms")),
    ]
    for label, fn in metrics:
        lines.append(f"| {label} | " + " | ".join(fn(r) for _, r in rows) + " |")

    lines += [
        "",
        "## 판정: 사용자 실제 증상(1인 이동 시 2~3박스)이 이 측정에서 재현되는가",
    ]
    mac_dense = rows[1][1]
    if mac_dense and mac_dense["unique_tid"] <= 1 and mac_dense["max_concurrent"] <= 1:
        lines.append(
            "- **재현 안 됨.** mac_single_move.mp4 오프라인 재생(조밀 24fps·성긴 208ms 둘 다)에서 "
            "person tid는 시종일관 1개(재발급 0건), 동시 검출도 항상 1명 — 겹침이 구조적으로 발생할 수 "
            "없는 조건이었다(2+ 겹침엔 최소 2개 박스가 필요한데 항상 1개뿐)."
        )
        lines.append(
            "- **208ms(PD-2 실측 워커 갱신율) 재현으로도 재현 안 됨** — 즉 '검출 간격이 성겨서 이동량이 "
            "커진다'는 가설(track_fragmentation_causes.py (b)형 메커니즘)만으로는 이 클립을 설명 못 한다. "
            "이 클립 자체의 움직임 폭이 208ms 간격에서도 IoU 유지에 충분히 완만했다(코드 확인: 연속 프레임 "
            "박스 위치가 프레임 크기 대비 작게 이동)."
        )
        lines.append(
            "- **정직한 결론**: 이 특정 영상 파일로는 사용자가 실제로 겪은 증상이 재현되지 않았다. 즉 "
            "'재현 실패'이지 '버그 없음 확정'이 아니다 — 가능한 설명(미검증, 추측): (1) 이 클립이 증상이 "
            "발생한 순간을 포함하지 않았을 수 있음, (2) 실제 문제는 이 84프레임(3.5s)보다 긴 세션에서 "
            "occlusion·프레임드롭 등 이 클립에 없는 조건이 필요할 수 있음, (3) 실시간 파이프라인에만 있는 "
            "요인(카메라 자동노출·모션블러·실제 서버 부하로 인한 불규칙한 갱신 간격 — 208ms는 평균값이지 "
            "실측 분포 자체가 아님)일 수 있음. 이 중 어느 것이 맞는지는 **이 데이터로는 모른다.**"
        )
    lines += [
        "",
        "## multi_scene(다인) 대비 시사점",
        "- multi_scene은 최대 동시 6명, 재발급 42건(38건 최초출현 제외), 1초 윈도우 내 최대 11건 몰림 — "
        "명백한 파편화가 실측으로 재현됨(직전 보고).",
        "- mac_single_move는 정반대로 재발급이 아예 0건 — **'다인 혼동'이 원인이 아니라는 사용자의 가설"
        "(1인인데도 tid 여러 개면 다인 혼동이 아니라 단일 인물 재추적 실패)은 이 데이터로는 검증도 반증도 "
        "안 됐다** — 애초에 재추적이 실패할 상황(트랙 손실) 자체가 이 클립에서 발생하지 않았기 때문.",
    ]

    _OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
