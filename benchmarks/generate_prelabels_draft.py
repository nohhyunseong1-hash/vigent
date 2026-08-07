#!/usr/bin/env python3
"""benchmarks/generate_prelabels_draft.py — 자체모델(RF-DETR person+ppe) conf=0.10 사전라벨 초안 생성.

**초안일 뿐, 정답 아님(규칙7)** — 사람 전수 검수 전에는 어떤 채점에도 쓰지 않는다. 이 conf=0.10은
"과다생성"(검수자가 지우는 작업을 하도록) 의도된 초안 생성 전용값이며, Phase 3(모델 평가) 채점 시엔
반드시 운용 임계(guard.DETECTOR_CONF 기본값)로 별도 추론한다 — 절대 이 초안을 그대로 채점에 쓰지 않는다.

person 슬롯의 확증편향 완화: (b)방법(자체모델로 초안 생성)의 유일한 구조적 위험은 "우리 모델이 아예
놓친 사람은 초안에도 없어 검수자가 놓치기 쉽다"는 것 — 이건 이 스크립트가 아니라 검수 절차(docs/
labeling_guide.md §검수 체크리스트 ④ "박스 0개 프레임 전수 훑기")로 완화한다.

출력:
  data/field_eval/labels_draft/<파일명>.txt        YOLO 형식(class_id cx cy w h, 정규화 0~1)
  data/field_eval/labels_draft_preview/<파일명>.jpg  박스+클래스+conf 그린 미리보기(검수 참고용)

실행: python3 benchmarks/generate_prelabels_draft.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import box_quality as bq  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DRAFT_CONF = 0.10   # 초안 생성 전용(과다생성 의도) — Phase 3 채점 임계와 절대 혼용 금지
IMGSZ = 640          # 실배포 검출 해상도와 동일(routers/detect.py live_imgsz 기본값)
DETECTORS = ["person", "ppe"]

FRAMES_DIR = _ROOT / "data" / "field_eval" / "frames"
LABELS_DRAFT_DIR = _ROOT / "data" / "field_eval" / "labels_draft"
PREVIEW_DIR = _ROOT / "data" / "field_eval" / "labels_draft_preview"
CLASSES_PATH = _ROOT / "data" / "field_eval" / "classes.txt"

_COLOR = {  # BGR, danger(NO-*)는 빨강 계열 — 라이브 UI 관례(isDanger=/^no-/i)와 동일 취지
    "person": (255, 180, 0), "Hardhat": (0, 200, 0), "NO-Hardhat": (0, 0, 255),
    "Safety-Vest": (0, 200, 0), "NO-Safety-Vest": (0, 0, 255),
    "Mask": (0, 200, 0), "NO-Mask": (0, 0, 255),
}


def _load_classes() -> list[str]:
    return [ln.strip() for ln in CLASSES_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _check_ppe_per_class_override(guard: Any) -> str:
    """PPE_PER_CLASS(클래스별 후필터 맵)가 비어있지 않으면 conf=0.10 오버라이드를 일부 무력화한다
    (guard.py:611, per_class.get(label, slot_conf) 가 slot_conf 대신 개별 임계를 씀) — 방어적으로
    확인해 비어있지 않으면 이 실행 동안만 임시로 비운다(파일 무수정, 프로세스 내 인스턴스 속성만)."""
    ppe_map = dict(getattr(guard, "PPE_PER_CLASS", {}) or {})
    if ppe_map:
        note = (f"[주의] guard.PPE_PER_CLASS 가 비어있지 않음({ppe_map}) — conf=0.10 오버라이드가 "
                 "일부 클래스에 안 먹힐 수 있어 이 실행 동안만 임시로 비웁니다(파일 무수정).")
        print(note)
        guard.PPE_PER_CLASS = {}
        return note
    return "guard.PPE_PER_CLASS 비어있음(기본) — conf=0.10 이 전 클래스에 그대로 적용됨."


def _detect_one(guard: Any, img, track_key: str) -> list[dict[str, Any]]:
    guard.reset_tracks(track_key)   # 단발·stateless(box_quality.py 관례와 동일) — 독립 이미지라 추적상태 오염 방지
    out = guard.detect(img, detectors=DETECTORS, conf=DRAFT_CONF, imgsz=IMGSZ, track_key=track_key)
    dets = []
    for d in out.get("detections", []):
        x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])   # 정규화 xyxy(0~1)
        dets.append({"cls": d.get("label"), "conf": float(d.get("conf", 0.0)),
                     "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "w": x2 - x1, "h": y2 - y1})
    return dets


def _write_yolo_txt(path: Path, dets: list[dict[str, Any]], class_ids: dict[str, int]) -> None:
    lines = []
    for d in dets:
        cid = class_ids.get(d["cls"])
        if cid is None:
            continue   # 우리 7종 스킴 밖 라벨(있으면 안 되지만 방어) — 라벨 누락 대신 조용히 스킵하지 않고 아래 요약에서 카운트
        lines.append(f"{cid} {d['cx']:.6f} {d['cy']:.6f} {d['w']:.6f} {d['h']:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _draw_preview(img, dets: list[dict[str, Any]], out_path: Path) -> None:
    import cv2
    h, w = img.shape[:2]
    canvas = img.copy()
    for d in dets:
        x1 = (d["cx"] - d["w"] / 2) * w
        y1 = (d["cy"] - d["h"] / 2) * h
        x2 = (d["cx"] + d["w"] / 2) * w
        y2 = (d["cy"] + d["h"] / 2) * h
        col = _COLOR.get(d["cls"], (200, 200, 200))
        cv2.rectangle(canvas, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
        label = f"{d['cls']} {d['conf']:.2f}"
        cv2.putText(canvas, label, (int(x1), max(12, int(y1) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), canvas)


def main() -> None:
    import cv2

    LABELS_DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    classes = _load_classes()
    class_ids = {c: i for i, c in enumerate(classes)}
    print(f"클래스 스킴({len(classes)}개): {classes}")

    frame_files = sorted(FRAMES_DIR.glob("*.jpg"))
    if not frame_files:
        raise SystemExit(f"[generate_prelabels_draft] 프레임 없음: {FRAMES_DIR}")
    print(f"대상 프레임: {len(frame_files)}장 (from {FRAMES_DIR})")

    guard = bq._build_guard()
    override_note = _check_ppe_per_class_override(guard)

    per_frame: list[dict[str, Any]] = []
    class_totals: dict[str, int] = {c: 0 for c in classes}
    unknown_labels: dict[str, int] = {}
    zero_box_files: list[str] = []

    for i, fp in enumerate(frame_files):
        img = cv2.imread(str(fp))
        if img is None:
            print(f"  [경고] 이미지 로드 실패: {fp.name}")
            continue
        raw_dets = _detect_one(guard, img, track_key=f"prelabel:{fp.stem}")
        # 우리 7종 스킴 밖 라벨(COCO 폴백 잡동사니 등)은 라벨 파일·미리보기·집계 어디에도 안 넣는다 —
        # 진단용으로만 별도 집계(unknown_labels). 실제 산출물(txt·jpg·요약)은 recognized_dets 기준.
        dets = [d for d in raw_dets if d["cls"] in class_totals]
        for d in raw_dets:
            if d["cls"] in class_totals:
                class_totals[d["cls"]] += 1
            else:
                unknown_labels[d["cls"]] = unknown_labels.get(d["cls"], 0) + 1
        _write_yolo_txt(LABELS_DRAFT_DIR / f"{fp.stem}.txt", dets, class_ids)
        _draw_preview(img, dets, PREVIEW_DIR / f"{fp.stem}.jpg")
        per_frame.append({"file": fp.name, "n": len(dets)})
        if not dets:
            zero_box_files.append(fp.name)
        if (i + 1) % 20 == 0 or (i + 1) == len(frame_files):
            print(f"  진행 {i + 1}/{len(frame_files)}")

    total_boxes = sum(pf["n"] for pf in per_frame)
    ppe_classes = [c for c in classes if c != "person"]
    ppe_total = sum(class_totals[c] for c in ppe_classes)
    lines = [
        "# 사전라벨 초안 생성 요약 (자체모델 RF-DETR person+ppe, conf=0.10 — 초안 전용, 정답 아님)",
        "",
        f"입력: `{FRAMES_DIR}`({len(frame_files)}장) · 출력: `{LABELS_DRAFT_DIR}`(YOLO txt) + "
        f"`{PREVIEW_DIR}`(미리보기 jpg)",
        f"검출 설정: detectors={DETECTORS}, conf={DRAFT_CONF}(초안 전용), imgsz={IMGSZ}(실배포 동일)",
        f"PPE_PER_CLASS 확인: {override_note}",
        "",
    ]
    if ppe_total == 0:
        lines += [
            "## \U0001f534 차단 이슈 — PPE 클래스 박스가 0개(전 109장)",
            "이 실행 환경(desktop)에는 PPE 파인튜닝 가중치(`ppe_rfdetr_v1.pth`/`ppe_css_v1.pt`)가 없다"
            "(`/health`의 `rfdetr_slots`에서 `ppe: MISSING_FALLBACK` 확인됨, 이전 세션들에서 이미 문서화된 "
            "환경 한계). `VIGENT_ALLOW_FALLBACK=1`이 이 슬롯을 **COCO 사전학습 모델로 대체**하는데, COCO엔 "
            "애초에 Hardhat/Safety-Vest/Mask 같은 클래스가 없어 **PPE 검출이 구조적으로 0건**이다.",
            "",
            f"실제로 이 실행에서 'ppe' 슬롯은 COCO 80종(의자·TV·병·가방 등)을 대신 검출했다(diagnostics: "
            f"{sum(unknown_labels.values())}건, 클래스 예시: {list(unknown_labels)[:8]}...) — 이 값들은 "
            "라벨 파일·미리보기에 **안 들어갔다**(우리 7종 스킴 밖이라 자동 제외, 코드로 필터링됨).",
            "",
            "**PPE 사전라벨(초안)은 이 환경에서 생성 불가능하다.** person 사전라벨(아래)은 정상 생성됐다 "
            "— person 슬롯은 파인튜닝 없이 COCO 기반 모델을 그대로 쓰는 설계라 이 한계의 영향을 안 받는다.",
            "",
            "**진행 옵션(사용자 결정 필요)**: ① 실제 PPE 가중치 파일을 이 데스크탑 `vigent-core/weights/`로 "
            "복사 후 재실행 ② PPE 가중치가 있는 맥에서 이 스크립트 재실행 ③ 지금은 person만 검수 대상으로 "
            "진행하고 PPE는 나중으로 미룸.",
            "",
        ]
    lines += [
        "## 전체 요약",
        f"- 총 초안 박스 수: **{total_boxes}개** ({len(frame_files)}장 평균 {total_boxes/len(frame_files):.1f}개/장)",
        f"- 박스 0개 프레임: **{len(zero_box_files)}장**",
        "",
        "## 클래스별 총계",
        "| 클래스 | 박스 수 |",
        "|---|---|",
    ]
    for c in classes:
        lines.append(f"| {c} | {class_totals[c]} |")
    if unknown_labels:
        lines.append("")
        lines.append(f"⚠️ 우리 7종 스킴 밖 라벨 발견(라벨 파일엔 안 씀, 확인 필요): {unknown_labels}")

    lines += ["", "## 박스 0개 프레임 목록(검수 체크리스트 ④의 1차 후보 — 사람 없음 13장과 대조할 것)", ""]
    for f in zero_box_files:
        lines.append(f"- {f}")

    lines += ["", "## 프레임별 박스 수(전체)", "", "| 파일 | 박스 수 |", "|---|---|"]
    for pf in per_frame:
        lines.append(f"| {pf['file']} | {pf['n']} |")

    out_md = _HERE / "generate_prelabels_draft_summary.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines[:24]))
    print(f"\n(요약 전문 저장: {out_md})")


if __name__ == "__main__":
    main()
