# [S1] 위험구역 후보 표시 이미지 — 비식별화된 스냅샷 위에 후보 폴리곤을 그린다(확정은 사람 몫).
import numpy as np, cv2
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vigent-core"))
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)
SRC = media("runs/site01_eval/site1")            # 고객사 설비 스틸 — 저장소 밖
OUT = media("runs/site01_eval/zone_candidates")
OUT.mkdir(parents=True, exist_ok=True)
FONT = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 17)
FONT_S = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 13)

def draw(src, out, zones, note):
    img = cv2.imread(str(SRC/src))
    h, w = img.shape[:2]
    over = img.copy()
    for poly, color, _ in zones:
        pts = np.array([[int(x*w), int(y*h)] for x, y in poly], np.int32)
        cv2.fillPoly(over, [pts], color)
    img = cv2.addWeighted(over, 0.30, img, 0.70, 0)
    for poly, color, _ in zones:
        pts = np.array([[int(x*w), int(y*h)] for x, y in poly], np.int32)
        cv2.polylines(img, [pts], True, color, 3)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    for poly, color, label in zones:
        x = min(p[0] for p in poly)*w; y = min(p[1] for p in poly)*h
        tb = d.textbbox((x, max(2,y-24)), label, font=FONT)
        d.rectangle(tb, fill=(0,0,0,160))
        d.text((x, max(2,y-24)), label, font=FONT, fill=(255,255,90))
    tb = d.textbbox((8, h-26), note, font=FONT_S)
    d.rectangle(tb, fill=(0,0,0))
    d.text((8, h-26), note, font=FONT_S, fill=(255,255,255))
    cv2.imwrite(str(OUT/out), cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR))
    print("저장:", OUT/out)

# ① 프레스 라인 전경 (frame_01, 영상 0.5s) — 라인 전면 접근로 + 우측 출입구
draw("frame_01.jpg", "zone_cand_1_press_line.jpg", [
    ([(0.00,0.78),(0.52,0.60),(0.60,0.78),(0.10,1.00),(0.00,1.00)], (0,0,255),
     "후보A 프레스 라인 전면 접근로(협착)"),
    ([(0.80,0.55),(0.97,0.55),(0.97,0.82),(0.80,0.82)], (0,165,255),
     "후보B 출입구(진입 감지)"),
], "후보 확정은 현장 검토 후 — 폴리곤 좌표는 카메라 설치 화각 기준으로 재지정 필요")

# ② HCA-160 금형 작업점 (frame_18, 영상 52.5s) — 작업자 인접 실장면
draw("frame_18.jpg", "zone_cand_2_die_point.jpg", [
    ([(0.26,0.28),(0.74,0.28),(0.80,0.88),(0.20,0.88)], (0,0,255),
     "후보A HCA-160 금형·볼스터(협착 1순위)"),
], "우측에 실제 작업자(person 0.88) 인접 — 침입 판정 시나리오와 동일 구도")

# ③ 통로·적재 구역 (frame_20, 영상 58.5s)
draw("frame_20.jpg", "zone_cand_3_aisle.jpg", [
    ([(0.42,0.55),(0.80,0.42),(1.00,0.60),(1.00,1.00),(0.55,1.00)], (0,165,255),
     "후보C 통로·적재구역(대차 동선)"),
], "적재함 이동·대차 통행 구간 — 통로 침입보다는 적치 감시 용도 검토")
