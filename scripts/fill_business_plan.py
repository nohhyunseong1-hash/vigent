#!/usr/bin/env python3
"""[문서] 사업계획서 — ★원본 양식 docx 를 그대로 두고 내용만 채운다.

★왜 이 방식인가 (v3 — 2026-09-03)
  v2(md_to_docx.py)는 md 를 새 문서로 변환했는데, 그 결과물에는 원본 양식에 없는
  머리말 주석·부록이 붙고 표 구성도 양식과 달랐다. 사용자가 "원본 양식과 동일한
  양식"을 요구해, **양식 문서를 열어 그 구조(표·제목·골격 문단)를 유지한 채**
  ①파란 안내문구를 내용으로 교체(양식 자체 규정: 파란 글씨는 삭제 후 검정으로 작성)
  ②'◦ / -' 골격 문단을 **서식째 복제**해 내용을 끼워 넣고
  ③지정된 표 셀만 채우는 방식으로 바꿨다.

채우지 않는 곳(공란 유지 — 양식 규정 "해당 없을 시 공란 유지"):
  신청현황 표 전체 · 직업/기업(예정)명/팀 구성 · 사업비 집행계획 금액 ·
  3-3-4 조달계획 · 4-1 대표자 역량(개인정보) — 이들 구역의 파란 안내문구는
  대표가 쓸 때 필요하므로 **남겨 둔다**.

사용:
  python scripts/fill_business_plan.py \
      --template "docs/templates/사업계획서_양식.docx" --out "docs/사업계획서_VIGENT_초안.docx"
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BLUE = {"0000FF", "001AFF"}
HL_RE = re.compile(r"(\[공란[^\]]*\])")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# ──────────────────────────────────────────────────────────────────
# 본문 내용 — (level, text). level 0 = '◦' 골격, 1 = '-' 골격.
# 출처: 자체 실측은 저장소 파일·측정일·표본, 외부는 링크(md 초안과 동일 근거).
# ──────────────────────────────────────────────────────────────────
C: dict[str, list[tuple[int, str]]] = {}

C["1-1. 창업아이템 배경 및 필요성"] = [
    (0, "(외부적 배경 ①) 산재 사망사고가 다시 늘고 있고, 상위 유형이 '카메라로 볼 수 있는 사고'다"),
    (1, "2025년(누적) 재해조사 대상 사고사망자 605명(573건)으로 전년 589명 대비 16명(2.7%) 증가. "
        "유형별로 떨어짐 249명(41.2%) 최다, 부딪힘 62명(+24.0%) 증가, 끼임 50명 "
        "(출처: 고용노동부 보도자료 2026.3.31 — [고용노동부](https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=19159) · "
        "[정책브리핑](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156751984))"),
    (1, "부딪힘·끼임(합계 112명)은 중장비-사람의 위치 관계, 보호구 미착용은 착용 상태에서 비롯 — "
        "사망 원인 상위 유형의 상당수가 영상으로 관찰 가능한 선행 징후(위험반경 접근·미착용)를 가짐"),
    (0, "(외부적 배경 ②) 중대재해처벌법 확대로 소규모 사업장의 안전관리 의무는 커졌으나 수단이 없다"),
    (1, "2024.1.27부터 상시근로자 5인 이상 전 사업장(5~49인 약 83.7만 개 사업장, 종사자 약 800만 명)으로 확대 적용 "
        "(출처: [신·김 법률사무소 뉴스레터](https://www.shinkim.com/kor/media/newsletter/2309) · "
        "[YTN 사이언스 2024.1.26](https://science.ytn.co.kr/program/view.php?mcd=0082&key=202401261712258700))"),
    (1, "위험 확대가 기타업종·영세사업장 중심이라는 보도 "
        "(출처: [아웃소싱타임스 2026.3.31](https://www.outsourcing.co.kr/news/articleView.html?idxno=202354)) — "
        "소규모 사업장은 전담 안전관리 인력을 두기 어렵고, CCTV 는 사고 후 확인용으로만 쓰임"),
    (0, "(외부적 배경 ③) AI 영상분석·CCTV 시장은 성장 국면"),
    (1, "글로벌 CCTV 시장 2026년 581.1억 달러 → 2031년 1,235.2억 달러(CAGR 16.28%) 전망 "
        "(출처: [Mordor Intelligence](https://www.mordorintelligence.kr/industry-reports/cctv-market) ※민간 조사기관 추정치)"),
    (0, "(내부적 배경·동기) [공란 — 대표 작성: 창업 동기·가치관·비전]"),
    (0, "(추진 경과) 신청 전까지 기획·추진 이력"),
    (1, "2026.7 코어 파이프라인(검출→추적→판정→통보) 구현·24시간 연속가동 시험 → "
        "2026.8 검출 모델 Apache-2.0(RF-DETR) 이관·오경보 억제 설계 확정 → "
        "2026.8.27 중장비 교육기관 현장 시험(카메라 1대·54분·929프레임) → "
        "2026.8~9 재분석·정정 이력 공개, 정답지(라벨 데이터) 구축 계획 수립"),
]

C["1-2. 창업아이템 목표시장(고객) 현황 분석"] = [
    (0, "목표시장 정의"),
    (1, "1차: 중장비 교육기관(지게차·굴착기 실습장) — 실습생 다수·안전관리 인력 부족. "
        "현장 시험 1회로 니즈 직접 확인(2026.8.27)"),
    (1, "2차: 5~49인 제조·물류 사업장 — 중대재해처벌법 신규 적용 대상 약 83.7만 개(출처: 1-1 참조)"),
    (0, "고객 도입 장벽을 낮추는 정책 환경"),
    (1, "안전보건공단 「안전일터 조성지원(스마트 안전장비)」 — 소규모 사업장 스마트 안전장비 도입 보조 "
        "(출처: [산업안전포털](https://portal.kosha.or.kr/business-apply-search/biz-support/smart-equipment/info) · "
        "[2025년 공고문](https://oshri.kosha.or.kr/kosha/report/notice.do?mode=download&articleNo=455975&attachNo=449336)) "
        "[공란 — 대표 확인: 당해년도 공고의 지원 품목·한도]"),
    (0, "경쟁 현황과 차별 지점(자체 근거 보유분만 기재)"),
    (1, "[공란 — 대표 작성: 경쟁사 2~3곳 조사(대상 시장·가격대·구축 방식), 출처 링크 포함]"),
    (1, "기존 카메라 재사용: 보급형 IP 카메라(TP-Link Tapo C200) 1대로 전 기능 동작 확인 — 자체 실측 2026.8.27"),
    (1, "알림 피로 억제: 판정 기록 270건 → 휴대폰 알림 19건(14.2:1), 오경보 폭주 시나리오에서 "
        "고정 쿨다운 억제 0.0% 대비 적응형 백오프 89.1% 억제(221→24건, 24시간 실데이터 재현) — "
        "자체 실측(저장소 docs/proposal_base_2026-08.md)"),
    (1, "현장별 판정 프로파일: 현장마다 다른 필수 보호구 구성을 설정으로 흡수(야외 실습장 마스크 제외 등) — "
        "자체 실측 근거(저장소 reports/현장테스트_보고서_20260827_v1.2.md §7-1)"),
    (0, "기대효과 — 이해관계자별"),
    (1, "현장 근로자: 위험구역 침입·방호장치 해제·보호구 미착용이 즉시 감지·조치되어 위험 노출 감소 — "
        "산재 사망·부상을 줄이는 것 자체가 본질 가치"),
    (1, "겸직 안전담당자: 서류(위험성평가·중대재해처벌법 증빙)·설비 점검 부담을 AI Agent 가 대행해 "
        "실질 위험 감소에 집중 가능"),
    (1, "사업주: 사고·고장에 의한 예고 없는 라인 정지가 줄어 생산성·매출·납기를 지키고, "
        "중대재해처벌법 경영책임자 리스크를 증빙 기록으로 관리"),
    (1, "사회혁신: 대기업만 가능했던 스마트 안전·예지보전을 월 구독 저가 모델로 확산해 "
        "'안전·생산성 양극화'를 좁힘. 축적된 공정 데이터와 디지털 트윈은 중소 사업장이 처음 갖는 "
        "디지털 자산이자 혁신 역량이 됨"),
    (0, "기대효과의 근거(외부 실증)"),
    (1, "중소벤처기업부 스마트공장 보급사업 성과분석(2014~2017 도입 5,003개사, 2019.5.23 발표) — "
        "생산성 +30.0%·품질 +43.5%·원가 -15.9%·산업재해 -18.3%, 10인 미만 소기업일수록 효과 큼(생산성 +39.0%) "
        "(출처: [중소벤처기업부 보도자료](https://www.mss.go.kr/site/smba/ex/bbs/View.do?cbIdx=86&bcIdx=1011893&parentSeq=1011893) · "
        "[대한민국 정책브리핑](https://www.korea.kr/special/policyCurationView.do?newsId=148866604))"),
    (1, "한국노동연구원 「산업재해의 경제적 손실비용 관련연구」(박찬임) — 제조업 기업당 연평균 재해자 "
        "0.433명·경제적 손실 245만 원, 재해자 10% 감소 시 매출 약 2.8% 회복 "
        "(출처: [한국노동연구원 보고서 PDF](https://www.kli.re.kr/kliFileDownload?fileName=BBD7920FF418A4CA4925860200243DD8_3.pdf&fileNameOrg=%EC%82%B0%EC%97%85%EC%9E%AC%ED%95%B4%EC%9D%98+%EA%B2%BD%EC%A0%9C%EC%A0%81+%EC%86%90%EC%8B%A4%EB%B9%84%EC%9A%A9+%EA%B4%80%EB%A0%A8%EC%97%B0%EA%B5%AC_%EB%B0%95%EC%B0%AC%EC%9E%84_web.pdf&filePath1=jsphome/DATA/pblctList/issue/BBD7920FF418A4CA4925860200243DD8)) "
        "[공란 — 대표 확인: 보고서 내 해당 수치의 페이지]"),
    (1, "확산 시 사회적 효과(가정 명시): 1,000개 사업장 도입 × 재해 30% 감소 가정 시 연 약 7.4억 원의 "
        "산재 직접손실 예방(산식: 기업당 연 손실 245만 원 × 1,000개 × 30% ≒ 7.35억 원). 간접손실까지 "
        "포함하면 예방 규모는 이보다 크다 — 직·간접 손실 비율은 하인리히 1:4, 국내 실증 1:6.2(사망)·"
        "1:7.1(중경상) (출처: [KCI 논문 — 하인리히 직·간접비용 비율의 검증](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002557365)) "
        "[공란 — 대표 확인: 'ANSI 제조업 9.5배' 표기의 원출처 — 이번 조사에서 확인하지 못함. 확인되면 링크와 함께 기입]"),
]

C["2-1. 창업아이템 현황(준비정도)"] = [
    (0, "신청 시점 개발 현황 — 동작하는 시제품 + 현장 시험 1회"),
    (1, "검출(사람·보호구·지게차·화재) RF-DETR(Apache-2.0) 기반 구현 완료, 추론 60~62ms/프레임(2026.8.29 실측) · "
        "판정 6종 규칙 + 오경보 억제 계층 · 텔레그램 통보(기록 우선 구조) · "
        "자동 검증 5종(린트·타입·테스트 481건·API 차분·설정 드리프트) + CI 운영"),
    (0, "현장 시험 주요 실측(중장비 교육기관, 2026.8.27, 카메라 1대·54분·929프레임 — "
        "저장소 reports/현장테스트_보고서_20260827_v1.2.md)"),
    (1, "지게차 검출률 97.7%(929프레임, 학원 프로파일 YOLO 모델·장면 대본 기준) · 안전모 판정 일치(지상 근거리) 98.4%(252프레임) · "
        "탑승 운전자를 침입자로 오인 0건(200프레임) · 경보 전송 19/19 성공(지연 중앙값 1.8초)"),
    (0, "남은 과제(신청 시점의 정확한 상태)"),
    (1, "사람 인식률(추적 후) 38~42% — 최우선 개선 대상. 원인 분석 결과 검출 불능이 아니라 "
        "임계·추적 단계에서 버려지는 문제로 확인(저임계 재실행 실측) → 학습·튜닝으로 개선 가능한 부류"),
    (1, "정확도 공인에 필요한 정답지(프레임 단위 라벨)가 아직 없음 — 구축 계획·도구 준비 완료 · "
        "유료 고객 0, 파일럿 계약 0 — 본 사업으로 첫 파일럿 구축이 목표"),
]

C["2-2. 창업 아이템 실현 및 구체화 방안"] = [
    (0, "협약기간 내 구체화 목표(판정 기준을 측정 전에 선언하는 방식으로 추진)"),
    (1, "① 정답지 구축: 현장 재촬영(원본 확보 절차 코드화 완료) → 층화 표본 270프레임 라벨링"),
    (1, "② 사람 인식률 개선: 임계·추적 파라미터 최적화 + 원거리 표본 재학습 — 정답지 기준 재현율/정밀도로 채택 판정"),
    (1, "③ 라이선스 정비: 지게차 검출 모델 AGPL(YOLO) → Apache-2.0(RF-DETR) 재학습·이관"),
    (1, "④ 신뢰성 보강: 정지화면 감지·시스템 생존신호·재기동 안전화(자체 결함 원장 상위 3건 해소)"),
    (1, "⑤ 파일럿 1개 현장 다중 카메라 구축·운영 [공란 — 대표 확정: 대상·기간]"),
    (0, "경쟁력 확보 근거 — 측정으로 결정하는 개발 방식"),
    (1, "설계 변경마다 판정 기준을 측정 전에 선언하고 실측으로 채택/기각 · 보고서 정정 이력 공개 "
        "(v1.1→v1.2 정정 9건을 문서 맨 앞에 배치) — 심사·고객 신뢰의 근거"),
    (1, "개인정보 보호 내장: 저장·전송 프레임 얼굴 자동 비식별화, 보존기간 자동 파기 스케줄러 "
        "[공란 — 대표 확인: 영상정보처리기기 고지·동의 절차 법무 확인]"),
    (0, "[공란 — 대표 작성: 대표자·팀원·외부 협력기관 역량을 어느 과제에 투입할지]"),
]

C["3-1. 창업아이템 사업화 추진전략"] = [
    (0, "수익모델(안)"),
    (1, "월 구독(카메라 대수 기준) + 초기 구축비(설치·구역 설정·판정 프로파일 튜닝) "
        "[공란 — 대표 작성: 가격 — 근거 있는 산정 전이므로 공란]"),
    (1, "안전보건공단 스마트 안전장비 지원사업 연계로 고객 부담 경감(1-2 출처 참조, 품목 해당 여부 확인 필요)"),
    (0, "고객 확보 전략"),
    (1, "1단계: 현장 시험을 수행한 중장비 교육기관을 첫 파일럿(유료 전환 협의)으로 추진 "
        "[공란 — 대표 작성: 협의 상태]"),
    (1, "2단계: 교육기관 협회·지역 산업단지 안전 담당 채널 [공란 — 대표 작성: 구체 채널·일정]"),
    (1, "영업 자료는 실측 보고서 기반(측정일·표본 병기) — 근거 없는 정확도 주장을 하지 않는 것을 영업 원칙으로 함"),
]

C["3-2. 생존율 제고를 위한 노력"] = [
    (0, "핵심 성과지표(정량) — 실증 사업장 2곳, 3~6개월 기준"),
    ("TABLE", [
        ["측정 지표", "3~6개월 목표"],
        ["아차사고·설비 이상 전조 가시화", "보이지 않던 전조를 월 단위 수치 리포트로 제공"],
        ["알람 → 조치 완료율", "70% 이상"],
        ["법정 서류(위험성평가·중대재해처벌법 증빙) 작성 시간", "80% 절감"],
        ["긴급(비계획) 정비 비중 · 설비 가동률", "비계획 정비 비중 감소·가동률 상승 [공란 — 목표 수치]"],
        ["위험행동 감지 정확도(정밀도·재현율)", "[공란 — 목표 수치: 정답지 구축 후 현 수준 실측을 근거로 설정]"],
    ]),
    (0, "보조 지표 — 실증 후 유료 전환율 · 월 구독 유지율 · 사업장당 예방 손실 금액(시뮬레이터 산출) · "
        "정부 지원사업 연계 건수"),
    (0, "협약기간 내 사업화 성과 목표 [공란 — 대표 작성: 매출/투자/고용 — 신청현황 표와 일치시킬 것]"),
    (0, "협약 종료 후 지속 계획"),
    (1, "실증 운영 데이터를 정확도 공인 자료로 전환 → 2호점 영업 근거로 사용 · "
        "자동 테스트 481건 등 인수인계 체계 정비로 인력 합류 진입 비용 절감"),
    (1, "[공란 — 대표 작성: 후속 지원사업·투자 유치 계획]"),
]

C["3-2-1. 사업 전체 로드맵"] = [
    (0, "정답지 구축 → 인식률 개선·라이선스 정비 → 파일럿 구축·운영 → 정식 출시(파일럿 실측 기반 영업) "
        "순으로 추진 — 세부 일정은 아래 표 [공란 — 대표 기입: 추진 기간]"),
]

C["3-2-2"] = [   # 협약기간 내 목표(제목에 날짜가 있어 앞부분 일치로 찾는다)
    (0, "협약기간 내 목표: ① 현장 재촬영·정답지 270프레임 ② 사람 인식률 개선(정답지 기준 판정) "
        "③ 신뢰성 보강 상위 3건 ④ 파일럿 1곳 구축 — 세부 일정은 아래 표 [공란 — 대표 기입: 기간]"),
]

C["4-2. 외부 협력기관 현황 및 활용 계획"] = [
    (0, "중장비 교육기관 1곳 — 현장 시험 협력 1회 완료(2026.8.27) "
        "[공란 — 대표 확인: 기관명 기재 여부·협약 형태]"),
    (1, "활용 계획: 재촬영(정답지 구축용) 및 파일럿 후보"),
    (0, "[공란 — 대표 작성: 추가 협력기관(대학·공공기관·민간) 및 세부 활용방안]"),
]

C["4-3. 중장기 사회적 가치 도입계획"] = [
    (0, "사회: 산업재해 예방이라는 사업 목적 자체가 사회적 가치와 정렬(1-1 통계 참조) · "
        "안전 기능의 한계를 정직하게 고지 — 비전 AI 는 확률적이므로 인증 안전장치(방호장치·안전 PLC)를 "
        "대체하지 않는 보조·감시 계층임을 계약·화면에 명시"),
    (0, "개인정보: 얼굴 자동 비식별화·보존기간 자동 파기를 제품 기본값으로 유지"),
    (0, "[공란 — 대표 작성: 고용·환경 등 추가 계획]"),
]

# '◦ [공란]' 한 줄만 넣고 파란 안내는 남겨 두는 구역(대표가 직접 쓸 곳)
BLANK_ONLY = {
    "3-3-3. 정부지원금 집행계획":
        [(0, "[공란 — 대표 작성: 자금 필요성·비목별 산출근거. 위 파란 안내를 따라 작성 후 안내문구 삭제]")],
    "3-3-4. 기타 자금 필요성 및 조달계획":
        [(0, "[공란 — 대표 작성: 법인 설립 비용·추가 자본금·투자유치 목표와 전략]")],
    "4-1. 대표자(팀) 현황 및 보유역량":
        [(0, "[공란 — 대표 작성 ※개인정보 마스킹 규정 준수. 기재 가능 사실 예: 현장 시험 직접 설계·수행(2026.8.27), "
             "측정·검증 중심 개발 문화(자동 테스트 481건·정정 이력 공개 — 저장소로 증빙 가능)]")],
}
KEEP_BLUE = set(BLANK_ONLY)          # 이 구역들의 파란 안내문구는 지우지 않는다

# 표 채움 —— (표 인덱스, 행, 열): 텍스트
ITEM_NAME = ("AI 영상분석 기술이 적용된, 기존 CCTV 로 산업현장 위험(보호구 미착용·위험구역 침입·"
             "중장비 협착)을 실시간 감지해 관리자에게 통보하는 산업안전 모니터링 서비스 VIGENT")
TABLE_FILL = {
    (3, 0, 1): ITEM_NAME,
    (3, 1, 1): "산업안전 AI 모니터링 SW 1식(검출·판정·통보 서버 + 웹 대시보드), 현장 파일럿 구축 1식 "
               "[공란 — 대표 확정: 수량·범위]",
    (5, 1, 1): "정답지 구축", (5, 1, 2): "[공란]", (5, 1, 3): "현장 재촬영(원본 확보 절차 코드화 완료) → 270프레임 라벨링",
    (5, 2, 1): "인식률 개선·라이선스 정비", (5, 2, 2): "[공란]", (5, 2, 3): "정답지 기준 판정 · 지게차 모델 Apache-2.0 이관",
    (5, 3, 1): "파일럿 구축·운영", (5, 3, 2): "[공란]", (5, 3, 3): "1개 현장 다중 카메라 · 운영 데이터 수집",
    (5, 4, 1): "정식 출시", (5, 4, 2): "[공란]", (5, 4, 3): "파일럿 실측 기반 영업 개시",
    (6, 1, 1): "현장 재촬영·정답지", (6, 1, 2): "[공란]", (6, 1, 3): "촬영 검증 도구 완비(scripts/check_raw_capture.py)",
    (6, 2, 1): "사람 인식률 개선", (6, 2, 2): "[공란]", (6, 2, 3): "사전 선언된 판정 기준 적용",
    (6, 3, 1): "신뢰성 보강", (6, 3, 2): "[공란]", (6, 3, 3): "정지화면 감지·생존신호·재기동 안전화",
    (6, 4, 1): "파일럿 구축", (6, 4, 2): "[공란]", (6, 4, 3): "[공란 — 대상 협의 상태에 따라]",
    (9, 1, 1): "[공란 — 중장비 교육기관(기재 여부 대표 결정)]",
    (9, 1, 2): "지게차·중장비 실습장 운영", (9, 1, 3): "현장 시험·재촬영·파일럿 후보(1회 협력 완료 2026.8.27)",
    (9, 1, 4): "협력 중",
    (9, 2, 1): "", (9, 2, 2): "", (9, 2, 3): "", (9, 2, 4): "",       # 양식 예시(○○기업) 비움
}
# 개요(요약) 표 — 병합 셀이라 (행, 셀텍스트열쇠) 대신 행 첫 병합열 오른쪽 셀을 채운다
SUMMARY_FILL = [
    (0, 2, "VIGENT (Vision + AI Agent)"),
    (0, 5, "산업안전 AI 영상분석 소프트웨어(SaaS/구축형)"),
    (1, 1, "현장에 이미 설치된 CCTV·보급형 IP 카메라의 영상을 초당 2회 AI 로 분석해 ①보호구(안전모·조끼) "
           "미착용 ②위험구역 침입 ③지게차 등 중장비 협착 위험 ④급격동작·무동작을 감지하고 관리자 휴대폰"
           "(텔레그램)으로 요약 통보. 기록은 전부 남기고 알림은 억제(자체 실측: 판정 270건→알림 19건, "
           "오경보 폭주 억제 221건→24건). 카메라 교체 없이 SW 만 얹어 도입 부담이 낮음"),
    (2, 1, "2025년 재해조사 대상 사고사망자 605명으로 전년 대비 증가(고용노동부, 2026.3.31). 2024.1.27부터 "
           "중대재해처벌법이 5인 이상 전 사업장으로 확대됐으나 소규모 사업장은 안전관리 인력 상주가 어렵고 "
           "CCTV 는 사고 후 확인용으로만 쓰임 — 상시 감시 공백을 SW 로 메움"),
    (6, 1, "동작하는 시제품 보유(자동 테스트 481건). 중장비 교육기관 1곳에서 실카메라 현장 시험 1회 완료"
           "(54분·929프레임, 2026.8.27) — 지게차 검출 97.7%(학원 프로파일 YOLO 모델·장면 대본 기준), 경보 전송 19/19. 협약기간 내 ①정답지 구축 "
           "②사람 인식률 개선 ③파일럿 1곳 구축 목표"),
    (9, 1, "1차: 중장비 교육기관 · 2차: 50인 미만 제조/물류(중대재해처벌법 신규 적용 약 83.7만 개 사업장). "
           "월 구독(카메라 대수 과금)+초기 구축비. 안전보건공단 스마트 안전장비 지원사업을 도입 장벽 완화에 활용"),
]


def main() -> int:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn

    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true",
                    help="기존 산출물이 커밋본과 달라도 덮어쓴다(백업은 그래도 만든다)")
    args = ap.parse_args()
    tpl, out = Path(args.template), Path(args.out)
    if not tpl.exists():
        print(f"❌ 양식 없음: {tpl}")
        return 1

    # ★[사고 재발 방지 — 2026-09-03] 이 스크립트가 사용자가 직접 편집한 docx 를
    #   확인 없이 덮어써 편집 내용을 유실시킨 일이 실제로 있었다(규칙 2 위반).
    #   → 덮어쓰기 전에 ①무조건 백업을 만들고 ②기존 파일이 저장소 최신 커밋본과
    #     다르면(=사람이 고쳤을 가능성) --force 없이는 중단한다.
    if out.exists():
        import hashlib
        import shutil
        import subprocess
        import time as _time
        ts = _time.strftime("%Y%m%d_%H%M%S")
        backup = out.with_name(f"{out.stem}_백업_{ts}{out.suffix}")
        shutil.copy2(out, backup)
        if not backup.exists() or backup.stat().st_size != out.stat().st_size:
            print(f"❌ 백업 생성 실패 — 진행하지 않는다: {backup}")
            return 1
        cur = hashlib.sha256(out.read_bytes()).hexdigest()
        head = None
        try:
            r = subprocess.run(["git", "-C", str(out.parent), "show", f"HEAD:./{out.name}"],
                               capture_output=True, timeout=30)
            if r.returncode == 0:
                head = hashlib.sha256(r.stdout).hexdigest()
        except Exception:  # noqa: BLE001
            pass
        if cur != head and not args.force:
            print("⛔ 중단: 기존 산출물이 저장소 최신 커밋본과 다르다 — **사람이 편집했을 수 있다.**")
            print(f"   기존 파일 백업: {backup}")
            print("   편집 내용을 확인·병합한 뒤 다시 실행하거나, 정말 덮으려면 --force 를 붙여라.")
            return 1
        print(f"   (덮어쓰기 전 백업 생성: {backup.name})")

    doc = docx.Document(str(tpl))
    body = doc.element.body
    # ★양식 표 참조를 지금 고정한다 — 뒤에서 KPI 표를 중간 삽입하면 인덱스가 밀린다(실제 겪음)
    tpl_tables = list(doc.tables)

    def p_text(el) -> str:
        return "".join(t.text or "" for t in el.findall(".//" + qn("w:t")))

    def is_blue(el) -> bool:
        return any((c.get(qn("w:val")) or "") in BLUE for c in el.findall(".//" + qn("w:color")))

    def first_rpr(el):
        r = el.find(".//" + qn("w:r"))
        if r is None:
            return None
        return r.find(qn("w:rPr"))

    def _norm_rpr(rp, sz: int):
        """★글꼴·크기 통일(사용자 요청 '글꼴 정리') — 삽입하는 런에만 적용, 양식 원문은 불변.

        골격/예시 셀에서 물려받은 rPr 은 구역마다 글꼴·크기가 제각각이라, 명시적으로
        맑은 고딕 + 지정 크기로 덮어쓴다(굵게·형광펜 등 나머지 속성은 유지).
        """
        for tag in ("w:rFonts", "w:sz", "w:szCs"):
            for e in rp.findall(qn(tag)):
                rp.remove(e)
        f = docx.oxml.OxmlElement("w:rFonts")
        f.set(qn("w:ascii"), "Malgun Gothic")
        f.set(qn("w:hAnsi"), "Malgun Gothic")
        f.set(qn("w:eastAsia"), "맑은 고딕")
        rp.insert(0, f)
        for tag in ("w:sz", "w:szCs"):
            e = docx.oxml.OxmlElement(tag)
            e.set(qn("w:val"), str(sz))
            rp.append(e)

    def _set_jc(p_el, val: str):
        """★정렬 통일 — 삽입 문단은 양쪽 맞춤(both)으로."""
        ppr = p_el.find(qn("w:pPr"))
        if ppr is None:
            ppr = docx.oxml.OxmlElement("w:pPr")
            p_el.insert(0, ppr)
        for e in ppr.findall(qn("w:jc")):
            ppr.remove(e)
        jc = docx.oxml.OxmlElement("w:jc")
        jc.set(qn("w:val"), val)
        ppr.append(jc)

    def write_into(proto_el, text: str):
        """골격 문단을 복제해 내용 채움 — 골격의 접두('◦ ' 등)·들여쓰기를 그대로 쓴다."""
        new = copy.deepcopy(proto_el)
        rpr = first_rpr(new)
        prefix = p_text(new)                       # '    ◦ ' / '        - '
        for r in new.findall(qn("w:r")):
            new.remove(r)
        _set_jc(new, "both")

        def add(txt, bold=False, hl=False):
            r = docx.oxml.OxmlElement("w:r")
            if rpr is not None:
                rp = copy.deepcopy(rpr)
            else:
                rp = docx.oxml.OxmlElement("w:rPr")
            _norm_rpr(rp, 20)                      # 본문 10pt 통일
            if bold and rp.find(qn("w:b")) is None:
                rp.append(docx.oxml.OxmlElement("w:b"))
            if hl:
                h = docx.oxml.OxmlElement("w:highlight")
                h.set(qn("w:val"), "yellow")
                rp.append(h)
            t = docx.oxml.OxmlElement("w:t")
            t.set(qn("xml:space"), "preserve")
            t.text = txt
            r.append(rp)
            r.append(t)
            new.append(r)

        def add_link(label, url):
            rid = doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
            h = docx.oxml.OxmlElement("w:hyperlink")
            h.set(qn("r:id"), rid)
            r = docx.oxml.OxmlElement("w:r")
            rp = copy.deepcopy(rpr) if rpr is not None else docx.oxml.OxmlElement("w:rPr")
            _norm_rpr(rp, 20)
            c = docx.oxml.OxmlElement("w:color")
            c.set(qn("w:val"), "0563C1")
            u = docx.oxml.OxmlElement("w:u")
            u.set(qn("w:val"), "single")
            rp.append(c)
            rp.append(u)
            t = docx.oxml.OxmlElement("w:t")
            t.set(qn("xml:space"), "preserve")
            t.text = label
            r.append(rp)
            r.append(t)
            h.append(r)
            new.append(h)

        add(prefix)
        pos = 0
        for lm in LINK_RE.finditer(text):
            _plain(text[pos:lm.start()], add)
            add_link(lm.group(1), lm.group(2))
            pos = lm.end()
        _plain(text[pos:], add)
        return new

    def _plain(text, add):
        for i, seg in enumerate(HL_RE.split(text)):
            hl = bool(i % 2)
            p2 = 0
            for bm in BOLD_RE.finditer(seg):
                if seg[p2:bm.start()]:
                    add(seg[p2:bm.start()], hl=hl)
                add(bm.group(1), bold=True, hl=hl)
                p2 = bm.end()
            if seg[p2:]:
                add(seg[p2:], hl=hl)

    # ── 표 셀 쓰기(본문 채우기에서도 쓰므로 먼저 정의) ────────────
    def set_cell(cell, text, bold=False, center=False, sz=18):
        first = cell.paragraphs[0]
        rpr = first_rpr(first._p)
        for p in list(cell.paragraphs[1:]):
            p._p.getparent().remove(p._p)
        for r in list(first._p.findall(qn("w:r"))):
            first._p.remove(r)
        for hl in list(first._p.findall(qn("w:hyperlink"))):
            first._p.remove(hl)
        _set_jc(first._p, "center" if center else "left")

        def add(txt, b=False, hl=False):
            r = docx.oxml.OxmlElement("w:r")
            rp = copy.deepcopy(rpr) if rpr is not None else docx.oxml.OxmlElement("w:rPr")
            for cel in rp.findall(qn("w:color")):    # 예시 셀의 회색/파랑 물려받지 않기
                rp.remove(cel)
            _norm_rpr(rp, sz)                        # 표 9pt 통일
            if b and rp.find(qn("w:b")) is None:
                rp.append(docx.oxml.OxmlElement("w:b"))
            if hl:
                e = docx.oxml.OxmlElement("w:highlight")
                e.set(qn("w:val"), "yellow")
                rp.append(e)
            t = docx.oxml.OxmlElement("w:t")
            t.set(qn("xml:space"), "preserve")
            t.text = txt
            r.append(rp)
            r.append(t)
            first._p.append(r)

        for i, seg in enumerate(HL_RE.split(text)):
            if seg:
                add(seg, b=bold, hl=bool(i % 2))

    def make_table(rows):
        """추가 표(양식 규정: 추가설명용 표 삽입 가능) — 머리행 음영·전체 테두리."""
        tbl = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        borders = docx.oxml.OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = docx.oxml.OxmlElement(f"w:{edge}")
            for k, v in (("w:val", "single"), ("w:sz", "4"), ("w:color", "8C8C8C")):
                e.set(qn(k), v)
            borders.append(e)
        tbl._tbl.tblPr.append(borders)
        for ri, row in enumerate(rows):
            for ci, txt in enumerate(row):
                cell = tbl.rows[ri].cells[ci]
                set_cell(cell, txt, bold=(ri == 0), center=(ri == 0))
                if ri == 0:
                    shd = docx.oxml.OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), "E8EAED")
                    cell._tc.get_or_add_tcPr().append(shd)
        return tbl._tbl

    # ── 1) 본문 구역 채우기 ──────────────────────────────────────
    HEADINGS = list(C) + list(BLANK_ONLY)
    children = list(body)
    # 제목 요소 찾기(앞부분 일치 — 3-2-2 는 제목에 날짜가 섞여 있다)
    idx_of: dict[str, int] = {}
    for i, el in enumerate(children):
        if not el.tag.endswith("}p"):
            continue
        t = p_text(el).strip()
        for h in HEADINGS:
            if h not in idx_of and t.startswith(h.split(".")[0] + ".") and (h in t or h == "3-2-2"):
                if h == "3-2-2" and not t.startswith("3-2-2"):
                    continue
                idx_of[h] = i
    missing = [h for h in HEADINGS if h not in idx_of]
    if missing:
        print(f"❌ 양식에서 제목을 못 찾음: {missing}")
        return 1

    stats = {"filled": 0, "blue_removed": 0, "skeleton_removed": 0}
    for h in HEADINGS:
        start = idx_of[h]
        nexts = [j for j in idx_of.values() if j > start]
        # 구역 끝: 다음 알려진 제목 또는 표/`<` 캡션 전까지의 골격 구간만 다룬다
        end = min(nexts) if nexts else len(children)
        proto0 = proto1 = None
        region = []
        for j in range(start + 1, end):
            el = children[j]
            if el.tag.endswith("}tbl") or p_text(el).strip().startswith("<"):
                break
            region.append(el)
        for el in region:
            t = p_text(el).strip()
            if t == "◦" and proto0 is None:
                proto0 = el
            if t == "-" and proto1 is None:
                proto1 = el
        if proto0 is None:
            print(f"❌ {h}: '◦' 골격을 못 찾음")
            return 1
        content = C.get(h) or BLANK_ONLY[h]
        anchor = proto0
        for lvl, text in content:
            if lvl == "TABLE":                     # 구역 안 추가 표(KPI 등)
                anchor.addprevious(make_table(text))
                stats["filled"] += 1
                continue
            proto = proto0 if lvl == 0 else (proto1 if proto1 is not None else proto0)
            new = write_into(proto, text)
            anchor.addprevious(new)
            stats["filled"] += 1
        for el in region:                          # 파란 안내·골격 제거
            t = p_text(el).strip()
            if is_blue(el) and h not in KEEP_BLUE:
                body.remove(el)
                stats["blue_removed"] += 1
            elif t in ("◦", "-"):
                body.remove(el)
                stats["skeleton_removed"] += 1

    # ── 2) 양식 표 채우기 ───────────────────────────────────────
    for (ti, ri, ci), text in TABLE_FILL.items():
        set_cell(tpl_tables[ti].rows[ri].cells[ci], text)
        stats["filled"] += 1
    tb4 = tpl_tables[4]
    for ri, ci, text in SUMMARY_FILL:
        # 병합 표 — 행의 고유 셀 목록에서 ci 번째
        seen, uniq = set(), []
        for c in tb4.rows[ri].cells:
            if id(c._tc) not in seen:
                seen.add(id(c._tc))
                uniq.append(c)
        set_cell(uniq[ci], text)
        stats["filled"] += 1

    doc.save(str(out))

    # ── ★규칙 11 — 재개봉 검증 ──────────────────────────────────
    import zipfile
    chk = docx.Document(str(out))
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    full = "".join(m.group(1) for m in re.finditer(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))
    used = re.findall(r'<w:hyperlink[^>]*r:id="([^"]+)"', xml)
    rel_ids = set(re.findall(r'Id="([^"]+)"[^>]*relationships/hyperlink', rels))
    dangling = [i for i in used if i not in rel_ids]
    probes = ["605명", "83.7만", "97.7%", "89.1%", "VIGENT (Vision + AI Agent)",
              "5,003개사", "아차사고", "알람 → 조치 완료율"]
    miss = [p for p in probes if p not in full]
    ok = (out.stat().st_size > 0 and not dangling and not miss
          and len(chk.tables) == 12)               # 양식 11 + KPI 표 1(양식 규정상 추가 허용)
    print(f"{'✅' if ok else '❌'} {out} — {out.stat().st_size / 1024:.0f}KB · "
          f"채움 {stats['filled']} · 파란안내 제거 {stats['blue_removed']} · 골격 제거 {stats['skeleton_removed']} · "
          f"표 {len(chk.tables)}(양식 11 + KPI 1) · 링크 {len(used)}(정합 {not dangling}) · "
          f"공란표시 {full.count('[공란')}곳 · 본문 {len(full):,}자")
    if miss:
        print(f"   ❌ 빠진 내용 표본: {miss}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
