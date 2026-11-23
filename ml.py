"""
ml.py - AI layer: synthetic training set from SWMM events, flood-risk classifier,
        anomaly detector. Training data goes through the SAME sensor/gateway code
        as the live stream (only the MQTT hop is skipped for speed).
"""
import numpy as np, pandas as pd, joblib
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.metrics import roc_auc_score, precision_score, recall_score
from sklearn.inspection import permutation_importance
from swmm_model import (hyetograph, run_sim, ramp, NODES, CONDUITS, GATE, MAX_DEPTH, SIM_MIN)
from sensors import sensorize
from gateway import Gateway, frame_from_con

HORIZON = 30          # minutes ahead the classifier looks
NODE_OUT = {"J1": "C1", "J2": "C2", "J3": "C3", "J4": "C4", "J5": "C5", "J6": "C6", "J7": "C7"}
FEATS = ["rain_now", "rain_15", "rain_60", "depth", "depth_ratio", "rise_5", "q_out",
         "res_depth", "res_q", "q_ratio"] + ["node_" + n for n in NODES]


def random_event(rng):
    peak = rng.uniform(25, 95)
    dur = int(rng.integers(30, 150))
    onset = int(rng.integers(5, 25))
    rain = hyetograph(peak, dur, onset)
    acts, truth = [], {}
    k = rng.choice([0, 1, 1, 2], p=[0.25, 0.4, 0.2, 0.15])
    for c in rng.choice(CONDUITS, size=k, replace=False):
        t0 = float(rng.integers(0, 40)); fin = float(rng.uniform(0.1, 0.8))
        acts += ramp(GATE[c], t0, t0 + 10, fin)
        truth[c] = fin
    return rain, acts, truth, dict(peak=peak, dur=dur, onset=onset)


def sensed_frame(df, seed, run_id="ev", **kw):
    gw = Gateway(":memory:")
    for m in sensorize(df, seed=seed, run_id=run_id, **kw):
        gw.on_message("", m)
    return frame_from_con(gw.con, run_id)[0]


def rain_from_frame(w, until=None, step=5):
    """
    Sensed rain -> 5-minute hyetograph for the twin. Each bin averages the readings
    that fall inside it (a reading at minute m describes minute m-1..m); the bin that is
    still open at 'until' uses what has arrived so far, and later bins are 0 (no forecast).
    """
    r = w.set_index("t_min")["rain"]
    until = int(r.index.max()) if until is None else int(until)
    r = r[r.index <= until].reindex(range(0, until + 1)).interpolate(limit=4).fillna(0)
    out, last = [], 0.0
    for b in range(0, SIM_MIN + 1, step):
        if b > until:
            out.append((b, 0.0)); continue
        seg = r.loc[b + 1: min(b + step, until)]
        v = float(seg.mean()) if len(seg) else last
        out.append((b, round(v, 2))); last = v
    return out


def build_features(w, expected):
    """One row per (node, minute) from cleaned sensor frame + healthy-model expectation."""
    w = w.set_index("t_min")
    e = expected.set_index("t_min")
    idx = w.index
    rain = w["rain"].fillna(0)
    out = []
    for n in NODES:
        c = NODE_OUT[n]
        d = w["d_" + n].rolling(3, min_periods=1).median()
        q = w["q_" + c].rolling(3, min_periods=1).median()
        de = e["d_" + n].reindex(idx).ffill()
        qe = e["q_" + c].reindex(idx).ffill()
        f = pd.DataFrame({
            "t_min": idx, "node": n,
            "rain_now": rain.rolling(3, min_periods=1).mean().values,
            "rain_15": (rain.rolling(15, min_periods=1).sum() / 60).values,
            "rain_60": (rain.rolling(60, min_periods=1).sum() / 60).values,
            "depth": d.values, "depth_ratio": (d / MAX_DEPTH).values,
            "rise_5": (d - d.shift(5)).fillna(0).values,
            "q_out": q.values,
            "res_depth": (d - de).values, "res_q": (q - qe).values,
            "q_ratio": (q / (qe + 0.05)).values})
        out.append(f)
    f = pd.concat(out, ignore_index=True)
    for n in NODES:
        f["node_" + n] = (f.node == n).astype(int)
    return f


def expected_healthy(w):
    from twin import expected_response
    return expected_response(w)


def make_dataset(n_events=160, seed=0, verbose=True):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_events):
        rain, acts, truth, meta = random_event(rng)
        df = run_sim(rain, acts)
        w = sensed_frame(df, seed=int(rng.integers(1e9)), loss=float(rng.uniform(0, 0.05)))
        f = build_features(w, expected_healthy(w))
        # label: node floods within the next HORIZON minutes
        lab = []
        for n in NODES:
            fl = df.set_index("t_min")["fl_" + n] > 1e-4
            fut = fl[::-1].rolling(HORIZON, min_periods=1).max()[::-1].shift(-1).fillna(0)
            lab.append(fut.reindex(f[f.node == n].t_min).values)
        f["y"] = np.concatenate(lab).astype(int)
        f["event"] = i
        f["flood_event"] = int(df[[c for c in df if c.startswith("fl_")]].max().max() > 1e-4)
        rows.append(f)
        if verbose and (i + 1) % 40 == 0:
            print(f"  generated {i + 1}/{n_events} events")
    return pd.concat(rows, ignore_index=True).dropna(subset=FEATS)


def _event_metrics(df, p, th):
    """Event-level view: was a flood warned about, how early, and how many false alarms."""
    det = fa = n_fl = n_ok = 0
    leads = []
    d = df.assign(p=p)
    for _, g in d.groupby("event"):
        alarm_t = g[g.p > th].t_min.min() if (g.p > th).any() else None
        if g.flood_event.iloc[0]:
            n_fl += 1
            if alarm_t is not None:
                det += 1
                leads.append(float(g[g.y == 1].t_min.min() + HORIZON - alarm_t))
        else:
            n_ok += 1
            fa += alarm_t is not None
    return {"flood_events": n_fl, "detected": det, "no_flood_events": n_ok, "false_alarm_events": fa,
            "median_lead_min": float(np.median(leads)) if leads else None}


def train(ds, out="models.joblib"):
    ev = ds.event.unique()
    rng = np.random.default_rng(1); rng.shuffle(ev)
    n = len(ev)
    te_ev, va_ev = set(ev[: n // 4]), set(ev[n // 4: n // 4 + n // 6])
    te = ds[ds.event.isin(te_ev)]; va = ds[ds.event.isin(va_ev)]
    tr = ds[~ds.event.isin(te_ev | va_ev)]
    clf = RandomForestClassifier(n_estimators=250, min_samples_leaf=5, n_jobs=-1, random_state=0)
    clf.fit(tr[FEATS], tr.y)
    # alarm threshold chosen on the validation events: catch all floods, <=10 % false-alarm events
    pv = clf.predict_proba(va[FEATS])[:, 1]
    th = 0.9
    for cand in np.arange(0.3, 0.95, 0.05):
        m = _event_metrics(va, pv, cand)
        if m["false_alarm_events"] <= 0.10 * max(m["no_flood_events"], 1) and m["detected"] == m["flood_events"]:
            th = float(round(cand, 2)); break
    p = clf.predict_proba(te[FEATS])[:, 1]
    rep = {"auc": round(float(roc_auc_score(te.y, p)), 4), "alarm_threshold": th,
           "precision": round(float(precision_score(te.y, p > th)), 3),
           "recall": round(float(recall_score(te.y, p > th)), 3),
           "train_events": int(tr.event.nunique()), "test_events": int(te.event.nunique()),
           "test_event_level": _event_metrics(te, p, th)}
    smp = te.sample(min(5000, len(te)), random_state=0)
    imp = permutation_importance(clf, smp[FEATS], smp.y, n_repeats=3, random_state=0, n_jobs=-1,
                                 scoring="roc_auc")
    rep["importance_auc_drop"] = dict(sorted(zip(FEATS, imp.importances_mean.round(4)), key=lambda x: -x[1])[:6])
    # anomaly detector fitted on healthy-network behaviour only
    h = tr[(tr.rain_now > 5) & (tr.res_depth.abs() < 0.15)][["res_depth", "res_q", "q_ratio"]]
    iso = IsolationForest(n_estimators=150, contamination=0.02, random_state=0).fit(h)
    joblib.dump({"clf": clf, "iso": iso, "report": rep, "threshold": th}, out)
    return rep


_MODELS = {}
def load_models(path="models.joblib"):
    if path not in _MODELS:
        _MODELS[path] = joblib.load(path)
    return _MODELS[path]


def predict_risk(feat, path="models.joblib"):
    m = load_models(path)
    feat = feat.copy()
    ok = feat[FEATS].notna().all(axis=1)
    feat["risk"] = np.nan
    feat.loc[ok, "risk"] = m["clf"].predict_proba(feat.loc[ok, FEATS])[:, 1]
    feat["anomaly"] = np.nan
    feat.loc[ok, "anomaly"] = -m["iso"].score_samples(feat.loc[ok, ["res_depth", "res_q", "q_ratio"]])
    return feat
