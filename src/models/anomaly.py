# Unusual-activity check: an IsolationForest that marks a transaction as "unusual for you" when it differs
# from the user's OWN pattern in earlier months. It is a pattern check, not fraud detection: the simulated
# data has no labelled fraud. It is measured by injecting clearly marked artificial outliers into a copy
# of the test months. All data is simulated.
# Run: python -m src.models.anomaly   (trains on months 1-3, evaluates on 4-5, writes artifacts/anomaly/)

import functools  # Load the saved model once.
import json  # Saves the evaluation.
import pickle  # Saves the fitted model (loaded only from our own artifacts folder).

import numpy as np  # Number tools.
import pandas as pd  # Table tools.
import sklearn  # Version stamp in the saved file.
from sklearn.ensemble import IsolationForest  # The unusual-activity model.

from src import config as cfg  # Seed, months, flag rate, folders.
from src.features.build_features import load_data  # The simulated CSV files.

TYPES = list(cfg.LIVE_TYPES)  # The 7 transaction types (used for the per-type report).
# Per-transaction inputs, all relative to the user's own history. The type enters through "amount against
# your usual amount for THIS type" and "type never used before". A first version also had one-hot type
# columns; on the training months they flagged 54% of the rare add_money rows (a rare type isolates in one
# split), so "unusual" meant "rare type", not "unusual for you". They were removed after that first run,
# which had also shown the test-month results; this is disclosed in the metrics file.
FEATURES = ["log_amount_vs_usual", "new_type", "day_share", "log_share_of_balance"]
MODEL_PATH = cfg.ANOMALY_DIR / "isolation_forest.pkl"
METRICS_PATH = cfg.ANOMALY_DIR / "metrics.json"


def feature_matrix(rows):
    """Model inputs for transactions. rows needs: amount, type, day, usual_type, usual_all, opening_balance.

    usual_type / usual_all are the user's median amount for that type / for any type in EARLIER months
    (blank if never seen); opening_balance is the wallet balance at the start of that day.
    """
    usual = rows["usual_type"].fillna(rows["usual_all"])  # A type never used before: compare with all types.
    out = pd.DataFrame(index=rows.index)
    out["log_amount_vs_usual"] = np.log1p(rows["amount"]) - np.log1p(usual)
    out["new_type"] = rows["usual_type"].isna().astype(float)
    out["day_share"] = rows["day"] / cfg.DAYS_IN_MONTH
    out["log_share_of_balance"] = np.log1p(rows["amount"] / rows["opening_balance"].clip(lower=1))
    return out[FEATURES].astype(float)


def history_medians(tx_hist):
    """(median amount per user and type, median amount per user) over the given earlier transactions."""
    return (tx_hist.groupby(["user_id", "type"])["amount"].median().rename("usual_type"),
            tx_hist.groupby("user_id")["amount"].median().rename("usual_all"))


def opening_balances(bal):
    """Balance at the start of each user-day: the previous day's end-of-day balance (blank on the very first day)."""
    bal = bal.sort_values(["user_id", "month", "day"])
    return bal.assign(opening_balance=bal.groupby("user_id")["end_of_day_balance"].shift(1))[
        ["user_id", "month", "day", "opening_balance"]]


def transaction_rows(tx, bal, months):
    """Every transaction in the given months, with its history medians (earlier months only) and opening balance."""
    opening = opening_balances(bal)
    parts = []
    for m in months:
        by_type, overall = history_medians(tx[tx["month"] < m])  # Only months before m: no look-ahead.
        cur = tx[tx["month"] == m].join(by_type, on=["user_id", "type"]).join(overall, on="user_id")
        parts.append(cur.merge(opening, on=["user_id", "month", "day"], how="left"))
    rows = pd.concat(parts, ignore_index=True)
    return rows[rows["usual_all"].notna() & rows["opening_balance"].notna()].reset_index(drop=True)


def inject_outliers(rows, rng):
    """A marked copy of ANOMALY_INJECTED_ROWS real money-out rows with the amount multiplied 5-10 times."""
    pool = rows[rows["direction"] == "out"]
    picked = pool.iloc[rng.choice(len(pool), size=cfg.ANOMALY_INJECTED_ROWS, replace=False)].copy()
    picked["amount"] = np.round(picked["amount"] * rng.uniform(*cfg.ANOMALY_INJECT_MULT, size=len(picked)))
    picked["injected"] = 1  # Clearly marked: these rows are artificial.
    return picked


@functools.lru_cache(maxsize=1)
def load():
    """The saved model bundle, or None if python -m src.models.anomaly has not been run yet."""
    if not MODEL_PATH.exists():
        return None
    with MODEL_PATH.open("rb") as f:
        return pickle.load(f)  # Our own file, written by main() below.


def is_unusual(bundle, rows):
    """True/False per row: the IsolationForest score is below the cut learned on the training months."""
    return bundle["model"].score_samples(feature_matrix(rows)) < bundle["cut"]


def main():
    """Train on training months 1-3, evaluate on test months with injected outliers, save under artifacts/anomaly/."""
    users, tx, bal = load_data()
    first_test = cfg.N_MONTHS - cfg.TEST_MONTHS
    train = transaction_rows(tx, bal, range(1, first_test))  # Month 0 has no earlier months to compare with.
    test = transaction_rows(tx, bal, range(first_test, cfg.N_MONTHS))

    model = IsolationForest(n_estimators=200, random_state=cfg.SEED, n_jobs=1)
    model.fit(feature_matrix(train))
    cut = float(np.quantile(model.score_samples(feature_matrix(train)), cfg.ANOMALY_TRAIN_FLAG_RATE))
    bundle = {"model": model, "cut": cut, "features": FEATURES, "types": TYPES, "sklearn": sklearn.__version__}

    # Evaluation on a copy of the test months with marked artificial outliers.
    rng = np.random.default_rng(cfg.SEED)
    injected = inject_outliers(test, rng)
    normal_flag = is_unusual(bundle, test)
    injected_flag = is_unusual(bundle, injected)
    train_flag = is_unusual(bundle, train)
    metrics = {
        "simulated": True,
        "what_it_is": "IsolationForest pattern check relative to each user's own earlier months; not fraud detection.",
        "seed": cfg.SEED, "features": FEATURES, "train_months": list(range(1, first_test)),
        "test_months": list(range(first_test, cfg.N_MONTHS)), "train_rows": len(train), "test_rows": len(test),
        "flag_rate_target": cfg.ANOMALY_TRAIN_FLAG_RATE,
        "train_flag_rate": round(float(train_flag.mean()), 4),
        "test_normal_rows": int(len(test)), "test_normal_flagged": int(normal_flag.sum()),
        "test_normal_false_flag_rate": round(float(normal_flag.mean()), 4),
        "injected_rows": int(len(injected)), "injected_flagged": int(injected_flag.sum()),
        "injected_flag_rate": round(float(injected_flag.mean()), 4),
        "injection": f"copies of real money-out test rows with the amount multiplied by "
                     f"{cfg.ANOMALY_INJECT_MULT[0]:g}-{cfg.ANOMALY_INJECT_MULT[1]:g}; artificial and marked",
        "design_change": "One-hot type columns were removed after a first run that flagged 54% of the rare "
                         "add_money training rows; that first run's test results had also been seen "
                         "(injected outliers caught 1.8%, normal false flags 0.82%). No other setting was changed.",
        "caveat": "The injected outliers are built to be large, so a high catch rate is expected. "
                  "This shows the check works end to end, not how it would do on real unusual activity.",
        # Per type: share of training rows flagged, false flags on normal test rows, injected outliers caught.
        "by_type": {t: {"train_flag_rate": round(float(train_flag[(train["type"] == t).values].mean()), 4)
                        if (train["type"] == t).any() else None,
                        "test_false_flag_rate": round(float(normal_flag[(test["type"] == t).values].mean()), 4)
                        if (test["type"] == t).any() else None,
                        "injected_rows": int((injected["type"] == t).sum()),
                        "injected_flag_rate": round(float(injected_flag[(injected["type"] == t).values].mean()), 4)
                        if (injected["type"] == t).any() else None}
                    for t in TYPES},
    }
    cfg.ANOMALY_DIR.mkdir(parents=True, exist_ok=True)
    with MODEL_PATH.open("wb") as f:
        pickle.dump(bundle, f)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Training rows (months 1-{first_test - 1}): {len(train)}, flagged {metrics['train_flag_rate']:.2%} "
          f"(target {cfg.ANOMALY_TRAIN_FLAG_RATE:.0%})")
    print(f"Test months: {len(test)} normal rows, false flags {metrics['test_normal_flagged']} "
          f"({metrics['test_normal_false_flag_rate']:.2%})")
    print(f"Injected outliers: {len(injected)}, flagged {metrics['injected_flagged']} "
          f"({metrics['injected_flag_rate']:.2%})")
    for t, s in metrics["by_type"].items():
        print(f"  {t:<18} train flagged {s['train_flag_rate']}, test false flags {s['test_false_flag_rate']}, "
              f"injected {s['injected_rows']} caught {s['injected_flag_rate']}")
    print(f"Saved {MODEL_PATH.relative_to(cfg.PROJECT_ROOT)} and {METRICS_PATH.relative_to(cfg.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
