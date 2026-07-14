"""
train_model.py — Train and validate the Isolation Forest model.

Reads surprise vectors from the `synthetic_surprise_vectors` PostgreSQL
table via a simple SELECT query, builds a numpy matrix, trains
sklearn IsolationForest, and validates detection performance.

There are no .npy files anywhere in the pipeline.

Output:
  - model/isolation_forest.pkl

Usage:
    python scripts/train_model.py
"""

import os
import sys
from pathlib import Path

import numpy as np
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)

# Add parent directory so we can import scoring-engine modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring-engine"))

from app.weights import DIMENSION_NAMES, NUM_DIMENSIONS
from db_config import get_connection


def train_model(model_output: str = "model/isolation_forest.pkl"):
    """
    Train the Isolation Forest from synthetic_surprise_vectors.

    Hyperparameters (S9):
      - n_estimators=200
      - contamination=0.10
      - random_state=42
    """
    print("=" * 70)
    print("Isolation Forest Training & Validation  (<- PostgreSQL)")
    print("=" * 70)

    # 1. Load data from PostgreSQL
    print("  Reading surprise vectors from synthetic_surprise_vectors...")
    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT surprise_vector, is_anomaly, anomaly_types "
            "FROM synthetic_surprise_vectors "
            "ORDER BY id"
        )
        rows = cur.fetchall()
    conn.close()

    n = len(rows)
    print(f"  -> {n} rows fetched")

    # 2. Build numpy arrays from the query result
    vectors = np.zeros((n, NUM_DIMENSIONS), dtype=np.float64)
    labels = np.zeros(n, dtype=np.int32)
    anomaly_types_list = []

    for i, (sv, is_anom, atypes) in enumerate(rows):
        vectors[i] = sv
        labels[i] = 1 if is_anom else 0
        anomaly_types_list.append(atypes or [])

    print(f"  -> Vectors shape: {vectors.shape}")
    print(f"  -> Labels: {labels.sum()} anomalies / {n} total "
          f"({labels.mean()*100:.1f}%)")

    # 3. Train Isolation Forest
    print("\n  Training IsolationForest...")
    print("    n_estimators=200, contamination=0.10, random_state=42")

    model = IsolationForest(
        n_estimators=200,
        contamination=0.10,
        random_state=42,
        n_jobs=-1,
        verbose=0,
    )
    model.fit(vectors)
    print("  -> Training complete")

    # 4. Get predictions
    predictions = model.predict(vectors)
    scores = model.decision_function(vectors)
    pred_binary = (predictions == -1).astype(int)

    # 5. Overall metrics
    print("\n" + "-" * 50)
    print("  Overall Performance")
    print("-" * 50)
    print(f"  Precision: {precision_score(labels, pred_binary):.4f}")
    print(f"  Recall:    {recall_score(labels, pred_binary):.4f}")
    print(f"  F1 Score:  {f1_score(labels, pred_binary):.4f}")

    tn, fp, fn, tp = confusion_matrix(labels, pred_binary).ravel()
    print(f"\n  Confusion Matrix:")
    print(f"    True Positives:  {tp:>6}  "
          "(anomalies correctly detected)")
    print(f"    True Negatives:  {tn:>6}  "
          "(normals correctly passed)")
    print(f"    False Positives: {fp:>6}  "
          "(normals flagged as anomaly)")
    print(f"    False Negatives: {fn:>6}  "
          "(anomalies missed)")

    # 6. Per-anomaly-type recall
    if anomaly_types_list:
        print("\n" + "-" * 50)
        print("  Per-Anomaly-Type Recall")
        print("-" * 50)
        print(f"  {'Type':<25} {'Count':>6} {'Detected':>8} "
              f"{'Recall':>8}")
        print(f"  {'-'*49}")

        type_stats = {}
        for i, atypes in enumerate(anomaly_types_list):
            if not atypes:
                continue
            for atype in atypes:
                if atype not in type_stats:
                    type_stats[atype] = {"total": 0, "detected": 0}
                type_stats[atype]["total"] += 1
                if pred_binary[i] == 1:
                    type_stats[atype]["detected"] += 1

        for atype in sorted(type_stats.keys()):
            stats = type_stats[atype]
            recall = stats["detected"] / max(stats["total"], 1)
            marker = "+" if recall >= 0.80 else "!"
            print(f"  {marker} {atype:<23} {stats['total']:>6} "
                  f"{stats['detected']:>8} {recall:>8.1%}")

        if "multi_attribute" in type_stats:
            g_recall = (type_stats["multi_attribute"]["detected"]
                        / max(type_stats["multi_attribute"]["total"], 1))
            if g_recall >= 0.80:
                print(f"\n  + Type G (multi_attribute) recall target "
                      f"met: {g_recall:.1%} >= 80%")
            else:
                print(f"\n  ! Type G recall below target: "
                      f"{g_recall:.1%} < 80%")

    # 7. Score distribution
    print("\n" + "-" * 50)
    print("  IF Score Distribution")
    print("-" * 50)
    normal_scores = scores[labels == 0]
    anomaly_scores = scores[labels == 1]
    print(f"  Normals:   mean={normal_scores.mean():.4f}, "
          f"std={normal_scores.std():.4f}, "
          f"min={normal_scores.min():.4f}, "
          f"max={normal_scores.max():.4f}")
    print(f"  Anomalies: mean={anomaly_scores.mean():.4f}, "
          f"std={anomaly_scores.std():.4f}, "
          f"min={anomaly_scores.min():.4f}, "
          f"max={anomaly_scores.max():.4f}")

    print(f"\n  Suggested tier thresholds (IF scores):")
    print(f"    HIGH threshold:   <= "
          f"{np.percentile(anomaly_scores, 25):.4f} "
          f"(25th percentile of anomaly scores)")
    print(f"    MEDIUM threshold: <= "
          f"{np.percentile(anomaly_scores, 50):.4f} "
          f"(50th percentile of anomaly scores)")

    # 8. Save model
    os.makedirs(os.path.dirname(model_output) or ".", exist_ok=True)
    joblib.dump(model, model_output)
    model_size_kb = os.path.getsize(model_output) / 1024
    print(f"\n  -> Model saved to {model_output} "
          f"({model_size_kb:.0f} KB)")

    # 9. Verify reload
    loaded_model = joblib.load(model_output)
    test_scores = loaded_model.decision_function(vectors[:10])
    assert np.allclose(scores[:10], test_scores), \
        "Model reload verification failed!"
    print("  -> Model reload verification passed")

    print("\n" + "=" * 70)
    print("Training complete!")
    print("=" * 70)

    return model


if __name__ == "__main__":
    train_model()
