"""
twin.py - Hydraulic Digital Twin.

State synchronisation (honest description): SWMM has no built-in data assimilation,
so the twin keeps one *effective opening factor* per conduit (1.0 = clear,
0.3 = ~70 % blocked) and fits it by re-simulating the event so far with the
SENSED rainfall and comparing simulated depths/flows with the sensor readings
(greedy search over conduits + opening grid, least squares). That is explainable
and cheap; a production system could use EnKF / Bayesian calibration instead.
"""
import numpy as np, pandas as pd
from swmm_model import (run_sim, summarise, CONDUITS, NODES, GATE, UPSTREAM, MAX_DEPTH, SIM_MIN)
from ml import rain_from_frame, NODE_OUT

GRID = [0.8, 0.6, 0.45, 0.35, 0.28, 0.22, 0.17, 0.12, 0.08]
SIG_D, SIG_Q = 0.05, 0.03


def expected_response(w):
    """What a HEALTHY network would do under the rain actually observed."""
    until = int(w.t_min.max())
    return run_sim(rain_from_frame(w, until), [], until_min=until)


def _actions(settings, extra=()):
    return [(0.0, GATE[c], s) for c, s in settings.items() if s < 0.999] + list(extra)


def _cost(w, sim, t_now, recent=40):
    o = w.set_index("t_min"); s = sim.set_index("t_min")
    idx = o.index.intersection(s.index)
    idx = idx[idx <= t_now]
    if len(idx) == 0:
        return 1e9
    wt = np.where(idx >= t_now - recent, 1.0, 0.25)[:, None]
    err = []
    for n in NODES:
        err.append(((o.loc[idx, "d_" + n] - s.loc[idx, "d_" + n]) / SIG_D).values)
    for c in CONDUITS:
        sd = SIG_Q + 0.1 * s.loc[idx, "q_" + c].values
        err.append(((o.loc[idx, "q_" + c] - s.loc[idx, "q_" + c]) / sd).values)
    E = np.clip(np.vstack(err).T, -6, 6) ** 2
    m = ~np.isnan(E)
    return float(np.nansum(E * wt) / max((m * wt).sum(), 1))


def estimate_blockage(w, t_now, extra_actions=(), max_blocks=3, min_gain=0.30):
    """Fit per-conduit opening factors to sensor data up to t_now."""
    w = w[w.t_min <= t_now]
    rain = rain_from_frame(w, t_now)
    settings = {c: 1.0 for c in CONDUITS}
    sim = lambda st: run_sim(rain, _actions(st, extra_actions), until_min=t_now)
    cur = _cost(w, sim(settings), t_now)
    base = cur
    first_round = {}
    for rnd in range(max_blocks):
        best = (cur, None, None)
        for c in CONDUITS:
            if settings[c] < 0.999:
                continue
            for s in GRID:
                st = dict(settings); st[c] = s
                cst = _cost(w, sim(st), t_now)
                if rnd == 0:
                    first_round[c] = min(first_round.get(c, 1e9), cst)
                if cst < best[0]:
                    best = (cst, c, s)
        if best[1] is None or (cur - best[0]) < min_gain * cur or (cur - best[0]) < 0.08:
            break
        settings[best[1]] = best[2]; cur = best[0]
    for c in [c for c in CONDUITS if settings[c] < 0.999]:        # local refinement
        for s in np.clip([settings[c] - 0.1, settings[c] - 0.05, settings[c] + 0.05, settings[c] + 0.1], 0.05, 1.0):
            st = dict(settings); st[c] = float(s)
            cst = _cost(w, sim(st), t_now)
            if cst < cur:
                settings, cur = st, cst
    # heuristic localisation confidence (softmax over best cost per conduit)
    conf = {}
    if first_round:
        v = np.array([first_round[c] for c in CONDUITS if c in first_round])
        p = np.exp(-(v - v.min()) / (0.05 * v.min() + 1e-6)); p /= p.sum()
        conf = dict(zip([c for c in CONDUITS if c in first_round], p.round(3)))
    return {"settings": {c: round(float(s), 3) for c, s in settings.items()},
            "cost": round(cur, 3), "cost_healthy": round(base, 3), "confidence": conf}


def dhi_table(w, t_now, est, expected=None):
    """Drain Health Index per conduit segment (100 = healthy).

    Sensor-health fix in NEXT: a sensor that stops reporting must not be
    assigned a numeric zero/NaN DHI and incorrectly classified as a pipe fault.
    Return a null DHI and an explicit Sensor unavailable state when data are
    missing for more than ten minutes.
    """
    w = w[w.t_min <= t_now].set_index("t_min")
    expected = expected if expected is not None else expected_response(w.reset_index())
    e = expected.set_index("t_min")
    rows = []
    for c in CONDUITS:
        n = UPSTREAM[c]
        ds = w["d_" + n].rolling(3, min_periods=1).median().dropna()
        qs = w["q_" + c].rolling(3, min_periods=1).median().dropna()
        eff = float(est["settings"].get(c, 1.0))
        if ds.empty or qs.empty or t_now - ds.index[-1] > 10 or t_now - qs.index[-1] > 10:
            rows.append({"conduit": c, "node": n, "eff_capacity": eff,
                         "util": None, "rise": None, "flow_deficit": None,
                         "DHI": None, "state": "Sensor unavailable"})
            continue
        d = float(ds.iloc[-1])
        older = ds[ds.index <= t_now - 5]
        d5 = float(older.iloc[-1]) if not older.empty else float(ds.iloc[0])
        q = float(qs.iloc[-1])
        qe_s = e["q_" + c].reindex(w.index).ffill().dropna()
        de_s = e["d_" + n].reindex(w.index).ffill().dropna()
        if qe_s.empty or de_s.empty:
            rows.append({"conduit": c, "node": n, "eff_capacity": eff,
                         "util": None, "rise": None, "flow_deficit": None,
                         "DHI": None, "state": "Model unavailable"})
            continue
        qe, de = float(qe_s.iloc[-1]), float(de_s.iloc[-1])
        util = float(np.clip(d / MAX_DEPTH, 0, 1))
        rise = float(np.clip((d - d5) / 0.5, 0, 1))
        fdef = float(np.clip(1 - q / qe, 0, 1)) if qe > 0.05 else 0.0
        dev = float(np.clip(abs(d - de), 0, 1))
        score = float(np.clip(100 * (1 - (0.5 * (1 - eff) + 0.2 * util + 0.1 * rise + 0.1 * fdef + 0.1 * dev)), 0, 100))
        state = "Healthy" if score >= 75 else "Degraded" if score >= 50 else "Critical" if score >= 25 else "Severe"
        rows.append({"conduit": c, "node": n, "eff_capacity": eff, "util": round(util, 2),
                     "rise": round(rise, 2), "flow_deficit": round(fdef, 2),
                     "DHI": round(score, 1), "state": state})
    return pd.DataFrame(rows)


DEFAULT_DELAYS = {"clear": 8, "bypass": 3, "pump": 5}      # response times in minutes


def scenario_actions(est, t_now, delays=None, clear_to=1.0):
    d = {**DEFAULT_DELAYS, **(delays or {})}
    blocked = [c for c, s in est["settings"].items() if s < 0.999]
    clear = [(t_now + d["clear"], GATE[c], clear_to) for c in blocked]
    byp = [(t_now + d["bypass"], "OBYP", 1.0)]
    pump = [(t_now + d["pump"], "PUMP", 1.0)]
    return {"Baseline (no action)": [],
            "Clear blockage": clear,
            "Open bypass pipe": byp,
            "Temporary pump": pump,
            "Pump + bypass": byp + pump}


def simulate_scenarios(est, rain_full, t_now, delays=None):
    """rain_full: hyetograph = observed rain up to t_now + forecast after t_now."""
    base = _actions(est["settings"])
    out = {}
    for name, acts in scenario_actions(est, t_now, delays).items():
        df = run_sim(rain_full, base + acts)
        m = summarise(df, t_from=t_now)
        if m["time_to_flood_min"] is not None:
            m["time_to_flood_min"] -= t_now
        out[name] = {"df": df, "metrics": m, "actions": acts}
    b = out["Baseline (no action)"]["metrics"]["flood_volume_m3"]
    for v in out.values():
        v["metrics"]["flood_reduction_pct"] = round(100 * (1 - v["metrics"]["flood_volume_m3"] / b), 1) if b > 0 else 0.0
    return out


def mixed_rain(w, t_now, future_true, factor=1.0):
    """Observed rain until t_now, forecast (true future * factor) afterwards."""
    obs = dict(rain_from_frame(w, t_now))
    fut = dict(future_true)
    return [(t, obs[t] if t <= t_now else round(fut[t] * factor, 2)) for t in sorted(obs)]


def prediction_error(pred_df, w_obs, t_from, t_to):
    p = pred_df.set_index("t_min"); o = w_obs.set_index("t_min")
    idx = [t for t in o.index if t_from <= t <= t_to and t in p.index]
    res = {}
    for n in NODES:
        x = (o.loc[idx, "d_" + n] - p.loc[idx, "d_" + n]).dropna()
        res["d_" + n] = float(np.sqrt((x ** 2).mean())) if len(x) else np.nan
    dm = np.nanmean([res["d_" + n] for n in NODES])
    return {"rmse_depth_m": round(float(dm), 4), "per_node": {k: round(v, 4) for k, v in res.items()}}


def closed_loop_update(w_all, t_now, t_end, est, scenario, rain_obs_full):
    """
    After an intervention: (1) measure prediction error of the twin's forecast,
    (2) correct the twin state. For 'Clear blockage' the unknown is how well the crew
    actually cleared the conduit (fit 'clearing effectiveness'); for other scenarios
    the blockage settings are re-estimated from all data to date.
    """
    acts = scenario["actions"]
    pred = scenario["df"]
    err_before = prediction_error(pred, w_all, t_now + 1, t_end)
    w = w_all[w_all.t_min <= t_end]
    rain = rain_from_frame(w, t_end)
    base = _actions(est["settings"])
    new_est = dict(est); new_est["settings"] = dict(est["settings"])
    if acts and acts[0][1].startswith("O") and acts[0][1] != "OBYP":
        t_act = acts[0][0]
        best = (1e9, 1.0)
        for eff in [1.0, 0.95, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4]:
            a2 = base + [(t_act, g, eff) for (_, g, _) in acts]
            c = _cost(w[w.t_min >= t_act - 5], run_sim(rain, a2, until_min=t_end), t_end, recent=999)
            if c < best[0]:
                best = (c, eff)
        eff = best[1]
        for (_, g, _) in acts:
            cond = "C" + g[1:]
            new_est["settings"][cond] = eff
        new_acts = base + [(t_act, g, eff) for (_, g, _) in acts]
        info = {"fitted_clearing_effectiveness": eff}
    else:
        upd = estimate_blockage(w, t_end, extra_actions=acts)
        new_est["settings"] = upd["settings"]
        new_acts = _actions(upd["settings"], acts)
        info = {}
    rain_post = [(t, v) for t, v in rain]
    new_pred = run_sim(rain_post, new_acts, until_min=t_end)
    err_after = prediction_error(new_pred, w_all, t_now + 1, t_end)
    return {"error_before": err_before, "error_after": err_after, "updated_estimate": new_est,
            "new_pred": new_pred, **info}
