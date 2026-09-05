import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from tracker import iou


class DetectionEvaluator:
    def __init__(self, iou_threshold: float = 0.5):
        self.iou_threshold = iou_threshold

    def evaluate(self, ground_truth: List[Dict[str, Any]], predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        tp = 0
        fp = 0
        fn = 0

        for gt, pred in zip(ground_truth, predictions):
            gt_boxes = gt.get('boxes', [])
            pred_boxes = pred.get('boxes', [])
            matched = set()
            for pbox in pred_boxes:
                best_iou = 0.0
                best_idx = -1
                for i, gbox in enumerate(gt_boxes):
                    if i in matched:
                        continue
                    score = iou(pbox, gbox)
                    if score > best_iou:
                        best_iou = score
                        best_idx = i
                if best_iou >= self.iou_threshold:
                    tp += 1
                    matched.add(best_idx)
                else:
                    fp += 1
            fn += len(gt_boxes) - len(matched)

        precision = tp / (tp + fp) if tp + fp > 0 else 0.0
        recall = tp / (tp + fn) if tp + fn > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
        return {
            'true_positive': tp,
            'false_positive': fp,
            'false_negative': fn,
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
        }


def load_json(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    parser = argparse.ArgumentParser(description='Evaluate detection predictions against ground truth.')
    parser.add_argument('--gt', type=str, required=True, help='Ground truth JSON file')
    parser.add_argument('--pred', type=str, required=True, help='Prediction JSON file')
    parser.add_argument('--iou', type=float, default=0.5, help='IoU threshold')
    args = parser.parse_args()

    gt_data = load_json(Path(args.gt))
    pred_data = load_json(Path(args.pred))
    evaluator = DetectionEvaluator(iou_threshold=args.iou)
    results = evaluator.evaluate(gt_data, pred_data)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
