"""
ml_filter.py
=============
طبقة Machine Learning بسيطة (كما طُلب: "بسيطة في البداية") تقف بين Rules Engine
وBacktester، ومهمتها:

1. تصنيف كل إشارة جديدة إلى: strong / medium / weak (بناءً على خصائص الإشارة نفسها)
2. تعلّم من تاريخ الصفقات السابقة (نتائج win/loss) عبر نموذج بسيط (Logistic Regression)
   لرفض الإشارات التي تشبه إشارات خاسرة سابقاً.

تصميم متعمّد للبساطة:
- لا تحتاج GPU ولا بيانات ضخمة لتعمل.
- نموذج قابل لإعادة التدريب بسهولة (retrain) كل ما تجمّع صفقات جديدة في قاعدة البيانات.
- لو مافي صفقات كافية للتدريب (أقل من MIN_TRADES_FOR_TRAINING)، يرجع لقاعدة بسيطة
  مبنية على درجة الثقة (confidence) القادمة من Rules Engine فقط (Fallback آمن).
"""
from dataclasses import dataclass
from typing import Optional, List
import os
import pickle

import numpy as np

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from app.rules_engine import Structure

MIN_TRADES_FOR_TRAINING = 50
MODEL_PATH = os.getenv("ML_MODEL_PATH", "data/ml_filter_model.pkl")

# ترتيب أنواع الهياكل المستخدم في الـone-hot encoding (يجب تثبيته بين التدريب والاستدلال)
SIGNAL_TYPES = ["BOS", "CHoCH", "OB", "SND", "SNR", "FVG", "LIQUIDITY_SWEEP", "PREMIUM_DISCOUNT"]
DIRECTIONS = ["bullish", "bearish"]


@dataclass
class MLFilterResult:
    label: str          # "strong" | "medium" | "weak"
    score: float        # 0..1
    accepted: bool       # هل تُقبل هذه الإشارة للتنفيذ


def _structure_to_features(structure: Structure) -> np.ndarray:
    """يحوّل Structure إلى متجه خصائص رقمي ثابت الطول لتدريب/استدلال النموذج."""
    type_one_hot = [1.0 if structure.type == t else 0.0 for t in SIGNAL_TYPES]
    direction_one_hot = [1.0 if structure.direction == d else 0.0 for d in DIRECTIONS]

    zone_width = 0.0
    if structure.zone_high is not None and structure.zone_low is not None:
        zone_width = abs(structure.zone_high - structure.zone_low)

    features = type_one_hot + direction_one_hot + [structure.confidence, zone_width]
    return np.array(features, dtype=float)


class MLFilter:
    """
    واجهة الاستخدام الأساسية:
        ml = MLFilter()
        ml.train_from_trades(trades)             # trades: قائمة dict فيها features + result
        result = ml.predict(structure)
        if result.accepted: ... نفّذ الصفقة
    """

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path
        self.model: Optional["LogisticRegression"] = None
        self.scaler: Optional["StandardScaler"] = None
        self._load_model_if_exists()

    def _load_model_if_exists(self):
        if SKLEARN_AVAILABLE and os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
                self.model = data["model"]
                self.scaler = data["scaler"]

    def is_trained(self) -> bool:
        return self.model is not None

    def train_from_structures_and_outcomes(self, structures: List[Structure], outcomes: List[int]):
        """
        structures: قائمة Structure (نفس عدد outcomes)
        outcomes: قائمة 0/1 (0 = خسارة، 1 = فوز) لكل إشارة بعد تنفيذها فعلياً في Backtester
        """
        if not SKLEARN_AVAILABLE:
            print("[ml_filter] scikit-learn غير مثبت، تخطّي التدريب (سيُستخدم fallback بسيط).")
            return

        if len(structures) < MIN_TRADES_FOR_TRAINING:
            print(f"[ml_filter] عدد الصفقات ({len(structures)}) أقل من الحد الأدنى للتدريب "
                  f"({MIN_TRADES_FOR_TRAINING}). سيُستخدم fallback مبني على الثقة فقط.")
            return

        X = np.array([_structure_to_features(s) for s in structures])
        y = np.array(outcomes)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = LogisticRegression(max_iter=500, class_weight="balanced")
        model.fit(X_scaled, y)

        self.model = model
        self.scaler = scaler

        os.makedirs(os.path.dirname(self.model_path) or ".", exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump({"model": model, "scaler": scaler}, f)

        print(f"[ml_filter] تم تدريب النموذج على {len(structures)} إشارة. "
              f"دقة تقريبية (train accuracy): {model.score(X_scaled, y):.2f}")

    def predict(self, structure: Structure) -> MLFilterResult:
        """يرجع تقييم ML للإشارة. لو النموذج غير مدرَّب، يستخدم fallback مبني على confidence فقط."""
        if self.is_trained():
            features = _structure_to_features(structure).reshape(1, -1)
            features_scaled = self.scaler.transform(features)
            proba = self.model.predict_proba(features_scaled)[0][1]  # احتمال الفوز (class=1)
        else:
            # Fallback آمن: نعتمد فقط على ثقة Rules Engine نفسها
            proba = structure.confidence

        if proba >= 0.65:
            label = "strong"
        elif proba >= 0.45:
            label = "medium"
        else:
            label = "weak"

        accepted = label in ("strong", "medium")
        return MLFilterResult(label=label, score=round(float(proba), 3), accepted=accepted)


def make_backtester_filter(ml: MLFilter, min_label: str = "medium"):
    """
    يبني دالة filter متوافقة مع CandleByCandleBacktester.set_signal_filter():
    backtester.set_signal_filter(make_backtester_filter(ml))
    """
    rank = {"weak": 0, "medium": 1, "strong": 2}
    min_rank = rank.get(min_label, 1)

    def _filter(structure: Structure, context: dict) -> bool:
        result = ml.predict(structure)
        return rank.get(result.label, 0) >= min_rank

    return _filter
