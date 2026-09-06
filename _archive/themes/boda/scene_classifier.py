from pathlib import Path
from typing import Any

import numpy as np
from ultralytics import YOLO


class SceneClassifier:
    DEFAULT_MODEL = 'yolov8n-cls.pt'

    def __init__(self, model_path: str | None = None, device: str = 'cpu', imgsz: int = 640):
        self.model_path = Path(model_path) if model_path else Path(self.DEFAULT_MODEL)
        self.device = device
        self.imgsz = imgsz
        self.model = None
        self.class_names = {}
        self.loaded = False
        self.error: str | None = None

        if self.model_path.exists():
            try:
                self.model = YOLO(str(self.model_path))
                self.class_names = self.model.names if hasattr(self.model, 'names') else {}
                self.loaded = True
            except Exception as exc:
                self.error = str(exc)
        else:
            self.error = f'Scene model not found: {self.model_path}'

    def classify_scene(self, frame: Any) -> dict:
        if not self.loaded or self.model is None:
            return {'label': 'unknown', 'confidence': 0.0, 'error': self.error}

        try:
            results = self.model(frame, task='classify', imgsz=self.imgsz, device=self.device)
            if len(results) == 0:
                return {'label': 'unknown', 'confidence': 0.0, 'error': 'no results'}

            result = results[0]
            if hasattr(result, 'probs') and result.probs is not None:
                probs = result.probs.cpu().numpy()
                top_idx = int(np.argmax(probs))
                label = self.class_names.get(top_idx, str(top_idx))
                confidence = float(probs[top_idx])
                return {'label': label, 'confidence': confidence, 'error': None}

            if hasattr(result, 'scores') and result.scores is not None:
                scores = result.scores.cpu().numpy()
                top_idx = int(np.argmax(scores))
                label = self.class_names.get(top_idx, str(top_idx))
                confidence = float(scores[top_idx])
                return {'label': label, 'confidence': confidence, 'error': None}

            return {'label': 'unknown', 'confidence': 0.0, 'error': 'missing probability output'}
        except Exception as exc:
            return {'label': 'unknown', 'confidence': 0.0, 'error': str(exc)}
