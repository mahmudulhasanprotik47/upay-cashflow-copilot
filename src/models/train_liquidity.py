# Trains the liquidity (shortfall) model, compares it with two simple baselines,
# explains it and checks fairness. All data is simulated.
# Run: python -m src.models.train_liquidity

import json  # Saves metrics and settings as JSON files.

import numpy as np  # Number tools.
import pandas as pd  # Table tools.
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # Scores.
from xgboost import DMatrix, XGBClassifier, XGBRegressor  # Gradient-boosted tree models.

from src import config as cfg  # Central settings.
from src.features.build_features import (  # Feature builder from this project.
    FEATURES, build_features, leakage_test, load_data, summary_lines)

FLOOR = cfg.SHORTFALL_FLOOR_BDT  # Short name for the 500 BDT floor.


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def r(x, digits=4):
    """Round a number for printing and JSON; blank stays None."""
    return None if x is None or pd.isna(x) else round(float(x), digits)


def model_params():
    """Fixed model settings from config, identical for every model we fit."""
    return dict(n_estimators=cfg.MODEL_N_ESTIMATORS, max_depth=cfg.MODEL_MAX_DEPTH,
                learning_rate=cfg.MODEL_LEARNING_RATE, tree_method="hist",
                n_jobs=1, random_state=cfg.SEED)


def fit_classifier(df, labels=None):
    """Fit the shortfall classifier on the given rows (optionally on other labels)."""
    # Force risk to never go UP when balance_day20 goes up (-1); other features are free (0).
    monotone = tuple(-1 if f == "balance_day20" else 0 for f in FEATURES)
    model = XGBClassifier(**model_params(), eval_metric="logloss", monotone_constraints=monotone)
    model.fit(df[FEATURES], df["label"] if labels is None else labels)
    return model


def risk(model, df):
    """Predicted shortfall probability for each row."""
    return model.predict_proba(df[FEATURES])[:, 1]


def best_f1_cut(y, score):
    """Find the cut t that gives the highest F1 when we flag score >= t."""
    order = np.argsort(-score, kind="stable")  # Highest scores first.
    s, yy = score[order], np.asarray(y)[order]
    tp = np.cumsum(yy)  # True alerts if we flag the top n rows.
    n = np.arange(1, len(s) + 1)  # Number of alerts if we flag the top n rows.
    f1 = 2 * tp / (n + yy.sum())  # F1 = 2TP / (alerts + actual positives).
    # Only cut between different scores, so tied rows are flagged together.
    f1 = np.where(np.r_[s[1:] != s[:-1], True], f1, -1)
    i = int(np.argmax(f1))
    return float(s[i]), float(f1[i])


def classify_metrics(y, score, flag):
    """ROC-AUC, PR-AUC, precision, recall and F1 for one method."""
    y, flag = np.asarray(y), np.asarray(flag, dtype=bool)
    tp = int((flag & (y == 1)).sum())  # Correct alerts.
    precision = tp / flag.sum() if flag.sum() else 0.0  # Share of alerts that were right.
    recall = tp / y.sum() if y.sum() else 0.0  # Share of shortfalls we caught.
    f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
    return {"roc_auc": r(roc_auc_score(y, score)), "pr_auc": r(average_precision_score(y, score)),
            "precision": r(precision), "recall": r(recall), "f1": r(f1)}


def top_k_flag(prob, k):
    """Flag the k rows with the highest risk (used for equal alert volume)."""
    flag = np.zeros(len(prob), dtype=bool)
    flag[np.argsort(-prob, kind="stable")[:k]] = True
    return flag


def recall_of(y, flag):
    """Share of actual shortfalls that were flagged."""
    y = np.asarray(y)
    return float(flag[y == 1].mean()) if (y == 1).any() else 0.0


def precision_of(y, flag):
    """Share of alerts that were real shortfalls."""
    return float(np.asarray(y)[flag].mean()) if flag.any() else 0.0


# ---------------------------------------------------------------------------
# Threshold selection inside the training months only
# ---------------------------------------------------------------------------

def expanding_window_oof(train):
    """Validate each of the last two training months with a model fit on earlier months."""
    months = sorted(train["month"].unique())
    parts = []
    for val_month in months[-2:]:
        fit_rows = train[train["month"] < val_month]  # Only months before the validation month.
        val = train[train["month"] == val_month].copy()
        val["prob"] = risk(fit_classifier(fit_rows), val)  # Out-of-fold predictions.
        parts.append(val)
    return pd.concat(parts)  # Pooled out-of-fold set.


def choose_settings(oof):
    """Pick the model threshold and the rule's X by max F1 on the pooled out-of-fold set."""
    threshold, model_f1 = best_f1_cut(oof["label"].values, oof["prob"].values)
    # Rule flags low balances, so score = -balance. Flag -bal >= t means bal < 1 - t (whole BDT).
    cut, rule_f1 = best_f1_cut(oof["label"].values, -oof["balance_day20"].values)
    return {"learned_threshold": threshold, "oof_model_f1": model_f1,
            "rule_x": 1 - cut, "oof_rule_f1": rule_f1, "oof_rows": len(oof)}


# ---------------------------------------------------------------------------
# Test-month evaluation
# ---------------------------------------------------------------------------

def method_scores(test, rule_x, threshold):
    """Score and alert flag for the rule, persistence and the model."""
    persist = test["prev_month_shortfall"].fillna(0).values  # Blank counts as no alert.
    return {
        "rule": (-test["balance_day20"].values, test["balance_day20"].values < rule_x),
        "persistence": (persist, persist == 1),
        "model": (test["prob"].values, test["prob"].values >= threshold),
    }


def view_masks(test):
    """View 1 = all user-months; View 2 = not already below the floor on day 20."""
    return {"view1_all": np.ones(len(test), dtype=bool),
            "view2_not_below_day20": test["balance_day20"].values >= FLOOR}


def evaluate_views(test, scores, out, lines):
    """Main metrics and equal-alert-volume comparison for each view."""
    y_all = test["label"].values
    for view, mask in view_masks(test).items():
        y = y_all[mask]
        lines.append(f"{view}: rows {mask.sum()}, shortfalls {y.sum()}")
        out[view] = {}
        for name, (score, flag) in scores.items():
            m = classify_metrics(y, score[mask], flag[mask])
            out[view][name] = m
            lines.append(f"  {name:<11} ROC-AUC {m['roc_auc']:.3f}  PR-AUC {m['pr_auc']:.3f}  "
                         f"P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}")
        # Equal alert volume: the model raises as many alerts as the rule in this view.
        rule_flag = scores["rule"][1][mask]
        model_flag = top_k_flag(scores["model"][0][mask], int(rule_flag.sum()))
        eq = {"alerts": int(rule_flag.sum()),
              "rule_recall": r(recall_of(y, rule_flag)), "rule_precision": r(precision_of(y, rule_flag)),
              "model_recall": r(recall_of(y, model_flag)),
              "model_precision": r(precision_of(y, model_flag))}
        out[view]["equal_volume"] = eq
        lines.append(f"  equal volume ({eq['alerts']} alerts): rule R {eq['rule_recall']:.3f} "
                     f"P {eq['rule_precision']:.3f} | model R {eq['model_recall']:.3f} "
                     f"P {eq['model_precision']:.3f}")


def catch_counts(test, scores, out, lines):
    """Who caught which shortfalls, per view, using each method's own alert setting."""
    y = test["label"].values == 1
    for view, mask in view_masks(test).items():
        rule = scores["rule"][1] & y & mask  # Shortfalls caught by the rule.
        model = scores["model"][1] & y & mask  # Shortfalls caught by the model.
        c = {"shortfalls": int((y & mask).sum()), "caught_rule": int(rule.sum()),
             "caught_model": int(model.sum()), "only_model": int((model & ~rule).sum()),
             "only_rule": int((rule & ~model).sum())}
        out[view]["counts"] = c
        lines.append(f"  {view} counts: shortfalls {c['shortfalls']}, rule {c['caught_rule']}, "
                     f"model {c['caught_model']}, only model {c['only_model']}, "
                     f"only rule {c['only_rule']}")


def lead_time(test, scores, out, lines):
    """Days between the prediction and the first dip, for shortfalls the model caught."""
    caught = scores["model"][1] & (test["label"].values == 1)
    days = test.loc[caught, "first_dip_day"] - cfg.PREDICTION_DAY
    out["lead_time_days"] = {"mean": r(days.mean(), 2), "median": r(days.median(), 2),
                             "n": int(len(days))}
    lines.append(f"Lead time (model-caught shortfalls, n={len(days)}): "
                 f"mean {days.mean():.2f} days, median {days.median():.1f} days")


def calibration(test, out, lines):
    """Brier score and a 10-bin table of predicted risk vs actual rate."""
    prob, y = test["prob"].values, test["label"].values
    out["brier"] = r(brier_score_loss(y, prob))
    lines.append(f"Calibration: Brier score {out['brier']:.4f}")
    bins = np.minimum((prob * 10).astype(int), 9)  # Bin 0 = 0.0-0.1, ... bin 9 = 0.9-1.0.
    out["calibration_bins"] = []
    for b in range(10):
        m = bins == b
        row = {"bin": f"{b / 10:.1f}-{(b + 1) / 10:.1f}", "rows": int(m.sum()),
               "mean_pred": r(prob[m].mean()) if m.any() else None,
               "actual_rate": r(y[m].mean()) if m.any() else None}
        out["calibration_bins"].append(row)
        if m.any():
            lines.append(f"  bin {row['bin']}: rows {row['rows']}, mean predicted "
                         f"{row['mean_pred']:.3f}, actual {row['actual_rate']:.3f}")


def bootstrap(test, rule_x, out, lines):
    """Resample USERS to get 95% intervals for model-minus-rule in View 2."""
    rng = np.random.default_rng(cfg.SEED)  # Seeded, so intervals are repeatable.
    users = test["user_id"].unique()
    rows_by_user = test.groupby("user_id").indices  # Row positions for each user.
    pr_diff, rec_diff = [], []
    for _ in range(cfg.BOOTSTRAP_RESAMPLES):
        pick = rng.choice(users, size=len(users), replace=True)  # Users drawn with replacement.
        s = test.iloc[np.concatenate([rows_by_user[u] for u in pick])]
        s = s[s["balance_day20"] >= FLOOR]  # View 2 only.
        y, prob, bal = s["label"].values, s["prob"].values, s["balance_day20"].values
        pr_diff.append(average_precision_score(y, prob) - average_precision_score(y, -bal))
        rule_flag = bal < rule_x
        rec_diff.append(recall_of(y, top_k_flag(prob, int(rule_flag.sum())))
                        - recall_of(y, rule_flag))
    for key, vals, label in [("view2_pr_auc_diff", pr_diff, "PR-AUC"),
                             ("view2_equal_volume_recall_diff", rec_diff, "recall @ equal volume")]:
        lo, hi = np.percentile(vals, [2.5, 97.5])
        out.setdefault("bootstrap_95ci", {})[key] = [r(lo), r(hi)]
        lines.append(f"Bootstrap View 2 {label}, model minus rule: "
                     f"mean {np.mean(vals):+.3f}, 95% CI [{lo:+.3f}, {hi:+.3f}]")
    lines.append(f"  ({cfg.BOOTSTRAP_RESAMPLES} resamples of users, seeded)")


# ---------------------------------------------------------------------------
# Sanity checks, helper regressor, SHAP and fairness
# ---------------------------------------------------------------------------

def sanity_checks(train, test, model, out, lines):
    """Shuffled-label check, direction check and the 70/30 user holdout (report only)."""
    rng = np.random.default_rng(cfg.SEED)
    # (1) A model trained on shuffled labels should be no better than chance.
    shuffled = fit_classifier(train, rng.permutation(train["label"].values))
    auc = roc_auc_score(test["label"], risk(shuffled, test))
    lines.append(f"Sanity 1, shuffled-label model test ROC-AUC: {auc:.3f} (about 0.5 expected)")
    # (2) Adding 1000 BDT to the day-20 balance should usually lower the risk.
    richer = test.copy()
    richer["balance_day20"] += 1000
    new_prob = risk(model, richer)
    share_down = float((new_prob < test["prob"].values).mean())  # Risk fell.
    share_up = float((new_prob > test["prob"].values).mean())  # Risk rose (should be rare).
    lines.append(f"Sanity 2, +1000 BDT on balance_day20: risk down {share_down:.1%}, "
                 f"up {share_up:.1%}, unchanged {1 - share_down - share_up:.1%} of rows")
    # (3) Train on 70% of users, test on the other 30% (unseen users), View 2 PR-AUC.
    users = rng.permutation(train["user_id"].unique())
    held = set(users[: int(0.3 * len(users))])
    held_model = fit_classifier(train[~train["user_id"].isin(held)])
    t = test[test["user_id"].isin(held) & (test["balance_day20"] >= FLOOR)]
    pr_held = average_precision_score(t["label"], risk(held_model, t))
    pr_main_same = average_precision_score(t["label"], t["prob"])
    lines.append(f"Sanity 3, View 2 PR-AUC on 30% unseen users: {pr_held:.3f} "
                 f"(main model on same users {pr_main_same:.3f})")
    out["sanity"] = {"shuffled_label_test_roc_auc": r(auc), "direction_share_down": r(share_down),
                     "direction_share_up": r(share_up),
                     "holdout_users_view2_pr_auc": r(pr_held),
                     "main_model_same_users_view2_pr_auc": r(pr_main_same)}


def helper_regressor(train, test, out, lines):
    """Predict the lowest balance on days 21-30 (only used for the buffer amount)."""
    reg = XGBRegressor(**model_params())
    reg.fit(train[FEATURES], train["min_balance_d21_30"])
    pred = reg.predict(test[FEATURES])
    err = np.abs(pred - test["min_balance_d21_30"].values)  # Model error in BDT.
    naive = np.abs(test["balance_day20"].values - test["min_balance_d21_30"].values)  # Naive guess.
    short = test["label"].values == 1
    out["min_balance_mae_bdt"] = {"model_all": r(err.mean(), 1), "model_shortfall": r(err[short].mean(), 1),
                                  "naive_all": r(naive.mean(), 1), "naive_shortfall": r(naive[short].mean(), 1)}
    lines.append(f"Min-balance regressor MAE: all {err.mean():.0f} BDT, shortfall rows "
                 f"{err[short].mean():.0f} BDT")
    lines.append(f"  naive (min = balance_day20) MAE: all {naive.mean():.0f} BDT, shortfall rows "
                 f"{naive[short].mean():.0f} BDT")
    return reg, pred


def shap_global(model, test, lines):
    """Mean absolute SHAP value per feature on the test rows."""
    X = test[FEATURES]
    try:
        import shap  # Imported here so a broken shap install only triggers the fallback.
        vals, method = np.asarray(shap.TreeExplainer(model).shap_values(X)), "shap.TreeExplainer"
    except Exception as e:  # Fallback: xgboost's own exact tree contributions.
        vals = model.get_booster().predict(DMatrix(X), pred_contribs=True)[:, :-1]
        method = f"xgboost pred_contribs (TreeExplainer failed: {type(e).__name__})"
    mean_abs = dict(zip(FEATURES, np.abs(vals).mean(axis=0)))
    ranked = {f: r(v) for f, v in sorted(mean_abs.items(), key=lambda kv: -kv[1])}
    lines.append(f"SHAP method: {method}")
    for f, v in ranked.items():
        lines.append(f"  {f:<24} mean |SHAP| {v:.4f}")
    return {"method": method, "mean_abs_shap": ranked}


def fairness(test, flag, lines):
    """Per-group rows, shortfall rate, alert rate, recall and false-positive rate."""
    report = {}
    for col in cfg.FAIRNESS_COLUMNS:
        groups = {}
        for g, d in test.groupby(col):
            y, f = d["label"].values, flag[d.index]
            groups[g] = {"rows": len(d), "shortfall_rate": r(y.mean()), "alert_rate": r(f.mean()),
                         "recall": r(f[y == 1].mean()) if (y == 1).any() else None,
                         "fpr": r(f[y == 0].mean()) if (y == 0).any() else None,
                         "low_sample": len(d) < cfg.MIN_GROUP_ROWS}
            s = groups[g]
            lines.append(f"  {col}={g}: rows {s['rows']}, shortfall {s['shortfall_rate']:.3f}, "
                         f"alert {s['alert_rate']:.3f}, recall {s['recall']:.3f}, "
                         f"FPR {s['fpr']:.3f}" + (" LOW SAMPLE" if s["low_sample"] else ""))
        ok = [s for s in groups.values() if not s["low_sample"]]  # Gaps ignore low-sample groups.
        gaps = {k: r(max(s[k] for s in ok) - min(s[k] for s in ok)) for k in ("recall", "fpr")}
        report[col] = {"groups": groups, "largest_gaps": gaps}
        lines.append(f"  {col}: largest recall gap {gaps['recall']:.3f}, "
                     f"largest FPR gap {gaps['fpr']:.3f}")
    return report


# ---------------------------------------------------------------------------
# One full training run
# ---------------------------------------------------------------------------

def run_training(feat):
    """Everything from split to fairness. Returns results; prints nothing."""
    lines, metrics = [], {}
    months = sorted(int(m) for m in feat["month"].unique())  # Months as plain numbers (0-based).
    test_months = months[-cfg.TEST_MONTHS:]  # The latest months are the test months.
    train = feat[~feat["month"].isin(test_months)].reset_index(drop=True)
    test = feat[feat["month"].isin(test_months)].reset_index(drop=True)
    lines.append(f"Split: train months {months[:-cfg.TEST_MONTHS]} ({len(train)} rows), "
                 f"test months {test_months} ({len(test)} rows)")

    # Choose the alert threshold and rule X on out-of-fold training predictions only.
    settings = choose_settings(expanding_window_oof(train))
    threshold = (settings["learned_threshold"] if cfg.ALERT_THRESHOLD_OVERRIDE is None
                 else cfg.ALERT_THRESHOLD_OVERRIDE)
    rule_x = settings["rule_x"]
    metrics["settings"] = {**{k: r(v, 6) for k, v in settings.items()}, "threshold_used": r(threshold, 6)}
    lines.append(f"Out-of-fold ({settings['oof_rows']} rows): model threshold "
                 f"{settings['learned_threshold']:.4f} (F1 {settings['oof_model_f1']:.3f}), "
                 f"rule X {rule_x:.0f} BDT (F1 {settings['oof_rule_f1']:.3f})")
    if cfg.ALERT_THRESHOLD_OVERRIDE is not None:
        lines.append(f"Threshold override in use: {threshold}")

    # Refit on all training months with the same fixed settings; score the test months.
    model = fit_classifier(train)
    test["prob"] = risk(model, test)
    scores = method_scores(test, rule_x, threshold)

    lines.append("Test results:")
    evaluate_views(test, scores, metrics, lines)
    catch_counts(test, scores, metrics, lines)
    lead_time(test, scores, metrics, lines)
    calibration(test, metrics, lines)
    bootstrap(test, rule_x, metrics, lines)
    sanity_checks(train, test, model, metrics, lines)
    reg, min_pred = helper_regressor(train, test, metrics, lines)
    shap_info = shap_global(model, test, lines)
    lines.append("Fairness (test months, model alerts):")
    fair = fairness(test, scores["model"][1], lines)

    # Test predictions table for the app and for the predict.py self-check.
    preds = pd.DataFrame({"user_id": test["user_id"], "month": test["month"],
                          "probability": test["prob"].round(6),
                          "alert": scores["model"][1].astype(int),
                          "rule_alert": scores["rule"][1].astype(int),
                          "predicted_min_balance": np.round(min_pred).astype(int)})
    threshold_info = {"learned_threshold": settings["learned_threshold"],
                      "alert_threshold_override": cfg.ALERT_THRESHOLD_OVERRIDE,
                      "rule_x_bdt": rule_x, "features": FEATURES}
    return dict(lines=lines, metrics=metrics, fairness=fair, shap=shap_info, model=model,
                regressor=reg, preds=preds, threshold=threshold_info)


def write_json(name, obj):
    """Save a dict as pretty JSON in artifacts/ and return the file bytes."""
    path = cfg.ARTIFACTS_DIR / name
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    return path.read_bytes()


def main():
    """Build features, train twice (determinism), save artifacts and the summary."""
    users, tx, bal = load_data()
    feat = build_features(users, tx, bal)
    lines = summary_lines(feat, tx, leakage_test(users, tx, bal, feat))

    first = run_training(feat)
    bytes_1 = write_json("metrics.json", first["metrics"])
    bytes_2 = write_json("metrics.json", run_training(feat)["metrics"])  # Second identical run.
    lines += first["lines"]
    lines.append(f"Determinism: two runs give byte-identical metrics.json: {bytes_1 == bytes_2}")

    # Save the remaining artifacts from the first run.
    first["model"].save_model(cfg.ARTIFACTS_DIR / "liquidity_model.json")
    first["regressor"].save_model(cfg.ARTIFACTS_DIR / "min_balance_model.json")
    write_json("threshold.json", first["threshold"])
    write_json("fairness.json", first["fairness"])
    write_json("shap_global.json", first["shap"])
    first["preds"].to_csv(cfg.ARTIFACTS_DIR / "test_predictions.csv", index=False)

    # File sizes (results_summary.txt is written last, so its size is printed after).
    names = ["liquidity_model.json", "min_balance_model.json", "threshold.json", "metrics.json",
             "fairness.json", "shap_global.json", "test_predictions.csv"]
    sizes = {n: (cfg.ARTIFACTS_DIR / n).stat().st_size for n in names}
    lines.append("Artifact sizes:")
    lines += [f"  {n}: {s / 1024:.1f} KB" for n, s in sizes.items()]

    text = "\n".join(lines) + "\n"
    (cfg.ARTIFACTS_DIR / "results_summary.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    summary_size = (cfg.ARTIFACTS_DIR / "results_summary.txt").stat().st_size
    print(f"  results_summary.txt: {summary_size / 1024:.1f} KB "
          f"(total {(sum(sizes.values()) + summary_size) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
