"""routers/ — 도메인별 APIRouter 모듈 (P1-7 main.py 분할).

각 라우터는 main 을 import 하지 않고, 공유 상태는 app_state 에서 가져온다(순환 방지).
main.py 는 이들을 include_router 로 등록만 한다.
"""
