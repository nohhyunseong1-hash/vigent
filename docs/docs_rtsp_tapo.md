# Tapo C200 (RTSP) 연결 가이드 — 검증 완료

## 준비물 (Tapo 앱에서)
1. 카메라 계정(RTSP용 ID/비번): Tapo 앱 → 카메라 → 설정 → 카메라 계정
2. 카메라 IP 주소: 설정 → 기기 정보
3. 카메라와 VIGENT PC가 같은 와이파이

## RTSP 주소 형식
rtsp://계정ID:비밀번호@카메라IP:554/stream1   (stream1=1080p, stream2=저화질)

## VIGENT 연결
1. .env 에 추가:  RTSP_URL=rtsp://계정:비번@IP:554/stream1   (.env 는 git 제외)
2. 연결 테스트:   python3 vigent-core/ml/rtsp_test.py
   → ✅ 연결 성공! 해상도 1920x1080 · runs/rtsp/first_frame.jpg 저장

## 검증 결과 (2026-06-21)
- Tapo C200 → VIGENT 영상 수신 성공, 1920x1080 Full HD, 화면 선명
