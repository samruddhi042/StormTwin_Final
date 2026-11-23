"""
StormTwin dashboard (Streamlit).   streamlit run app.py
Replays the demo storm through the full pipeline; move the time slider to 'be' at that moment.
"""
import os, json
import numpy as np, pandas as pd
import plotly.graph_objects as go
import streamlit as st
import demo, ml, twin
from swmm_model import CONDUITS, NODES, UPSTREAM, DOWNSTREAM, GEO, GATE, MAX_DEPTH, summarise
from sensors import sensorize

st.set_page_config(page_title="StormTwin", page_icon="🌧️", layout="wide")
MAP = getattr(go, 'Scattermap', None) or go.Scattermapbox
MAPKEY = 'map' if hasattr(go, 'Scattermap') else 'mapbox'
STATE_COL = {"Healthy": "#2e9e5b", "Degraded": "#e0a800", "Critical": "#e8590c", "Severe": "#c92a2a"}


@st.cache_resource(show_spinner="Building demo data through the IoT pipeline…")
def boot():
    if not os.path.exists("models.joblib"):
        st.error("models.joblib missing - run `python run_pipeline.py` first."); st.stop()
    if not os.path.exists(demo.DB):
        demo.build_demo_db()
    w, q = demo.load_demo()
    exp = twin.expected_response(w)
    feats = ml.predict_risk(ml.build_features(w, exp))
    return w, q, exp, feats, ml.load_models()


@st.cache_data(show_spinner="Synchronising Digital Twin with sensor data…")
def sync(t):
    w, *_ = boot()
    return twin.estimate_blockage(w, t)


@st.cache_data(show_spinner="Running what-if simulations in SWMM…")
def whatif(t, factor, d_clear, d_bypass, d_pump):
    w, *_ = boot()
    est = sync(t)
    rain = twin.mixed_rain(w, t, demo.rain(), factor)
    sc = twin.simulate_scenarios(est, rain, t, {"clear": d_clear, "bypass": d_bypass, "pump": d_pump})
    return sc


w_all, qual, expected, feats, models = boot()
th = models["threshold"]

# ---------------- sidebar ----------------
st.sidebar.title("🌧️ StormTwin")
st.sidebar.caption("Software-only IoT + AI + Digital Twin for urban drains")
t_now = st.sidebar.slider("Current time (min since start of rain event)", 30, 130, 60, step=5)
factor = st.sidebar.slider("Rain forecast accuracy (1.0 = perfect)", 0.7, 1.3, 1.0, 0.05)
st.sidebar.markdown("**Response times (min)**")
d_clear = st.sidebar.slider("Crew clears blockage", 2, 30, 8)
d_bypass = st.sidebar.slider("Open bypass gate", 1, 15, 3)
d_pump = st.sidebar.slider("Deploy pump", 2, 30, 5)

w = w_all[w_all.t_min <= t_now]
est = sync(t_now)
dhi = twin.dhi_table(w, t_now, est, expected)
sc = whatif(t_now, factor, d_clear, d_bypass, d_pump)
base = sc["Baseline (no action)"]["metrics"]
fnow = feats[feats.t_min == t_now]
max_risk = float(fnow.risk.max()) if len(fnow) else 0.0
worst = dhi.sort_values("DHI").iloc[0]
blocked = {c: s for c, s in est["settings"].items() if s < 0.999}

# ---------------- header ----------------
alert = (max_risk > th) or (worst.DHI < 50) or (base["time_to_flood_min"] is not None)
if alert:
    ttf = base["time_to_flood_min"]
    msg = f"⚠️ **Flood risk alert** – predicted overflow at {', '.join(base['flooded_nodes'])}" + \
          (f" in ~{ttf:.0f} min" if ttf is not None else "") + \
          (f". Probable blockage in {', '.join(f'{c} ({(1-s)*100:.0f}% blocked)' for c, s in blocked.items())}." if blocked else "")
    st.error(msg)
elif worst.DHI < 75:
    st.warning("Drain health degraded – monitoring.")
else:
    st.success("All drains healthy.")
k = st.columns(5)
k[0].metric("Rainfall now", f"{w.rain.iloc[-5:].mean():.0f} mm/h")
k[1].metric("Max AI flood risk (30 min)", f"{max_risk:.2f}", f"alarm ≥ {th}", delta_color="off")
k[2].metric("Worst Drain Health Index", f"{worst.DHI:.0f}", f"{worst.conduit} – {worst.state}", delta_color="off")
k[3].metric("Twin: time to overflow", "none" if base["time_to_flood_min"] is None else f"{base['time_to_flood_min']:.0f} min")
k[4].metric("Twin: overflow volume", f"{base['flood_volume_m3']:.0f} m³")

tabs = st.tabs(["🗺️ Live map", "📡 Sensors", "🧠 AI & Twin state", "🔀 What-if", "🔁 Closed loop", "ℹ️ About"])

# ---------------- map ----------------
with tabs[0]:
    fig = go.Figure()
    for _, r in dhi.iterrows():
        a, b = GEO[UPSTREAM[r.conduit]], GEO[DOWNSTREAM[r.conduit]]
        fig.add_trace(MAP(lon=[a[0], b[0]], lat=[a[1], b[1]], mode="lines",
                      line=dict(width=6, color=STATE_COL[r.state]), hoverinfo="text",
                      text=f"{r.conduit}: DHI {r.DHI} ({r.state})<br>effective capacity {r.eff_capacity:.0%}", showlegend=False))
    pts = []
    for n in NODES + ["OUT1"]:
        rk = float(fnow[fnow.node == n].risk.iloc[0]) if n in NODES and len(fnow[fnow.node == n]) else 0.0
        dep = float(w["d_" + n].dropna().iloc[-1]) if n in NODES else 0.0
        pts.append((n, GEO[n][0], GEO[n][1], rk, dep))
    p = pd.DataFrame(pts, columns=["n", "lon", "lat", "risk", "depth"])
    fig.add_trace(MAP(lon=p.lon, lat=p.lat, mode="markers+text", text=p.n, textposition="top right",
                  marker=dict(size=16, color=p.risk, colorscale=[[0, "#2e9e5b"], [0.5, "#e0a800"], [1, "#c92a2a"]],
                              cmin=0, cmax=1, colorbar=dict(title="AI risk", thickness=12)),
                  hovertext=[f"{r.n}: depth {r.depth:.2f} m, risk {r.risk:.2f}" for r in p.itertuples()], hoverinfo="text", showlegend=False))
    fig.update_layout(**{MAPKEY: dict(style="open-street-map", center=dict(lon=73.857, lat=18.461), zoom=14.6)},
                      height=560, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Line colour = Drain Health Index of the conduit; node colour = AI probability of flooding in the next 30 min.")

# ---------------- sensors ----------------
with tabs[1]:
    c1, c2 = st.columns(2)
    f1 = go.Figure()
    for n in NODES:
        f1.add_trace(go.Scatter(x=w.t_min, y=w["d_" + n], name=n, mode="lines"))
    f1.add_hline(y=MAX_DEPTH, line_dash="dot", annotation_text="ground level (flooding)")
    f1.update_layout(title="Water level (cleaned, m)", height=340, xaxis_title="min", margin=dict(t=40))
    c1.plotly_chart(f1, width="stretch")
    f2 = go.Figure()
    for c in CONDUITS:
        f2.add_trace(go.Scatter(x=w.t_min, y=w["q_" + c], name=c, mode="lines"))
    f2.update_layout(title="Flow (cleaned, m³/s)", height=340, xaxis_title="min", margin=dict(t=40))
    c2.plotly_chart(f2, width="stretch")
    f3 = go.Figure(go.Bar(x=w.t_min, y=w.rain, name="rain")); f3.update_layout(title="Tipping-bucket rain (mm/h)", height=220, margin=dict(t=40))
    st.plotly_chart(f3, width="stretch")
    qq = qual[qual.index <= t_now]
    health = pd.DataFrame({"suspect/flagged readings": (qq == "suspect").sum(),
                           "rejected": (qq == "rejected").sum(),
                           "missing minutes (packet loss)": qq.isna().sum()})
    health["status"] = np.where(health["suspect/flagged readings"] > 10, "⚠️ sensor fault suspected", "ok")
    st.subheader("Sensor health (gateway validation)")
    flagged = health[health.status != "ok"]
    st.dataframe(flagged if len(flagged) else pd.DataFrame({"result": ["all sensors passing validation"]}), width="stretch")
    if (health.status != "ok").any():
        st.info("Flagged sensors are excluded from AI features and twin calibration, so a frozen level sensor is not mistaken for a hydraulic failure.")
    with st.expander("All channels"):
        st.dataframe(health, width="stretch")

# ---------------- AI & twin ----------------
with tabs[2]:
    c1, c2 = st.columns([3, 2])
    ft = feats[feats.t_min <= t_now]
    f = go.Figure()
    for n in NODES:
        g = ft[ft.node == n]
        f.add_trace(go.Scatter(x=g.t_min, y=g.risk, name=n, mode="lines"))
    f.add_hline(y=th, line_dash="dash", annotation_text="alarm threshold")
    f.update_layout(title="AI: probability of flooding within 30 min", yaxis_range=[0, 1.02], height=340, margin=dict(t=40), xaxis_title="min")
    c1.plotly_chart(f, width="stretch")
    c2.subheader("Drain Health Index")
    c2.dataframe(dhi[["conduit", "DHI", "state", "eff_capacity", "util", "flow_deficit"]], width="stretch", hide_index=True)
    st.subheader("Digital Twin state estimate")
    if blocked:
        conf = est["confidence"]
        for c, s in blocked.items():
            st.write(f"**{c}** effective opening ≈ **{s:.0%}** (≈ {(1-s):.0%} blocked). "
                     f"Localisation confidence ≈ {conf.get(c, 0):.0%}. "
                     f"Fit error fell from {est['cost_healthy']:.2f} (healthy-network model) to {est['cost']:.2f}.")
    else:
        st.write("No blockage detected: the healthy-network model explains the sensor data.")
    node_sel = st.selectbox("Compare sensor vs healthy-model expectation at node", NODES, index=2)
    f = go.Figure()
    f.add_trace(go.Scatter(x=w.t_min, y=w["d_" + node_sel], name="observed (sensor)"))
    e = expected[expected.t_min <= t_now]
    f.add_trace(go.Scatter(x=e.t_min, y=e["d_" + node_sel], name="expected if drain were healthy", line=dict(dash="dash")))
    f.update_layout(height=300, margin=dict(t=20), yaxis_title="depth (m)", xaxis_title="min")
    st.plotly_chart(f, width="stretch")
    st.caption("The gap between the two curves is the raw signal behind the indirect blockage estimate.")
    with st.expander("Model quality (held-out synthetic storms)"):
        st.json(models["report"])

# ---------------- what-if ----------------
with tabs[3]:
    rows = []
    for name, v in sc.items():
        m = v["metrics"]
        rows.append({"Scenario": name, "Peak depth (m)": round(m["peak_depth_m"], 2),
                     "Overflow volume (m³)": m["flood_volume_m3"], "Flood reduction vs baseline": f"{m['flood_reduction_pct']:.0f}%",
                     "Flooded nodes": ", ".join(m["flooded_nodes"]) or "–",
                     "Time to overflow (min)": "–" if m["time_to_flood_min"] is None else str(round(m["time_to_flood_min"])),
                     "Action at t+": ", ".join(f"{a[0]-t_now:.0f} min" for a in v["actions"][:1]) or "–"})
    tbl = pd.DataFrame(rows)
    st.dataframe(tbl, width="stretch", hide_index=True)
    best = min(sc.items(), key=lambda kv: (kv[1]["metrics"]["flood_volume_m3"], kv[1]["metrics"]["peak_depth_m"]))
    if base["flood_volume_m3"] > 0:
        st.success(f"Best simulated option: **{best[0]}** – overflow {best[1]['metrics']['flood_volume_m3']:.0f} m³ "
                   f"({best[1]['metrics']['flood_reduction_pct']:.0f}% less than doing nothing). Final decision stays with the operator.")
    node_w = (base["flooded_nodes"] or ["J3"])[0]
    f = go.Figure()
    for name, v in sc.items():
        d = v["df"]; d = d[d.t_min >= t_now - 10]
        f.add_trace(go.Scatter(x=d.t_min, y=d["d_" + node_w], name=name))
    f.add_hline(y=MAX_DEPTH, line_dash="dot", annotation_text="overflow level")
    f.add_vline(x=t_now, line_dash="dash", annotation_text="now")
    f.update_layout(title=f"Predicted water level at {node_w} under each intervention", height=380, xaxis_title="min", yaxis_title="m")
    st.plotly_chart(f, width="stretch")
    st.caption("Scenarios are simulated on a copy of the twin – the physical network is not touched. The rain forecast is the true future rain × the 'forecast accuracy' factor.")

# ---------------- closed loop ----------------
with tabs[4]:
    st.write("Pick the intervention the operator carries out. The *real* network (hidden from the twin) executes it, new sensor data arrive, "
             "and the twin compares its forecast with what happened and corrects itself. In this demo the crew only clears 85 % of the blockage.")
    choice = st.selectbox("Intervention executed", list(sc.keys()), index=1)
    horizon = st.slider("Observe for (min after intervention decision)", 15, 60, 40, 5)
    if st.button("▶ Execute and observe", type="primary"):
        with st.spinner("Real network responds, twin updates…"):
            chosen = sc[choice]
            truth_df = demo.truth(chosen["actions"])
            from ml import sensed_frame
            w_post = sensed_frame(truth_df, seed=99)
            t_end = min(t_now + horizon, 235)
            res = twin.closed_loop_update(w_post, t_now, t_end, est, chosen, None)
        st.session_state["cl"] = (res, choice, t_end, w_post, truth_df, chosen)
    if "cl" in st.session_state:
        res, ch, t_end, w_post, truth_df, chosen = st.session_state["cl"]
        a, b = res["error_before"]["rmse_depth_m"], res["error_after"]["rmse_depth_m"]
        c = st.columns(3)
        c[0].metric("Forecast error before update (RMSE depth)", f"{a*100:.1f} cm")
        c[1].metric("Error after twin update", f"{b*100:.1f} cm", f"{(b-a)*100:.1f} cm", delta_color="inverse")
        if "fitted_clearing_effectiveness" in res:
            c[2].metric("Clearing effectiveness learned", f"{res['fitted_clearing_effectiveness']:.0%}", "twin assumed 100 %", delta_color="off")
        else:
            nb = {k: v for k, v in res["updated_estimate"]["settings"].items() if v < 0.999}
            c[2].metric("Updated blockage state", ", ".join(f"{k} {v:.0%}" for k, v in nb.items()) or "none")
        node_w = (chosen["metrics"]["flooded_nodes"] or base["flooded_nodes"] or ["J3"])[0]
        f = go.Figure()
        ob = w_post[(w_post.t_min >= t_now - 10) & (w_post.t_min <= t_end)]
        f.add_trace(go.Scatter(x=ob.t_min, y=ob["d_" + node_w], name="observed after intervention", mode="markers"))
        p0 = chosen["df"]; p0 = p0[(p0.t_min >= t_now - 10) & (p0.t_min <= t_end)]
        f.add_trace(go.Scatter(x=p0.t_min, y=p0["d_" + node_w], name="twin forecast (before update)", line=dict(dash="dash")))
        p1 = res["new_pred"]; p1 = p1[(p1.t_min >= t_now - 10) & (p1.t_min <= t_end)]
        f.add_trace(go.Scatter(x=p1.t_min, y=p1["d_" + node_w], name="twin after update"))
        f.add_vline(x=t_now, line_dash="dot", annotation_text="decision")
        f.update_layout(title=f"{ch}: water level at {node_w}", height=380, xaxis_title="min", yaxis_title="m")
        st.plotly_chart(f, width="stretch")
        st.caption("Monitor → Analyse → Predict → Simulate → Recommend → Mitigate → Re-observe → Update.")

# ---------------- about ----------------
with tabs[5]:
    st.markdown("""
| Patent-draft element | In this software build |
|---|---|
| ESP32/STM32 sensor nodes | `sensors.py` – virtual nodes: noise, packet loss, spikes, stuck sensor, battery, RSSI |
| LoRaWAN/NB-IoT/Wi-Fi + MQTT | `bus.py` – real MQTT (paho + Mosquitto) or in-process bus, same topics `stormwater/{zone}/{node}/telemetry` |
| Raspberry Pi edge gateway | `gateway.py` – validation, spike/stuck detection, buffering during uplink loss |
| InfluxDB / Timestream | SQLite (swap-in point is `gateway.py`) |
| AI failure prediction | `ml.py` – Random Forest on sensor features, Isolation Forest anomaly score |
| Indirect blockage estimation + DHI | `twin.py` – fit effective conduit opening to sensor data; DHI from capacity, utilisation, rise rate, flow deficit |
| Hydraulic Digital Twin | EPA SWMM (via PySWMM); blockages are gated orifices |
| Counterfactual scenarios | `twin.simulate_scenarios` – clear, bypass, pump, pump+bypass with response delays |
| Closed loop | `twin.closed_loop_update` |
| Physical drain network | SWMM again, playing the real world (`demo.py`) |
""")
