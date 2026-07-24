"""T1 홀드아웃 15케이스 빌더 (재현 가능).

원칙(규칙서 §5·§7):
 - check_point(점검항목)는 config/corpus/jsa_hazards.json 의 공종 checklist 를 **그대로** 사용(환각/전사오류 방지).
 - 기계 특화 항목은 Scribe RULE_KB 의 실재 hazard 라벨에서만 보강(코퍼스 근거).
 - events 는 RULE_KB 의 **유효 규칙 id** 만 사용(테스트 자극=입력).
 - scribe_output 은 실제 제품 경로 scribe.generate(mode=checklist) 로 생성 — 지어내지 않음.
 - 강사 정답(적정성/위험수준/법령/감소대책/rubric 점수/치명오류)은 **전부 빈칸** — AI가 채우지 않는다.

실행: /opt/anaconda3/bin/python3 datasets/goldens/T1/build_cases.py   (또는 시스템 python3)
결과: datasets/goldens/T1/cases/T1_case_NN_<slug>.json  (15건)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "vigent-core"
sys.path.insert(0, str(CORE))
import os
os.chdir(CORE)

from agents.copilot import CopilotAgent  # noqa: E402
from agents.scribe import ScribeAgent, RULE_KB  # noqa: E402

OUT = ROOT / "datasets" / "goldens" / "T1" / "cases"
OUT.mkdir(parents=True, exist_ok=True)

# 코퍼스 공종 checklist 로드(그라운딩 소스)
JSA = json.loads((ROOT / "config" / "corpus" / "jsa_hazards.json").read_text(encoding="utf-8"))
CORPUS = {g["id"]: g for g in JSA["공종"]}


def cp_corpus(corpus_id, idx):
    """코퍼스 공종 checklist 항목을 인덱스로 그대로 가져온다."""
    return CORPUS[corpus_id]["checklist"][idx]


def cp_rulekb(rule):
    """RULE_KB 의 실재 hazard 라벨을 점검항목으로(기계 특화 보강용)."""
    return RULE_KB[rule]["hazard"]


def ev(rule, high=0, mid=0, low=0):
    lv = {}
    if high:
        lv["high"] = high
    if mid:
        lv["mid"] = mid
    if low:
        lv["low"] = low
    return {"rule": rule, "count": high + mid + low, "levels": lv}


# ── 15케이스 정의 ─────────────────────────────────────────────
# pool: (check_point, scribe_rule|None). rule 있으면 event 와 매칭 시 제품이 부적정(X)으로 판정.
# events: 비전 감지 자극(RULE_KB 유효 id). 절차·계측 위주 공종은 events 적게(=수동확인 위주).
CASES = [
    # ===== 건설 5 =====
    {"n": 1, "domain": "건설", "slug": "system_scaffold", "corpus": "high_place",
     "scenario": "시스템비계 설치·해체 작업. 외부 마감공사용 5단 시스템비계를 조립/해체하며 작업발판·안전난간 설치 상태와 안전대 체결이 관건.",
     "site": "신축 오피스 외벽 A동", "process": "시스템비계 설치·해체(높이 12m)",
     "pool": [(cp_corpus("high_place", 1), "height_fall_risk"),
              (cp_corpus("high_place", 0), "ppe_missing"),
              (cp_corpus("high_place", 3), "falling_object"),
              (cp_corpus("high_place", 4), None),
              (cp_corpus("high_place", 5), None)],
     "events": [ev("height_fall_risk", high=2, mid=1), ev("ppe_missing", mid=2), ev("falling_object", high=1)]},

    {"n": 2, "domain": "건설", "slug": "formwork_shoring", "corpus": "high_place",
     "scenario": "거푸집·동바리 조립 및 콘크리트 타설 준비. 동바리 좌굴·거푸집 붕괴 위험과 단부 추락이 혼재.",
     "site": "지하주차장 슬래브 구간", "process": "거푸집·동바리 조립(층고 4.2m)",
     "pool": [(cp_corpus("high_place", 1), "height_fall_risk"),
              (cp_corpus("high_place", 0), "ppe_missing"),
              (cp_corpus("high_place", 3), None),
              (cp_corpus("general", 1), None)],
     "events": [ev("height_fall_risk", high=1, mid=1), ev("ppe_missing", mid=1)]},

    {"n": 3, "domain": "건설", "slug": "excavation_shoring", "corpus": "excavation",
     "scenario": "굴착 및 흙막이 지보공 작업. 깊이 3m 터파기, 백호 병행. 굴착면 붕괴·매몰과 중장비 협착이 핵심.",
     "site": "상가 신축 부지 터파기", "process": "굴착·흙막이 지보공(깊이 3m)",
     "pool": [(cp_corpus("excavation", 2), "proximity_hazard"),
              (cp_corpus("excavation", 3), "height_fall_risk"),
              (cp_corpus("excavation", 5), "ppe_missing"),
              (cp_corpus("excavation", 0), None),
              (cp_corpus("excavation", 1), None),
              (cp_corpus("excavation", 4), None)],
     "events": [ev("proximity_hazard", high=2, mid=1), ev("height_fall_risk", high=1), ev("ppe_missing", mid=2)]},

    {"n": 4, "domain": "건설", "slug": "steel_erection", "corpus": "heavy_lifting",
     "scenario": "철골 세우기(부재 인양·볼트 체결). 크레인 양중 부재를 고소에서 결합. 중량물 낙하·협착과 고소 추락 복합.",
     "site": "물류창고 철골동", "process": "철골 세우기(H형강 볼트체결, 높이 9m)",
     "pool": [(cp_corpus("heavy_lifting", 2), "proximity_hazard"),
              (cp_corpus("heavy_lifting", 0), "falling_object"),
              (cp_corpus("heavy_lifting", 5), "ppe_missing"),
              (cp_corpus("high_place", 1), "height_fall_risk"),
              (cp_corpus("heavy_lifting", 1), None),
              (cp_corpus("heavy_lifting", 4), None)],
     "events": [ev("proximity_hazard", high=2), ev("falling_object", high=2, mid=1),
                ev("ppe_missing", mid=2), ev("height_fall_risk", high=1)]},

    {"n": 5, "domain": "건설", "slug": "mewp_ladder", "corpus": "high_place",
     "scenario": "고소작업대(MEWP)·이동식 사다리 병행 작업. 천장 배관 설치. 작업대 전도·과상승과 사다리 추락 위험.",
     "site": "공장 신축동 천장", "process": "고소작업대(MEWP) 배관작업(높이 6m)",
     "pool": [(cp_corpus("high_place", 2), None),
              (cp_corpus("high_place", 0), "ppe_missing"),
              (cp_corpus("high_place", 1), "height_fall_risk"),
              (cp_corpus("high_place", 5), None)],
     "events": [ev("ppe_missing", mid=1), ev("height_fall_risk", high=1, mid=1)]},

    # ===== 제조 5 =====
    {"n": 6, "domain": "제조", "slug": "conveyor_maint", "corpus": "general",
     "scenario": "가동 컨베이어 정비(청소·롤러 교체). 정지·잠금(LOTO) 없이 접근 시 롤러 끼임. 예기치 않은 기동 위험.",
     "site": "선별장 컨베이어 라인", "process": "컨베이어 정비(롤러·벨트)",
     "pool": [(cp_rulekb("machine_entanglement"), "machine_entanglement"),
              (cp_rulekb("guard_bypass"), "guard_bypass"),
              (cp_corpus("general", 3), "ppe_missing"),
              (cp_corpus("general", 0), None),
              (cp_corpus("general", 1), None)],
     "events": [ev("machine_entanglement", high=2), ev("guard_bypass", high=1), ev("ppe_missing", mid=1)]},

    {"n": 7, "domain": "제조", "slug": "arc_welding", "corpus": "hot_work",
     "scenario": "구조물 아크용접(화기작업). 인화물 인근에서 용접·용단. 불티 비산 화재·폭발, 흄 흡입, 감전.",
     "site": "제관공장 용접부스", "process": "아크용접·용단(SS400 구조물)",
     "pool": [(cp_corpus("hot_work", 0), "fire_smoke"),
              (cp_corpus("hot_work", 5), "ppe_missing"),
              (cp_corpus("hot_work", 1), None),
              (cp_corpus("hot_work", 2), None),
              (cp_corpus("hot_work", 3), None)],
     "events": [ev("fire_smoke", high=1, mid=1), ev("ppe_missing", mid=2)]},

    {"n": 8, "domain": "제조", "slug": "robot_cell", "corpus": "general",
     "scenario": "산업용 로봇셀 정비(용접로봇 티칭·청소). 방책 내 진입 시 로봇 충돌·끼임. 안전플러그·인터록 해제 위험.",
     "site": "차체라인 로봇셀 3호기", "process": "산업용 로봇셀 정비·티칭",
     "pool": [(cp_rulekb("machine_entanglement"), "machine_entanglement"),
              (cp_rulekb("zone_intrusion"), "zone_intrusion"),
              (cp_corpus("general", 3), "ppe_missing"),
              (cp_corpus("general", 1), None)],
     "events": [ev("machine_entanglement", high=1), ev("zone_intrusion", high=1, mid=1), ev("ppe_missing", mid=1)]},

    {"n": 9, "domain": "제조", "slug": "forklift_yard", "corpus": "heavy_lifting",
     "scenario": "지게차 하역·구내운반. 보행자 통로와 교차. 지게차 충돌·협착, 화물 전도.",
     "site": "완제품 창고 하역장", "process": "지게차 하역·구내운반(2톤)",
     "pool": [(cp_corpus("heavy_lifting", 2), "proximity_hazard"),
              (cp_rulekb("zone_intrusion"), "zone_intrusion"),
              (cp_corpus("heavy_lifting", 5), "ppe_missing"),
              (cp_corpus("heavy_lifting", 4), None)],
     "events": [ev("proximity_hazard", high=2, mid=1), ev("zone_intrusion", high=1), ev("ppe_missing", mid=1)]},

    {"n": 10, "domain": "제조", "slug": "injection_molding", "corpus": "general",
     "scenario": "사출성형기 작업(형체부 청소·이물 제거). 형체부 끼임, 고온 노즐 화상. 안전문 무효화 위험.",
     "site": "성형공장 사출기 라인", "process": "사출성형기 작업·형체부 청소",
     "pool": [(cp_rulekb("machine_entanglement"), "machine_entanglement"),
              (cp_rulekb("guard_bypass"), "guard_bypass"),
              (cp_corpus("general", 3), "ppe_missing"),
              (cp_corpus("general", 0), None)],
     "events": [ev("machine_entanglement", high=2), ev("guard_bypass", high=1), ev("ppe_missing", mid=1)]},

    # ===== 화학 5 =====
    {"n": 11, "domain": "화학", "slug": "solvent_painting", "corpus": "hot_work",
     "scenario": "유기용제 도장(스프레이). 밀폐 도장부스에서 인화성 용제 분무. 화재·폭발, 유기용제 급성중독.",
     "site": "도장공장 부스 2호", "process": "유기용제 스프레이 도장",
     "pool": [(cp_corpus("hot_work", 0), "fire_smoke"),
              (cp_rulekb("gas_alarm"), "gas_alarm"),
              (cp_corpus("hot_work", 5), "ppe_missing"),
              (cp_corpus("hot_work", 1), None)],
     "events": [ev("fire_smoke", high=1), ev("gas_alarm", high=1, mid=1), ev("ppe_missing", mid=1)]},

    {"n": 12, "domain": "화학", "slug": "loto_switchgear", "corpus": "electrical",
     "scenario": "정전작업(LOTO) 배전반 정비. 저압 배전반 차단·검전 후 정비. 무단투입 감전, 아크플래시.",
     "site": "공장 전기실 배전반", "process": "정전작업(LOTO) 배전반 정비",
     "pool": [(cp_corpus("electrical", 0), "electrical_hazard"),
              (cp_corpus("electrical", 2), "ppe_missing"),
              (cp_corpus("electrical", 1), None),
              (cp_corpus("electrical", 3), None),
              (cp_corpus("electrical", 4), None)],
     "events": [ev("electrical_hazard", high=1), ev("ppe_missing", mid=1)]},

    {"n": 13, "domain": "화학", "slug": "tank_cleaning", "corpus": "confined_space",
     "scenario": "위험물 저장탱크 내부 청소(밀폐공간). 잔류 유증기·산소결핍. 질식·중독, 정전기 화재.",
     "site": "위험물 탱크야드 T-3", "process": "저장탱크 내부 청소(밀폐공간 출입)",
     "pool": [(cp_corpus("confined_space", 0), "gas_alarm"),
              (cp_corpus("confined_space", 3), "ppe_missing"),
              (cp_corpus("confined_space", 1), None),
              (cp_corpus("confined_space", 2), None),
              (cp_corpus("confined_space", 4), None),
              (cp_corpus("confined_space", 5), None)],
     "events": [ev("gas_alarm", high=1), ev("ppe_missing", mid=1)]},

    {"n": 14, "domain": "화학", "slug": "skylight_roof", "corpus": "high_place",
     "scenario": "지붕 채광창 보수. 노후 채광창(FRP) 위 이동 중 파손 추락 위험.",
     "site": "공장동 지붕(경사 슬레이트)", "process": "지붕 채광창 보수(높이 8m)",
     "pool": [(cp_corpus("high_place", 1), "height_fall_risk"),
              (cp_corpus("high_place", 0), "ppe_missing"),
              (cp_corpus("high_place", 3), None),
              (cp_corpus("high_place", 5), None)],
     "events": [ev("height_fall_risk", high=2), ev("ppe_missing", mid=1)]},

    {"n": 15, "domain": "화학", "slug": "dust_work", "corpus": "general",
     "scenario": "국소배기 미비 분진작업(연삭·포장). 분진 흡입 진폐, 분진운 폭발.",
     "site": "분체공장 포장라인", "process": "분진작업(연삭·포장, 국소배기 미비)",
     "pool": [(cp_rulekb("gas_alarm"), "gas_alarm"),
              (cp_corpus("general", 3), "ppe_missing"),
              (cp_rulekb("fire_smoke"), "fire_smoke"),
              (cp_corpus("general", 0), None)],
     "events": [ev("gas_alarm", high=1, mid=1), ev("ppe_missing", mid=1), ev("fire_smoke", mid=1)]},
]

RUBRIC_BLANK = {
    "_주석": "확정 배점(30/25/25/10/10). 강사가 점수(0~배점) 부여.",
    "위험요인_식별_완전성": {"배점": 30, "점수": None, "코멘트": ""},
    "위험성_추정_적절성": {"배점": 25, "점수": None, "코멘트": ""},
    "감소대책_실효성_구체성": {"배점": 25, "점수": None, "코멘트": ""},
    "법적근거_형식_정확성": {"배점": 10, "점수": None, "코멘트": ""},
    "우선순위_잔류위험_관리": {"배점": 10, "점수": None, "코멘트": ""},
    "총점": None, "합격선": 80,
}
CRIT_BLANK = {
    "_주석": "하나라도 true면 rubric 점수와 무관하게 자동 불합격. 강사 판정.",
    "C1_중대재해_핵심위험_누락": None,
    "C2_실재하지않는_설비공정물질_언급": None,
    "C3_법령_오인용_또는_없는조문_인용": None,
    "C4_위험성등급_2단계이상_과소평가": None,
}


def build():
    scribe = ScribeAgent(None)
    scribe.copilot = CopilotAgent(None)
    made = []
    for c in CASES:
        pool = [{"check_point": cp, "rule": r} for cp, r in c["pool"]]
        res = scribe.generate(c["events"], site=c["site"], process=c["process"],
                              save=False, mode="checklist", item_pool=pool)
        assessment = res["assessment"]
        cid = f"T1_case_{c['n']:02d}_{c['slug']}"
        # 강사 정답란(빈칸) — pool 순서대로 items
        items = [{"check_point": cp, "적정성": "", "위험수준": "", "scribe_rule": r,
                  "vision_blind": False, "법령": [],
                  "감소대책": {"제거대체": [], "공학적": [], "관리적": [], "보호구": []}}
                 for cp, r in c["pool"]]
        obj = {
            "id": cid, "domain": c["domain"], "method": "checklist",
            "corpus_ref": c["corpus"],
            "scenario": c["scenario"], "site": c["site"], "process": c["process"],
            "holdout": True, "used_in_training_or_fewshot": False,
            "verified_by": "", "verified_date": "",
            "legal_basis": "산업안전보건법 제36조 및 고시 제2024-76호 제7조(체크리스트법)",
            "note_phrasing": "점검항목 요건 긍정형(O=충족/적정, X=미충족/부적정, − = 해당없음). 정답은 강사 판정 원본.",
            "input": {"events": c["events"],
                      "check_points": [cp for cp, _ in c["pool"]]},
            "scribe_output": assessment,
            "강사_정답": {"items": items, "rubric": json.loads(json.dumps(RUBRIC_BLANK)),
                       "critical_errors": json.loads(json.dumps(CRIT_BLANK)),
                       "verdict": {"pass": None}},
        }
        (OUT / f"{cid}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        s = assessment["summary"]
        made.append((cid, c["domain"], s["총항목"], s["부적정_X"], s["수동확인"], s["상_높음"]))
    print(f"생성 완료: {len(made)}건 → {OUT.relative_to(ROOT)}")
    print(f"{'id':34} {'도메인':6} {'총항목':>4} {'부적정X':>5} {'수동확인':>5} {'상':>3}")
    for cid, dom, tot, x, man, high in made:
        print(f"{cid:34} {dom:6} {tot:>4} {x:>5} {man:>5} {high:>3}")


if __name__ == "__main__":
    build()
