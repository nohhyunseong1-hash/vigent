"""iris.py — 홍채 인식 요소 (NIR 하드웨어 플러그형 + 해밍거리 매칭)

홍채는 쌍둥이·노화에 강한 최고 정밀 생체지표지만, 실제 인식엔 **근적외선(NIR) 카메라 +
근접 협조 촬영**이 필요하다(일반 웹캠·갈색 홍채는 불가). 따라서 본 모듈은:
  - 하드웨어(촬영+코드추출)를 `IrisProvider` 로 추상화 → 장비가 꽂히면 바로 동작.
  - 기본은 `NullIrisProvider`(미연결) → 홍채 요소는 '판정불가'.
  - 매칭은 Daugman 방식: 홍채코드(비트) + 마스크 → **정규화 해밍거리** < 임계값이면 동일인.
  - `SimIrisProvider`: 파이프라인(등록·매칭·정책) 검증용 시뮬레이터. **실제 인식 아님**(명시).

법적: 홍채는 민감 생체정보 → **별도 옵트인(VIGENT_IRIS_ENABLED)**, 암호화 저장, 감사,
보존기간. 얼굴 옵트인과 독립.
"""
from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass

import numpy as np

from . import config, privacy

CODE_BITS = 2048          # 홍채코드 길이(데모 기준; 실제 Daugman은 2048비트 관례)


# ── 템플릿 ───────────────────────────────────────────────────
@dataclass
class IrisTemplate:
    code: np.ndarray      # (CODE_BITS,) uint8 0/1
    mask: np.ndarray      # (CODE_BITS,) uint8 — 유효(1)/가림·잡음(0)

    def hamming(self, other: "IrisTemplate") -> float:
        """정규화 해밍거리(0=동일, ~0.5=무관). 유효비트(두 마스크 교집합)만 비교."""
        m = (self.mask & other.mask).astype(bool)
        n = int(m.sum())
        if n == 0:
            return 1.0
        diff = (self.code[m] ^ other.code[m]).sum()
        return float(diff) / n


# ── 하드웨어 프로바이더 (NIR 카메라 + 코드 추출) ──────────────
class IrisProvider:
    """홍채 촬영·코드추출 장비 추상화. 실제 장비/ SDK가 이 인터페이스를 구현한다."""

    name = "base"

    def available(self) -> bool:
        return False

    def capture(self, capture_input) -> IrisTemplate | None:
        """장비/입력에서 홍채 템플릿을 추출. 실패 시 None(가림·미초점 등)."""
        raise NotImplementedError


class NullIrisProvider(IrisProvider):
    """기본값: 홍채 하드웨어 미연결."""
    name = "null"

    def available(self) -> bool:
        return False

    def capture(self, capture_input) -> IrisTemplate | None:
        return None


class SimIrisProvider(IrisProvider):
    """시뮬레이터(파이프라인 검증용). 실제 홍채 인식이 아님.

    capture_input = {"seed": <같은 눈이면 같은 시드>, "noise": <촬영 변동 0~1>}.
    같은 시드 → 거의 같은 코드(낮은 해밍), 다른 시드 → ~0.5. 등록·매칭·정책을 테스트.
    """
    name = "sim"

    def available(self) -> bool:
        return True

    def capture(self, capture_input) -> IrisTemplate | None:
        if not isinstance(capture_input, dict) or "seed" not in capture_input:
            return None
        seed = str(capture_input["seed"])
        noise = float(capture_input.get("noise", 0.03))
        h = hashlib.sha256(seed.encode()).digest()
        rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
        code = rng.integers(0, 2, CODE_BITS, dtype=np.uint8)
        # 촬영 변동: noise 비율만큼 비트 뒤집기(클래스 내 변동 모사)
        nrng = np.random.default_rng()
        flip = nrng.random(CODE_BITS) < noise
        code = code ^ flip.astype(np.uint8)
        mask = (nrng.random(CODE_BITS) > 0.05).astype(np.uint8)   # 5% 가림 모사
        return IrisTemplate(code=code, mask=mask)


_PROVIDER: IrisProvider | None = None


def get_provider() -> IrisProvider:
    """환경변수 VIGENT_IRIS_PROVIDER = null(기본) | sim 로 선택."""
    global _PROVIDER
    if _PROVIDER is None:
        kind = os.environ.get("VIGENT_IRIS_PROVIDER", "null").lower()
        _PROVIDER = SimIrisProvider() if kind == "sim" else NullIrisProvider()
    return _PROVIDER


def set_provider(p: IrisProvider) -> None:
    global _PROVIDER
    _PROVIDER = p


# ── 템플릿 저장소(암호화) ────────────────────────────────────
class IrisStore:
    PATH = config.DATA_DIR / "iris_templates.npz"

    def __init__(self):
        self._ids: list[str] = []
        self._codes: list[np.ndarray] = []
        self._masks: list[np.ndarray] = []
        self._enc = False
        if self.PATH.exists():
            raw = self.PATH.read_bytes()
            for candidate in (raw, None):
                try:
                    data = candidate if candidate is not None \
                        else privacy.decrypt_bytes(raw, True)   # 평문 실패 시 복호화 시도
                    npz = np.load(io.BytesIO(data), allow_pickle=True)
                    self._ids = list(npz["ids"]); self._codes = list(npz["codes"])
                    self._masks = list(npz["masks"])
                    self._enc = candidate is None
                    break
                except Exception:
                    continue

    def _save(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        np.savez(buf, ids=np.array(self._ids, dtype=object),
                 codes=np.array(self._codes), masks=np.array(self._masks))
        data, enc = privacy.encrypt_bytes(buf.getvalue())
        self._enc = enc
        self.PATH.write_bytes(data)
        try:
            os.chmod(self.PATH, 0o600)
        except OSError:
            pass

    def enroll(self, person_id: str, t: IrisTemplate):
        self._ids.append(person_id); self._codes.append(t.code); self._masks.append(t.mask)
        self._save()
        privacy.audit("iris_enroll", person_id=person_id)

    def match(self, t: IrisTemplate) -> tuple[str | None, float]:
        best_id, best_hd = None, 1.0
        for pid, c, m in zip(self._ids, self._codes, self._masks):
            hd = t.hamming(IrisTemplate(c, m))
            if hd < best_hd:
                best_hd, best_id = hd, pid
        if best_id is not None and best_hd <= config.IRIS_HAMMING_THRESHOLD:
            return best_id, best_hd
        return None, best_hd


# ── 고수준 인식 ──────────────────────────────────────────────
class IrisRecognizer:
    def __init__(self, provider: IrisProvider | None = None,
                 store: IrisStore | None = None):
        self.provider = provider or get_provider()
        self.store = store or IrisStore()

    def enroll(self, person_id: str, capture_input) -> bool:
        if not config.IRIS_ENABLED:
            raise privacy.FacialRecognitionDisabled("홍채 비활성(VIGENT_IRIS_ENABLED=1 필요)")
        t = self.provider.capture(capture_input)
        if t is None:
            return False
        self.store.enroll(person_id, t)
        return True

    def identify(self, capture_input) -> tuple[str | None, float, str]:
        """(person_id, hamming, reason). 미연결/가림이면 person_id=None."""
        if not config.IRIS_ENABLED:
            return None, 1.0, "홍채 비활성"
        if not self.provider.available():
            return None, 1.0, "홍채 하드웨어 미연결(NIR 필요)"
        t = self.provider.capture(capture_input)
        if t is None:
            return None, 1.0, "홍채 판정불가(가림/미초점)"
        pid, hd = self.store.match(t)
        if pid is None:
            return None, hd, "등록되지 않은 홍채"
        return pid, hd, "홍채 일치"
