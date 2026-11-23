"""
swmm_model.py - The "physical drainage network" of the software-only project.

A small SWMM network is generated as an .inp file and driven with PySWMM.
Blockages are modelled with gated orifices placed at the inlet of every
conduit: orifice setting 1.0 = fully open, 0.4 = 60 % blocked. Because PySWMM
can change an orifice setting while the simulation runs, blockages can build
up gradually and be cleared mid-storm (this is what makes the closed loop
"intervention -> re-observe" possible without hotstart files).

Topology (flow direction ->):
    J1 -C1-> J2 -C2-> J3 -C3-> J4 -C4-> J5 -C5-> OUT1
                      J6 -C6-> J3        J7 -C7-> J4
    Mitigation assets (OFF by default):
      * BYP : gated bypass pipe  J3 -> J5   (alternate routing)
      * PUMP: temporary pump     J3 -> OUT2 (pumping, 0.15-0.5 m3/s)
"""
import os, tempfile, uuid
import numpy as np
import pandas as pd
from pyswmm import Simulation, Nodes, Links, RainGages

SIM_MIN = 240            # simulated minutes per event
CONDUITS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
NODES = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
GATE = {c: "O" + c[1:] for c in CONDUITS}        # blockage gate per conduit
UPSTREAM = {"C1": "J1", "C2": "J2", "C3": "J3", "C4": "J4", "C5": "J5", "C6": "J6", "C7": "J7"}
DOWNSTREAM = {"C1": "J2", "C2": "J3", "C3": "J4", "C4": "J5", "C5": "OUT1", "C6": "J3", "C7": "J4"}
# first sensor-equipped node downstream of each conduit's outlet (used for DHI)
INVERT = {"J1": 100.0, "J2": 99.0, "J3": 98.0, "J4": 97.0, "J5": 96.0, "J6": 98.3, "J7": 97.3}
DIAM = {"C1": 0.6, "C2": 0.8, "C3": 1.0, "C4": 1.2, "C5": 1.2, "C6": 0.6, "C7": 0.6}
MAX_DEPTH = 2.0
# lon/lat positions near Pune for the dashboard map
GEO = {"J1": (73.8540, 18.4640), "J2": (73.8555, 18.4625), "J3": (73.8570, 18.4610),
       "J4": (73.8585, 18.4595), "J5": (73.8600, 18.4580), "OUT1": (73.8615, 18.4568),
       "J6": (73.8548, 18.4600), "J7": (73.8600, 18.4612), "OUT2": (73.8578, 18.4601)}
# (area ha, outlet)
CATCH = {"S1": (2.0, "J1"), "S2": (2.5, "J2"), "S3": (3.0, "J3"), "S4": (2.0, "J6"), "S5": (2.0, "J7")}


def hyetograph(peak_mmh, duration_min, onset_min=10, step=5, total=SIM_MIN):
    """Bell-shaped design storm -> list of (minute, intensity mm/h)."""
    mu = onset_min + duration_min / 2
    sig = duration_min / 5
    out = []
    for t in range(0, total + 1, step):
        v = peak_mmh * np.exp(-0.5 * ((t - mu) / sig) ** 2) if onset_min <= t <= onset_min + duration_min else 0.0
        out.append((t, round(float(v), 2)))
    return out


def build_inp(rain, path):
    L = []
    a = L.append
    h = SIM_MIN // 60
    a("[TITLE]\nStormTwin demo network\n")
    a(f"""[OPTIONS]
FLOW_UNITS CMS
INFILTRATION HORTON
FLOW_ROUTING DYNWAVE
LINK_OFFSETS DEPTH
START_DATE 01/01/2026
START_TIME 00:00:00
REPORT_START_DATE 01/01/2026
REPORT_START_TIME 00:00:00
END_DATE 01/01/2026
END_TIME {h:02d}:00:00
REPORT_STEP 00:01:00
WET_STEP 00:01:00
DRY_STEP 00:05:00
ROUTING_STEP 00:00:05
ALLOW_PONDING NO
MIN_SURFAREA 1.5
VARIABLE_STEP 0.75
""")
    step = int(rain[1][0] - rain[0][0])
    a(f"[RAINGAGES]\nRG1 INTENSITY 0:{step:02d} 1.0 TIMESERIES RAIN\n")
    a("[TIMESERIES]")
    for t, v in rain:
        a(f"RAIN {t // 60}:{t % 60:02d} {v}")
    a("")
    a("[SUBCATCHMENTS]")
    for s, (ha, out) in CATCH.items():
        a(f"{s} RG1 {out} {ha} 70 {ha * 100000 ** 0.5 / 3:.0f} 0.8 0")
    a("\n[SUBAREAS]")
    for s in CATCH:
        a(f"{s} 0.013 0.2 1.5 5 25 OUTLET")
    a("\n[INFILTRATION]")
    for s in CATCH:
        a(f"{s} 40 8 4 7 0")
    a("\n[JUNCTIONS]")
    for n, z in INVERT.items():
        a(f"{n} {z} {MAX_DEPTH} 0 0 0")
    for c in CONDUITS:                                  # inlet node behind each blockage gate
        a(f"B{c[1:]} {INVERT[UPSTREAM[c]]} 3.0 0 0 0")
    a("BPN 97.2 3.0 0 0 0")
    a("\n[OUTFALLS]\nOUT1 95.0 FREE NO\nOUT2 95.5 FREE NO")
    a("\n[CONDUITS]")
    for c in CONDUITS:
        ln = 150 if c in ("C6", "C7") else 200
        a(f"{c} B{c[1:]} {DOWNSTREAM[c]} {ln} 0.013 0 0")
    a("BYP BPN J5 400 0.013 0 0")
    a("\n[ORIFICES]")
    for c in CONDUITS:
        a(f"{GATE[c]} {UPSTREAM[c]} B{c[1:]} SIDE 0 0.8 YES 0")
    a("OBYP J3 BPN SIDE 0 0.8 YES 0")
    a("\n[PUMPS]\nPUMP J3 OUT2 PC1 ON 0 0")
    a("\n[XSECTIONS]")
    for c in CONDUITS:
        a(f"{c} CIRCULAR {DIAM[c]} 0 0 0 1")
        a(f"{GATE[c]} CIRCULAR {DIAM[c]} 0 0 0")
    a("BYP CIRCULAR 0.6 0 0 0 1\nOBYP CIRCULAR 0.6 0 0 0")
    a("\n[CURVES]\nPC1 Pump4 0.2 0.15\nPC1 1.0 0.40\nPC1 2.0 0.50")
    a("\n[COORDINATES]")
    for n, (x, y) in GEO.items():
        a(f"{n} {x} {y}")
    for c in CONDUITS:
        a(f"B{c[1:]} {GEO[UPSTREAM[c]][0]} {GEO[UPSTREAM[c]][1]}")
    a(f"BPN {GEO['J4'][0]} {GEO['J4'][1]}")
    a("\n[SYMBOLS]\nRG1 73.85 18.47")
    open(path, "w").write("\n".join(L) + "\n")


def ramp(link_gate, t0, t1, final, n=6):
    """Gradual blockage: gate setting goes 1.0 -> final between t0 and t1 (minutes)."""
    ts = np.linspace(t0, t1, n)
    vs = np.linspace(1.0, final, n)
    return [(float(t), link_gate, float(v)) for t, v in zip(ts, vs)]


def run_sim(rain, actions=(), until_min=SIM_MIN, workdir=None):
    """
    rain    : hyetograph list
    actions : iterable of (t_min, link_id, setting) applied during the run
              (gate setting 0..1, 'PUMP' on/off 0..1, 'OBYP' bypass gate 0..1)
    returns : DataFrame, one row per minute
    """
    workdir = workdir or tempfile.gettempdir()
    inp = os.path.join(workdir, f"st_{uuid.uuid4().hex[:10]}.inp")
    build_inp(rain, inp)
    acts = sorted(actions, key=lambda a: a[0])
    # bypass and pump start switched off unless an action says otherwise
    acts = [(-1, "OBYP", 0.0), (-1, "PUMP", 0.0)] + acts
    rows, ai = [], 0
    try:
        with Simulation(inp) as sim:
            nodes, links, rg = Nodes(sim), Links(sim), RainGages(sim)
            sim.step_advance(60)
            for _ in sim:
                t = sim.current_time
                tm = (t - sim.start_time).total_seconds() / 60
                while ai < len(acts) and acts[ai][0] <= tm + 1e-6:
                    links[acts[ai][1]].target_setting = acts[ai][2]
                    ai += 1
                r = {"t_min": round(tm), "rain": rg["RG1"].rainfall}
                for n in NODES:
                    r["d_" + n] = nodes[n].depth
                    r["fl_" + n] = nodes[n].flooding
                for c in CONDUITS:
                    r["q_" + c] = links[c].flow
                r["q_PUMP"] = links["PUMP"].flow
                r["q_BYP"] = links["BYP"].flow
                rows.append(r)
                if tm >= until_min:
                    break
    finally:
        if os.path.exists(inp):
            os.remove(inp)
    return pd.DataFrame(rows)


def summarise(df, t_from=0):
    """Scenario metrics used by the what-if engine."""
    d = df[df.t_min >= t_from]
    fl_cols = [c for c in d.columns if c.startswith("fl_")]
    flood_vol = float((d[fl_cols].sum(axis=1) * 60).sum())           # m3
    flooded = [c[3:] for c in fl_cols if d[c].max() > 1e-4]
    d_cols = [c for c in d.columns if c.startswith("d_")]
    first = d[(d[fl_cols] > 1e-4).any(axis=1)].t_min
    return {"peak_depth_m": float(d[d_cols].max().max()),
            "flood_volume_m3": round(flood_vol, 1),
            "flooded_nodes": flooded,
            "time_to_flood_min": float(first.min()) if len(first) else None}
