"""zone_geom.py — 위험구역 순수 기하 헬퍼 (B7). 의존 없음(fastapi/app_state 무관).

web_util(웹 계층)·rfdetr_service·worker·ml 스크립트가 '위험구역 점 추출'을 공유하되,
web_util 을 import 하면 딸려오는 fastapi/app_state 를 ml 스크립트에 끌어들이지 않도록
순수 모듈로 분리한다(P2-11 에서 ml/rfdetr_zone_track 제외 사유 해소 — 그 프로토타입은 2026-09-06 감사에서 삭제됨).
"""
from __future__ import annotations


def zone_points(z: dict) -> list[tuple[float, float]]:
    """위험구역 json dict → 정규화 (x,y) 튜플 목록. worker·rfdetr_service·ml 공용(P2-11/B7)."""
    return [(p["x"], p["y"]) for p in z.get("points", [])]
