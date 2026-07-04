"""build_fire_smoke_eval.py — D-Fire(CC0) test split → fire_smoke 평가셋 (T13 Phase 1).

D-Fire 공식 test split(4,306장)에서 **결정적 층화샘플링**으로 fire/smoke 평가 서브셋 구성.
- 클래스 정의(provenance 실측): D-Fire YOLO id **0=smoke, 1=fire** (총 26,557박스 공식 일치로 확정).
- 층화: {both, fire_only, smoke_only, none(FP용)} 버킷별로 파일명 SHA256 순 선택(재현 가능).
- 목표: fire·smoke 각 이미지 ≥150 / 인스턴스 ≥300 (미달 시 assert 실패 → 멈춤).
- 서브셋은 benchmarks/data/fire_smoke/(gitignore) 로 복사, 선택 목록은 매니페스트(커밋)로 남긴다.

실행: /opt/anaconda3/bin/python3 benchmarks/build_fire_smoke_eval.py
원본(~/Desktop/D-Fire (1)/)은 읽기만 — 이동·삭제 안 함.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = Path.home() / "Desktop" / "D-Fire (1)" / "test"
_OUT = _ROOT / "benchmarks" / "data" / "fire_smoke"
_MANIFEST = _ROOT / "benchmarks" / "fire_smoke_eval_manifest.json"

# D-Fire YOLO class id → 표준 라벨(provenance 실측 확정). data.yaml names 는 id 순서(0,1).
_ID2NAME = {0: "smoke", 1: "fire"}
_NAMES = ["smoke", "fire"]           # index = class id

# 버킷별 목표 수(결정적 선택). smoke 는 이미지당 인스턴스 밀도가 낮아(~1.1) 목표 상향 —
# 각 클래스 ≥150장/≥300인스턴스를 여유있게 충족하도록 both·smoke_only 를 크게.
_TARGET = {"both": 180, "fire_only": 40, "smoke_only": 150, "none": 25}


def _counts(label_path: Path) -> tuple[int, int]:
    """(n_fire, n_smoke) — 라벨 파일의 클래스별 박스 수."""
    nf = ns = 0
    if label_path.exists():
        for line in label_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            cid = int(line.split()[0])
            if cid == 1:
                nf += 1
            elif cid == 0:
                ns += 1
    return nf, ns


def _hkey(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def main() -> None:
    img_dir, lbl_dir = _SRC / "images", _SRC / "labels"
    if not img_dir.exists():
        raise SystemExit(f"D-Fire test 없음: {img_dir}")
    buckets: dict[str, list] = {"both": [], "fire_only": [], "smoke_only": [], "none": []}
    for ip in sorted(img_dir.glob("*.jpg")):
        nf, ns = _counts(lbl_dir / (ip.stem + ".txt"))
        b = ("both" if nf and ns else "fire_only" if nf else "smoke_only" if ns else "none")
        buckets[b].append(ip.name)
    # 결정적 선택: 버킷별 SHA256 순 상위 N
    selected = []
    for b, names in buckets.items():
        names_sorted = sorted(names, key=_hkey)
        take = names_sorted[: _TARGET[b]]
        selected.extend(take)
        if len(take) < _TARGET[b]:
            print(f"  ⚠️ 버킷 {b}: {len(names)}장뿐(목표 {_TARGET[b]}) — 전량 사용")
    selected = sorted(set(selected))

    # 복사(원본 읽기만)
    (_OUT / "images").mkdir(parents=True, exist_ok=True)
    (_OUT / "labels").mkdir(parents=True, exist_ok=True)
    for old in (_OUT / "images").glob("*"):
        old.unlink()
    for old in (_OUT / "labels").glob("*"):
        old.unlink()
    fire_img = smoke_img = fire_inst = smoke_inst = 0
    for name in selected:
        stem = Path(name).stem
        shutil.copyfile(img_dir / name, _OUT / "images" / name)
        shutil.copyfile(lbl_dir / (stem + ".txt"), _OUT / "labels" / (stem + ".txt"))
        nf, ns = _counts(lbl_dir / (stem + ".txt"))
        fire_img += nf > 0; smoke_img += ns > 0
        fire_inst += nf; smoke_inst += ns

    (_OUT / "data.yaml").write_text(
        f"names: {_NAMES}\nnc: {len(_NAMES)}\n# D-Fire(CC0) test 서브셋 · id 0=smoke,1=fire\n",
        encoding="utf-8")

    manifest = {
        "source": "D-Fire (gaiasd/DFireDataset), CC0, official test split",
        "acquired": "2026-07-04 (사용자 직접 취득)",
        "class_map": {"0": "smoke", "1": "fire"},
        "selection": "버킷별 파일명 SHA256 오름차순 상위 N(결정적)", "targets": _TARGET,
        "counts": {"images": len(selected),
                   "fire": {"images": fire_img, "instances": fire_inst},
                   "smoke": {"images": smoke_img, "instances": smoke_inst},
                   "buckets": {b: len(v) for b, v in buckets.items()}},
        "files": selected,
    }
    _MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"fire_smoke 평가셋: {len(selected)}장 → {_OUT.relative_to(_ROOT)}")
    print(f"  fire : 이미지 {fire_img} · 인스턴스 {fire_inst}")
    print(f"  smoke: 이미지 {smoke_img} · 인스턴스 {smoke_inst}")
    print(f"  매니페스트: {_MANIFEST.relative_to(_ROOT)}")
    # 완료기준 assert(미달 시 멈춤)
    assert fire_img >= 150 and fire_inst >= 300, f"fire 미달: {fire_img}장/{fire_inst}인스턴스"
    assert smoke_img >= 150 and smoke_inst >= 300, f"smoke 미달: {smoke_img}장/{smoke_inst}인스턴스"
    print("  ✓ 완료기준 통과(각 ≥150장/≥300인스턴스)")


if __name__ == "__main__":
    main()
