"""enrollment.py — 얼굴 등록(갤러리) 저장소

한 사람당 1장 이상의 얼굴 이미지로 임베딩을 만들어 보관한다. 여러 장(각도·조명)을
넣을수록 인식률이 올라간다. 저장물:
  - gallery.json : 사람 메타(이름·동의·시각·만료) — 생체정보 자체는 아님
  - embeddings.npz: 임베딩 행렬(생체 템플릿) — 민감정보, 암호화/파일권한 보호

데이터 최소화: 기본은 임베딩만. 원본 얼굴 이미지는 config.STORE_RAW_FACE=1 일 때만.

스레드 안전: 파일 쓰기는 락으로 보호. 메모리 갤러리는 식별 때 재사용.
"""
from __future__ import annotations

import io
import json
import os
import threading
from dataclasses import asdict, dataclass, field

import numpy as np

from . import config, privacy
from .engine import get_engine
from .privacy import Consent


@dataclass
class Person:
    person_id: str
    name: str
    consent: Consent
    created_at: str = field(default_factory=privacy.now_iso)
    n_embeddings: int = 0


class EnrollmentStore:
    """갤러리(사람 + 임베딩 행렬)를 디스크에 보존하고 메모리에 캐시."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._persons: dict[str, Person] = {}
        self._emb: np.ndarray = np.zeros((0, 128), dtype=np.float32)  # (M,128)
        self._owner: list[str] = []                                   # 길이 M, 각 행의 person_id
        self._encrypted = False
        self._load()

    # ── 영속화 ────────────────────────────────────────────────
    def _load(self) -> None:
        if config.GALLERY_META.exists():
            meta = json.loads(config.GALLERY_META.read_text(encoding="utf-8"))
            for pid, p in meta.get("persons", {}).items():
                c = p["consent"]
                self._persons[pid] = Person(
                    person_id=pid, name=p["name"],
                    consent=Consent(**c),
                    created_at=p.get("created_at", privacy.now_iso()),
                    n_embeddings=p.get("n_embeddings", 0),
                )
            self._encrypted = meta.get("encrypted", False)
        if config.GALLERY_EMB.exists():
            raw = config.GALLERY_EMB.read_bytes()
            raw = privacy.decrypt_bytes(raw, self._encrypted)
            npz = np.load(io.BytesIO(raw), allow_pickle=True)
            self._emb = npz["emb"].astype(np.float32)
            self._owner = list(npz["owner"])

    def _save(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 임베딩(민감) → 직렬화 후 암호화/평문
        buf = io.BytesIO()
        np.savez(buf, emb=self._emb, owner=np.array(self._owner, dtype=object))
        data, encrypted = privacy.encrypt_bytes(buf.getvalue())
        self._encrypted = encrypted
        config.GALLERY_EMB.write_bytes(data)
        _chmod600(config.GALLERY_EMB)
        # 메타(비생체)
        meta = {
            "encrypted": encrypted,
            "persons": {
                pid: {
                    "name": p.name, "created_at": p.created_at,
                    "n_embeddings": p.n_embeddings, "consent": asdict(p.consent),
                    "expires_at": p.consent.expires_at(),
                }
                for pid, p in self._persons.items()
            },
        }
        config.GALLERY_META.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod600(config.GALLERY_META)

    # ── 등록/삭제 ─────────────────────────────────────────────
    def add_person(self, person_id: str, name: str, images: list[np.ndarray],
                   consent: Consent) -> Person:
        """이미지들(BGR)에서 얼굴 임베딩을 만들어 사람을 등록/추가.

        각 이미지에서 가장 큰 얼굴 1개를 사용. 얼굴이 없는 이미지는 건너뜀.
        """
        privacy.require_enabled()
        eng = get_engine()
        vecs: list[np.ndarray] = []
        for img in images:
            faces = [f for f in eng.detect(img) if eng.quality_ok(f)]
            if not faces:
                continue
            # 가장 큰 얼굴 선택(가장 가까운/주피사체)
            f = max(faces, key=lambda x: x.bbox[2] * x.bbox[3])
            vecs.append(eng.embed(img, f))
        if not vecs:
            raise ValueError("등록 이미지에서 얼굴을 찾지 못했습니다.")

        with self._lock:
            person = self._persons.get(person_id)
            if person is None:
                person = Person(person_id=person_id, name=name, consent=consent)
                self._persons[person_id] = person
            # 기존 개수 + 신규를 합치되 1인당 상한 적용(최근 것 우선)
            new = np.stack(vecs).astype(np.float32)
            self._emb = np.vstack([self._emb, new]) if self._emb.size else new
            self._owner.extend([person_id] * len(vecs))
            self._enforce_cap(person_id)
            person.n_embeddings = self._owner.count(person_id)
            self._save()
        privacy.audit("enroll", person_id=person_id, name=name,
                      added=len(vecs), total=person.n_embeddings,
                      purpose=consent.purpose, by=consent.consented_by)
        return person

    def _enforce_cap(self, person_id: str) -> None:
        """1인당 임베딩 상한 초과 시 오래된 것부터 제거."""
        idx = [i for i, o in enumerate(self._owner) if o == person_id]
        excess = len(idx) - config.MAX_EMB_PER_PERSON
        if excess > 0:
            drop = set(idx[:excess])
            keep = [i for i in range(len(self._owner)) if i not in drop]
            self._emb = self._emb[keep]
            self._owner = [self._owner[i] for i in keep]

    def delete_person(self, person_id: str) -> bool:
        """잊혀질 권리 — 사람의 메타+임베딩을 완전 삭제."""
        with self._lock:
            if person_id not in self._persons:
                return False
            keep = [i for i, o in enumerate(self._owner) if o != person_id]
            self._emb = self._emb[keep] if keep else np.zeros((0, 128), np.float32)
            self._owner = [self._owner[i] for i in keep]
            del self._persons[person_id]
            self._save()
        privacy.audit("delete", person_id=person_id)
        return True

    def purge_expired(self) -> list[str]:
        """보존기간 만료자 자동 삭제. 삭제된 person_id 목록 반환."""
        expired = [pid for pid, p in self._persons.items() if p.consent.is_expired()]
        for pid in expired:
            self.delete_person(pid)
            privacy.audit("purge_expired", person_id=pid)
        return expired

    # ── 조회 ──────────────────────────────────────────────────
    def list_persons(self) -> list[dict]:
        return [
            {"person_id": p.person_id, "name": p.name,
             "n_embeddings": p.n_embeddings, "created_at": p.created_at,
             "expires_at": p.consent.expires_at(),
             "expired": p.consent.is_expired()}
            for p in self._persons.values()
        ]

    def gallery_matrix(self) -> tuple[np.ndarray, list[str]]:
        """(임베딩 행렬 M×128, 각 행 owner person_id) — recognizer 가 사용."""
        return self._emb, self._owner

    def name_of(self, person_id: str) -> str:
        p = self._persons.get(person_id)
        return p.name if p else person_id


_STORE: EnrollmentStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> EnrollmentStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = EnrollmentStore()
    return _STORE


def _chmod600(path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
