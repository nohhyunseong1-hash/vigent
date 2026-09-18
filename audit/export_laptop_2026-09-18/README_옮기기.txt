# 개발기로 옮길 파일 — 노트북 소크 결과 묶음 (2026-09-18 수집)

이 폴더 전체(또는 같은 이름의 .zip 하나)를 개발기로 옮기면 된다.
원본 위치: C:\Users\1\Desktop\VIGENT\audit\export_laptop_2026-09-18\  (노트북 저장소 안, 그대로 남아 있음)

## 들어 있는 것 (12개)
1. loadtest_20260909_1032_laptop_base.md / .jsonl   — 1차(기준선) 소크
2. loadtest_20260909_1623_laptop_s2s9.md / .jsonl   — 2차(S2+S9) 소크
3. soak_console_laptop_base.log / soak_console_laptop_s2s9.log — 소크 콘솔 로그(UTF-16, 한글은 기록 시점부터 깨져 있음)
4. power_2026-09-09_before.txt / power_2026-09-09_after.txt / battery_2026-09-09.html — 전원·배터리
5. laptop_results.md — docs\ops\laptop_results.md 사본
6. MANIFEST.txt — 파일별 바이트·SHA256·원본 수정시각, 없음/제외 목록
7. facts.txt — git 상태·reflog, F-34 오류 집계, torch/cv2 버전, /health, 전원 설정, 콘솔 특이사항

## 없어서 못 넣은 것
- audit\rss_manual_laptop_base.txt, audit\rss_manual_laptop_s2s9.txt (노트북에 없음)

## 자격증명
- 포함된 파일 없음(.env, notify.yaml, camera_secrets.json, go2rtc.runtime.yaml 은 처음부터 제외)

## 개발기에서 무결성 확인
- 각 파일의 SHA256 을 MANIFEST.txt 의 값과 대조하면 된다.
