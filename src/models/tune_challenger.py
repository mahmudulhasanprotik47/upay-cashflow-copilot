# Challenger experiment: extra features plus a seeded random search of model settings, compared with the
# SHIPPED model and the day-20 balance rule. Settings and alert threshold are chosen on the training months
# only (the existing expanding-window method); test months 4-5 are scored ONCE at the end. Nothing shipped
# changes: the app keeps using artifacts/liquidity_model.json. All data is simulated.
# Run: python -m src.models.tune_challenger   (writes artifacts/challenger/comparison.json and summary.txt)

import json  # Writes the comparison.

import numpy as np  # Number tools.
import pandas as pd  # Table tools.
from sklearn.metrics import average_precision_score  # PR-AUC.
from xgboost import XGBClassifier  # Same model family as shipped.

from src import config as cfg  # Seed, months, folders, trials.
from src.features.build_features import FEATURES, build_features, load_data  # Shipped features (unchanged).
from src.features.challenger_features import NEW_FEATURES, challenger_features, leakage_by_feature  # Candidates.
from src.models.train_liquidity import (best_f1_cut, classify_metrics, precision_of, recall_of,  # Reused helpers.
                                        top_k_flag, view_masks)

CH_FEATURES = FEATURES + NEW_FEATURES  # Challenger inputs: the 11 shipped ones plus the candidates.
FLOOR = cfg.SHORTFALL_FLOOR_BDT


def r(x, digits=4):
    """Round for JSON; blank stays None."""
    return None if x is None or pd.isna(x) else round(float(x), digits)


def sample_settings(rng, pos_weight):
    """One random setting from the search space (monotone constraint on balance_day20 is always kept)."""
    return {"n_estimators": int(rng.integers(100, 601)), "max_depth": int(rng.integers(2, 7)),
            "learning_rate": float(10 ** rng.uniform(np.log10(0.02), np.log10(0.2))),
            "min_child_weight": float(rng.choice([1, 2, 5, 10])), "subsample": float(rng.uniform(0.6, 1.0)),
            "colsample_bytree": float(rng.uniform(0.6, 1.0)), "reg_lambda": float(10 ** rng.uniform(-0.3, 1.0)),
            "scale_pos_weight": float(rng.choice([1.0, pos_weight]))}


def fit(rows, settings):
    """Fit one challenger model with these settings; risk never rises with balance_day20."""
    monotone = tuple(-1 if f == "balance_day20" else 0 for f in CH_FEATURES)
    model = XGBClassifier(**settings, tree_method="hist", n_jobs=1, random_state=cfg.SEED,
                          eval_metric="logloss", monotone_constraints=monotone)
    model.fit(rows[CH_FEATURES], rows["label"])
    return model


def out_of_fold(train, settings):
    """Expanding window: each of the last two training months predicted by a model fit on earlier months."""
    parts = []
    for val_month in sorted(train["month"].unique())[-2:]:
        val = train[train["month"] == val_month].copy()
        val["prob"] = fit(train[train["month"] < val_month], settings).predict_proba(val[CH_FEATURES])[:, 1]
        parts.append(val)
    return pd.concat(parts)


def confusion(y, flag):
    """True/false positives and negatives."""
    y, flag = np.asarray(y) == 1, np.asarray(flag, dtype=bool)
    return {"tp": int((flag & y).sum()), "fp": int((flag & ~y).sum()), "fn": int((~flag & y).sum()),
            "tn": int((~flag & ~y).sum())}


def compare(test, out, lines):
    """Per view: PR-AUC, precision, recall, F1 for the three methods, plus equal alert volume."""
    out["views"], out["shipped_confusion"] = {}, {}
    for view, mask in view_masks(test).items():
        t = test[mask]
        y = t["label"].values
        methods = {"shipped": (t["shipped_prob"].values, t["shipped_alert"].values == 1),
                   "challenger": (t["ch_prob"].values, t["ch_alert"].values),
                   "rule": (-t["balance_day20"].values, t["rule_alert"].values == 1)}
        v = {m: classify_metrics(y, s, f) for m, (s, f) in methods.items()}
        k = int(methods["rule"][1].sum())  # Equal alert volume: as many alerts as the rule raises.
        eq = {"alerts": k, "rule_recall": r(recall_of(y, methods["rule"][1])),
              "rule_precision": r(precision_of(y, methods["rule"][1]))}
        for m in ("shipped", "challenger"):
            flag = top_k_flag(methods[m][0], k)
            eq[f"{m}_recall"], eq[f"{m}_precision"] = r(recall_of(y, flag)), r(precision_of(y, flag))
        v["equal_volume"] = eq
        out["views"][view] = v
        out["shipped_confusion"][view] = confusion(y, methods["shipped"][1])
        lines.append(f"{view}: rows {len(t)}, shortfalls {int(y.sum())}")
        for m in ("shipped", "challenger", "rule"):
            lines.append(f"  {m:<10} PR-AUC {v[m]['pr_auc']:.3f}  P {v[m]['precision']:.3f}  R {v[m]['recall']:.3f}  "
                         f"F1 {v[m]['f1']:.3f}  recall@{k} alerts {eq[m + '_recall']:.3f}")


def bootstrap(test, out, lines):
    """200 resamples of USERS: View 2 differences with 95% intervals."""
    rng = np.random.default_rng(cfg.SEED)
    users = test["user_id"].unique()
    rows_by_user = test.groupby("user_id").indices
    diffs = {"challenger_minus_shipped_view2_pr_auc": [], "challenger_minus_rule_view2_pr_auc": [],
             "challenger_minus_shipped_view2_equal_volume_recall": []}
    for _ in range(cfg.BOOTSTRAP_RESAMPLES):
        s = test.iloc[np.concatenate([rows_by_user[u] for u in rng.choice(users, size=len(users), replace=True)])]
        s = s[s["balance_day20"] >= FLOOR]
        y = s["label"].values
        pr_ch = average_precision_score(y, s["ch_prob"])
        diffs["challenger_minus_shipped_view2_pr_auc"].append(pr_ch - average_precision_score(y, s["shipped_prob"]))
        diffs["challenger_minus_rule_view2_pr_auc"].append(pr_ch - average_precision_score(y, -s["balance_day20"]))
        k = int((s["rule_alert"] == 1).sum())
        diffs["challenger_minus_shipped_view2_equal_volume_recall"].append(
            recall_of(y, top_k_flag(s["ch_prob"].values, k)) - recall_of(y, top_k_flag(s["shipped_prob"].values, k)))
    out["bootstrap_95ci"], out["bootstrap_mean"] = {}, {}
    for key, vals in diffs.items():
        lo, hi = np.percentile(vals, [2.5, 97.5])
        out["bootstrap_95ci"][key], out["bootstrap_mean"][key] = [r(lo), r(hi)], r(np.mean(vals))
        lines.append(f"Bootstrap {key}: mean {np.mean(vals):+.3f}, 95% interval [{lo:+.3f}, {hi:+.3f}]")
    lines.append(f"  ({cfg.BOOTSTRAP_RESAMPLES} resamples of users, seeded)")


def verdict(out):
    """better / same / worse from the View 2 PR-AUC interval of challenger minus shipped."""
    lo, hi = out["bootstrap_95ci"]["challenger_minus_shipped_view2_pr_auc"]
    if lo > 0:
        return "better", "The challenger is better than the shipped model: the View 2 PR-AUC interval is above zero."
    if hi < 0:
        return "worse", "The challenger is worse than the shipped model: the View 2 PR-AUC interval is below zero."
    return "same", ("The challenger is not clearly better than the shipped model: the View 2 PR-AUC interval "
                    "includes zero. The shipped model stays.")


def main():
    """Build features, check leakage, search settings on training months, score test months once, compare."""
    users, tx, bal = load_data()
    base = build_features(users, tx, bal)
    extra = challenger_features(tx, bal)
    df = base.merge(extra.reset_index(), on=["user_id", "month"], how="left")
    lines, out = [], {"simulated": True, "experiment_only": True, "app_uses": "shipped model (unchanged)"}

    # Leakage: every candidate must be identical when rows after day 20 are deleted.
    leak = leakage_by_feature(tx, bal, extra)
    out["leakage_test"] = leak
    lines.append("Leakage test per candidate (rebuild without days > 20): "
                 + ", ".join(f"{f} {'PASS' if ok else 'FAIL'}" for f, ok in leak.items()))
    if not all(leak.values()):
        raise SystemExit("A candidate feature leaks future data; stopping.")

    first_test = cfg.N_MONTHS - cfg.TEST_MONTHS
    train = df[df["month"] < first_test].reset_index(drop=True)
    test = df[df["month"] >= first_test].reset_index(drop=True)

    # Seeded random search on the training months only, scored by pooled out-of-fold PR-AUC.
    rng = np.random.default_rng(cfg.SEED)
    pos_weight = float((train["label"] == 0).sum() / max(1, (train["label"] == 1).sum()))
    trials = []
    for i in range(cfg.CHALLENGER_TRIALS):
        settings = sample_settings(rng, pos_weight)
        oof = out_of_fold(train, settings)
        trials.append({"settings": settings, "oof_pr_auc": r(average_precision_score(oof["label"], oof["prob"]))})
    best = max(trials, key=lambda t: t["oof_pr_auc"])
    oof = out_of_fold(train, best["settings"])
    threshold, oof_f1 = best_f1_cut(oof["label"].values, oof["prob"].values)  # Same rule as the shipped model.
    out["search"] = {"trials": cfg.CHALLENGER_TRIALS, "chosen_by": "pooled out-of-fold PR-AUC, training months only",
                     "best_oof_pr_auc": best["oof_pr_auc"], "chosen_settings": best["settings"],
                     "oof_f1_at_chosen_threshold": r(oof_f1), "chosen_threshold": r(threshold, 6)}
    lines.append(f"Random search: {cfg.CHALLENGER_TRIALS} settings; best out-of-fold PR-AUC {best['oof_pr_auc']:.3f}")
    lines.append(f"  chosen settings: {json.dumps({k: round(v, 3) for k, v in best['settings'].items()})}")

    # Test months, touched once: challenger, shipped (saved predictions) and the rule (saved flags).
    test["ch_prob"] = fit(train, best["settings"]).predict_proba(test[CH_FEATURES])[:, 1]
    test["ch_alert"] = test["ch_prob"] >= threshold
    shipped = pd.read_csv(cfg.ARTIFACTS_DIR / "test_predictions.csv")[
        ["user_id", "month", "probability", "alert", "rule_alert"]].rename(
        columns={"probability": "shipped_prob", "alert": "shipped_alert"})
    test = test.merge(shipped, on=["user_id", "month"], how="left")
    lines.append(f"Test months {sorted(test['month'].unique().tolist())}: {len(test)} rows (scored once)")
    compare(test, out, lines)
    bootstrap(test, out, lines)
    stored = json.loads((cfg.ARTIFACTS_DIR / "metrics.json").read_text(encoding="utf-8"))
    same = out["views"]["view2_not_below_day20"]["shipped"]["pr_auc"] == stored["view2_not_below_day20"]["model"]["pr_auc"]
    lines.append(f"Shipped View 2 PR-AUC recomputed here matches metrics.json: {same}")
    out["verdict"], out["verdict_text"] = verdict(out)
    lines.append(f"Verdict: {out['verdict'].upper()}. {out['verdict_text']}")
    lines.append("The app is NOT switched to the challenger; promotion is a separate decision.")

    cfg.CHALLENGER_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.CHALLENGER_DIR / "comparison.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    text = "\n".join(lines) + "\n"
    (cfg.CHALLENGER_DIR / "summary.txt").write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
