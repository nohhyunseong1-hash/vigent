# 다음 세션 착수 프롬프트 (2026-09-06 감사 종료 시점 작성)

> 두 세션 모두 **새 대화에서 이 파일을 열고 해당 절을 그대로 붙여 넣어** 시작한다. 전제·명령은 2026-09-06 실측 기준이며,
> 착수 전 "전제 확인" 항목을 다시 재서 어긋나면 멈추고 보고한다(규칙 7·11). 공통 규칙: 파괴적 작업은 계획을 보여주고 승인 후,
> 비밀값은 채팅·문서에 쓰지 않는다, 커밋 직전 `git branch --show-current`.

---

## 세션 1 — git 이력 재작성(민감 미디어 제거)

### 착수 프롬프트(복사용)

```
docs/NEXT_SESSIONS.md 세션 1 을 수행한다. 목표: 저장소 이력에서 얼굴 식별 이미지·고객 설비 사진·사고 영상을 제거하고
원격(origin)까지 반영한다. 순서: 전제 확인 → 백업 번들 → git filter-repo(경로 기준) → 검증(이력 내 미디어 0건) →
force-push → 재클론 검증 → 문서 갱신. 각 단계 결과를 수치로 보고하고, force-push 직전에 멈춰 승인을 받는다.
```

### 대상(실측 2026-09-06)

- 이력 안 미디어 객체 **110개**(`.jpg/.jpeg/.png/.mp4/.avi/.mov`, `git rev-list --objects --all` 기준). 대표 커밋은
  `2a98fa9`(2026-07-12, 미디어 5) · `b9e8289`(2026-08-28, 미디어 93)이지만 **다른 커밋에도 흩어져 있으므로 커밋이 아니라 경로로 지운다.**
- 경로(상위 디렉터리별 개수): `runs/site01_eval/site1` 21 · `runs/forklift_duel/{coco,loco,compare,driver}` 24 · `runs/rfdetr/{accident,lowres,refset}` 20 ·
  `runs/tapo_test_eval/{tp1,tp2,tp3}` 24 · `benchmarks/results/webcam_coord` 5 · 나머지(`data/field_eval` 평가 jpg 등) — 착수 시
  아래 명령으로 전체 목록을 다시 뽑아 `audit/history_media_list_<날짜>.txt` 에 남긴다(경로만, 파일 내용 열지 않음).
- 작업트리에서는 이미 제거돼 `D:\vigent_private_data\`(`VIGENT_DATA_DIR`)에 있다(5단계 C5). 이 세션은 **이력만** 다룬다.

### 전제 확인(하나라도 어긋나면 중단)

1. **다른 클론·워크트리 없음**: `git worktree list` 가 `D:\vigent_original` 1개 · `D:\vigent_verify*` 삭제됨(2026-09-06 확인) ·
   협업자 클론 없음(대표 확인). 재작성 뒤 옛 이력을 가진 클론이 push 하면 미디어가 되살아난다.
2. **원격 상태**: `git ls-remote origin` = main(`bbe32a5`) · fix/review-bugs(`e1ba0ab`) · audit/cleanup-20260906(`d577267`) ·
   태그 audit-before-cleanup · v-audit-2026-09 · weights-v1 — 총 6개 ref. 재작성은 **모든 ref** 에 적용하고 전부 force-push 한다.
3. **백업은 원격이 아니라 로컬 번들**: 원격 백업 태그를 만들면 미디어가 원격에 남아 목적에 어긋난다.
   `D:\vigent_private_data\git_backup\vigent_pre_rewrite_<날짜>.bundle`(전 ref) + `git bundle verify` 로 확인.
4. `git filter-repo` 미설치(2026-09-06 실측 `git: 'filter-repo' is not a git command`) → `py -3.11 -m pip install git-filter-repo`(승인 필요).
5. `.git` 49MB, pack 47MB — 재작성 뒤 `git count-objects -vH` 로 감소를 잰다(예상치 쓰지 말 것).

### 절차·명령

```powershell
cd D:\vigent_original
git worktree list ; git status --short            # 깨끗해야 한다
git ls-remote origin | Measure-Object -Line       # 6
# 1) 백업 번들(전 ref)
New-Item -ItemType Directory -Force D:\vigent_private_data\git_backup | Out-Null
git bundle create D:\vigent_private_data\git_backup\vigent_pre_rewrite_$(Get-Date -Format yyyyMMdd).bundle --all
git bundle verify D:\vigent_private_data\git_backup\vigent_pre_rewrite_*.bundle
# 2) 대상 목록(경로만)
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' `
  | Select-String -Pattern '\.(jpg|jpeg|png|mp4|avi|mov)$' | ForEach-Object { ($_ -split ' ',4)[3] } | Sort-Object -Unique `
  | Out-File -Encoding utf8 audit\history_media_list_$(Get-Date -Format yyyyMMdd).txt
# 3) filter-repo (신규 클론에서 돌리는 것이 안전 — filter-repo 는 fresh clone 을 요구한다)
py -3.11 -m pip install git-filter-repo
git clone --mirror D:\vigent_original D:\vigent_rewrite.git ; cd D:\vigent_rewrite.git
git filter-repo --invert-paths --paths-from-file D:\vigent_original\audit\history_media_list_<날짜>.txt
#    (README 의 얼굴 이미지 9장 등 경로가 목록에 있는지 확인. 확장자 대문자 .JPG 도 검색)
# 4) 검증: 이력 내 미디어 0건
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' `
  | Select-String -Pattern '\.(jpg|jpeg|png|mp4|avi|mov)$' | Measure-Object -Line     # 0 이어야 한다
git count-objects -vH
# 5) force-push (여기서 멈춰 승인) — 미러에서 origin 으로
git remote add origin https://github.com/nohhyunseong1-hash/vigent.git
git push --force --mirror origin
# 6) 재클론 검증
git clone https://github.com/nohhyunseong1-hash/vigent.git D:\vigent_original_new
cd D:\vigent_original_new ; git ls-remote origin | Measure-Object -Line ; (위 4 의 검증 명령) → 0
#    이어서 D:\vigent_original 을 D:\vigent_original_old 로 옮기고 새 클론을 D:\vigent_original 로 — .venv·weights·.env·data 는 복사
```

### 검증·마무리 기준

- 재클론에서 이력 내 미디어 **0건**, 6개 ref 모두 재작성본, `git log --oneline | Measure-Object -Line` 이 재작성 전과 같음(커밋 수 보존).
- GitHub 는 옛 객체를 캐시(PR·포크·"Recently pushed")로 남길 수 있다 → 저장소 Settings 확인 후 필요하면 GitHub Support 에 캐시 제거 요청(문서화).
- `docs/public_release_checklist.md` 의 ⛔차단 "이력 재작성" 항목을 실측 수치와 함께 해제, `CLAUDE.md` 규칙 10 의 "이력에 남아 있다" 문구를 정정.
- 이 세션 뒤 협업자는 전원 **재클론**(옛 클론에서 pull/push 금지).

---

## 세션 2 — Windows 로컬 VLM 대체 구현(RTX 5070 Ti / CUDA 13)

### 착수 프롬프트(복사용)

```
docs/NEXT_SESSIONS.md 세션 2 를 수행한다. 목표: mlx 전용(Apple)인 VLM 2차 확정 경로를 Windows/CUDA 로 동작하게 하되,
클라우드 전송 없이(OpenAI 라우팅은 키가 있을 때만·기본 off) 오프라인에서 돈다. 먼저 후보 2개를 같은 프레임 20장으로
실측(지연·VRAM·한국어 JSON 파싱 성공률)해 표로 보고하고 승인 후 배선한다. 규칙 6: 실패·미설치 시 기존 폴백(uncertain → 억제 없음) 유지.
```

### 현재 코드(실측 2026-09-06)

- `vigent-core/ml/vlm_risk_summary.py:154` — `from mlx_vlm import generate, load`(지연 로딩 `_ensure_loaded`), 기본 모델
  `_DEFAULT_MODEL = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"`(:19), `_ask_openai`(:165, `OPENAI_API_KEY` 있을 때만 클라우드 라우팅).
  Windows 에서는 `mlx_vlm` import 자체가 실패 → `available=False` 폴백(동작은 하지만 2차 확정이 **항상 불확실**).
- `vigent-core/vlm_confirm.py` — 규칙별 확정 프롬프트(`CONFIRM_PROMPTS`), `classify()`(confirmed/rejected/uncertain), `_fallback()`.
- 배선(M3-7): **브라우저 `/zone/intrusion` 의 opt-in `payload.vlm_confirm` 에만** — `routers/zone.py:107-111`(워커 소유 카메라면 생략, M8-1).
  **워커 경로(worker.py)에는 미배선** → 이 세션에서 워커 2차 확정(이벤트 확정 순간 1회 호출)을 설계·배선한다.
- mlx 참조 파일: `app_state.py`·`device.py`·`rfdetr_service.py`·`vlm_confirm.py`·`ml/vlm_risk_summary.py`·`routers/detect.py`,
  `requirements-agents.txt`·`requirements-optional.txt`(mlx 는 optional).
- 하드웨어: RTX 5070 Ti 16,303MiB · 드라이버 610.74 · 정본 3.11 의 torch 2.12.0+cu130(개발 PC). 서비스용 `.venv` 는 CPU torch — VLM 은 CUDA venv 에서.

### 후보

| 후보 | 방식 | 확인할 것 |
|---|---|---|
| A. transformers + Qwen2.5-VL-7B-Instruct 4bit(bitsandbytes 또는 AWQ) | 프로세스 내 로드, 이벤트 시 1회 추론 | 7B 4bit VRAM(예상치 쓰지 말고 실측) · 첫 로드 시간 · 검출기(RF-DETR 3슬롯)와 VRAM 동거 가능 여부 · Windows bitsandbytes 휠 |
| B. vLLM 서버(로컬 HTTP) + 같은 모델 | 별도 프로세스, OpenAI 호환 API → `_ask_openai` 경로 재사용(base_url 만 바꿈) | Windows 네이티브 지원 여부(WSL2 필요할 수 있음 — 현장 배포성) · 상주 VRAM |
| (대조) 3B 4bit | 현재 mlx 기본과 같은 크기 | 7B 가 안 들어가면 대안. 한국어 범주형 판정 품질(vlm_confirm.py:37 주석의 3B 한계) |

### 성공 기준(측정해서 채운다)

- **2차 확정 지연**: 이벤트 확정 시점 → verdict 반환 p50/p95(프레임 20장, 1024px 축소 `_safe_image` 기준). 목표는 대표가 정한다 — 기준선으로 현재 폴백(0s, 항상 uncertain)과 OpenAI 라우팅(있으면) 함께 표기.
- **VRAM**: 검출기 예열 후 VLM 로드 전/후 `nvidia-smi` 사용량, 여유 ≥ 검출 피크(카메라 5대 실측치는 benchmarks/capacity_report).
- **오프라인 동작**: 네트워크 차단(어댑터 비활성) 상태에서 모델 로드·추론 성공, `Downloading` 로그 0 — 모델 캐시 경로를 `TORCH_HOME`/`HF_HOME` 으로 `vigent-core/weights` 계열에 고정하고 `weights_manifest.json` 에 조달 항목 추가(SITE_CHECKLIST N-5).
- **품질**: 같은 20장에 대해 confirmed/rejected/uncertain 분포와 사람 판정 대비 일치 수(k/n 관측값만, 신뢰구간 금지).
- **저하 없음**: mlx·CUDA 어느 쪽도 없을 때 기존 `_fallback` 그대로, 테스트로 고정. `/health` 에 `vlm.backend`(mlx/cuda/none) 노출.

### 산출물

- `ml/vlm_backend.py`(backend 추상: mlx / transformers-cuda / openai) + `vlm_risk_summary.py`·`vlm_confirm.py` 가 backend 를 통해 호출.
- 워커 2차 확정 배선(설계 → 승인 → 구현), 브라우저 옵션은 그대로.
- `benchmarks/vlm_backend_ab.md`(실측 표) · DEPLOYMENT §3 에 CUDA VLM 설치 절 · requirements-optional 갱신.
