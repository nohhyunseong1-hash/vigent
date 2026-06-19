"""두 Roboflow 데이터셋(office + person)을 통합 클래스로 병합 → 재학습용 데이터셋 생성.

- 동의어 통일: tvmonitor/Computer → monitor, motorbike→motorcycle, aeroplane→airplane
- 이미지는 심볼릭 링크(복사 안 함, 공간 절약), 라벨만 통합 클래스 id 로 재작성
- 출력: data/retrain/merged/{train,valid}/{images,labels} + data.yaml
실행: python3 vigent-core/ml/merge_retrain_data.py
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
RETRAIN = ROOT / "data" / "retrain"
SRCS = {"office": RETRAIN / "office", "person": RETRAIN / "person"}
OUT = RETRAIN / "merged"

# 동의어 → 통일 이름
SYN = {
    "tvmonitor": "monitor", "computer": "monitor", "tv": "monitor",
    "motorbike": "motorcycle", "aeroplane": "airplane",
    "diningtable": "dining table", "pottedplant": "potted plant",
    "cell phone": "cell phone",
}


def norm(name: str) -> str:
    return SYN.get(name.strip().lower(), name.strip().lower())


def load_names(ds: Path) -> list[str]:
    with open(ds / "data.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["names"]


def main() -> None:
    # 1) 통합 클래스 목록 만들기(두 데이터셋 union, person=0 고정)
    all_names: list[str] = []
    per_ds_names = {k: load_names(v) for k, v in SRCS.items()}
    seen = set()
    # person 을 0번으로 먼저
    for nm in ["person", "monitor"]:
        all_names.append(nm); seen.add(nm)
    for names in per_ds_names.values():
        for n in names:
            u = norm(n)
            if u not in seen:
                all_names.append(u); seen.add(u)
    uni_id = {n: i for i, n in enumerate(all_names)}

    # 2) 출력 폴더 초기화
    if OUT.exists():
        shutil.rmtree(OUT)
    for split in ("train", "valid"):
        (OUT / split / "images").mkdir(parents=True, exist_ok=True)
        (OUT / split / "labels").mkdir(parents=True, exist_ok=True)

    stats = {}
    for ds_name, ds in SRCS.items():
        names = per_ds_names[ds_name]
        # 이 데이터셋의 옛 id → 통합 id
        old2new = {i: uni_id[norm(n)] for i, n in enumerate(names)}
        for split in ("train", "valid"):
            img_dir = ds / split / "images"
            lbl_dir = ds / split / "labels"
            if not img_dir.exists():
                continue
            cnt = 0
            for img in img_dir.iterdir():
                if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue
                stem = f"{ds_name}_{img.stem}"   # 파일명 충돌 방지
                # 이미지: 심볼릭 링크
                link = OUT / split / "images" / f"{stem}{img.suffix}"
                if not link.exists():
                    os.symlink(img.resolve(), link)
                # 라벨: 클래스 id 재매핑
                src_lbl = lbl_dir / f"{img.stem}.txt"
                dst_lbl = OUT / split / "labels" / f"{stem}.txt"
                lines_out = []
                if src_lbl.exists():
                    for line in src_lbl.read_text().splitlines():
                        p = line.split()
                        if len(p) < 5:
                            continue
                        old = int(p[0])
                        if old in old2new:
                            lines_out.append(" ".join([str(old2new[old])] + p[1:]))
                dst_lbl.write_text("\n".join(lines_out))
                cnt += 1
            stats[f"{ds_name}/{split}"] = cnt

    # 3) data.yaml 작성
    data = {
        "train": str((OUT / "train" / "images").resolve()),
        "val": str((OUT / "valid" / "images").resolve()),
        "nc": len(all_names),
        "names": all_names,
    }
    with open(OUT / "data.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print("✅ 병합 완료")
    print("   통합 클래스", len(all_names), ":", all_names)
    print("   이미지 수:", stats)
    print("   data.yaml:", OUT / "data.yaml")


if __name__ == "__main__":
    main()
