"""
gateway.py - Edge gateway (replaces Raspberry Pi) + time-series store (replaces InfluxDB).

Subscribes to stormwater/+/+/telemetry, then
  1. validates ranges (physically impossible -> rejected)
  2. detects spikes and stuck sensors (-> suspect, so a sensor fault is not read as a hydraulic fault)
  3. buffers while the uplink is down, flushes when it returns
  4. stores to SQLite (swap for InfluxDB/Timestream in production)
"""
import sqlite3, collections
import numpy as np, pandas as pd

LIMITS = {"water_level": (0.0, 2.6), "flow_rate": (0.0, 8.0), "rainfall": (0.0, 300.0)}
MAX_JUMP = {"water_level": 0.9, "flow_rate": 3.0}          # per-minute plausible change
STUCK_N = 12


class Gateway:
    def __init__(self, db_path="stormtwin.db"):
        self.db_path = db_path
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.execute("""CREATE TABLE IF NOT EXISTS readings(
            run_id TEXT, ts TEXT, t_min INTEGER, node_id TEXT, sensor_type TEXT,
            value REAL, unit TEXT, quality TEXT, battery REAL, rssi INTEGER)""")
        self.con.execute("CREATE INDEX IF NOT EXISTS ix ON readings(run_id, node_id, t_min)")
        self.buffer = collections.deque()
        self.uplink_up = True
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=STUCK_N))
        self.stats = collections.Counter()

    def clear_run(self, run_id):
        self.con.execute("DELETE FROM readings WHERE run_id=?", (run_id,)); self.con.commit()

    def on_message(self, topic, m):
        self.stats["received"] += 1
        stype, v, nid = m["sensor_type"], m["value"], m["node_id"]
        q = "ok"
        lo, hi = LIMITS[stype]
        h = self.hist[nid]
        if not (lo <= v <= hi):
            q = "rejected"
        elif stype in MAX_JUMP and h and abs(v - h[-1]) > MAX_JUMP[stype]:
            q = "suspect"                                   # spike
        h.append(v)
        if q == "ok" and stype == "water_level" and len(h) == STUCK_N and len(set(h)) == 1 and v > 0.05:
            q = "suspect"                                   # flat-lined sensor
        self.stats[q] += 1
        row = (m["run_id"], m["timestamp"], m["t_min"], nid, stype, v, m["unit"], q,
               m["battery"], m["rssi"])
        self.buffer.append(row)
        if self.uplink_up:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        rows = list(self.buffer); self.buffer.clear()
        self.con.executemany("INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self.con.commit()
        self.stats["stored"] += len(rows)

    def set_uplink(self, up):
        self.uplink_up = up
        if up:
            self.flush()

    def connect(self, bus):
        bus.subscribe("stormwater/+/+/telemetry", self.on_message)


def load_series(db_path, run_id, until_min=None, only_ok=True):
    """Wide per-minute table using the same column names as the SWMM ground truth."""
    con = sqlite3.connect(db_path)
    try:
        return frame_from_con(con, run_id, until_min, only_ok)
    finally:
        con.close()


def frame_from_con(con, run_id, until_min=None, only_ok=True):
    q = "SELECT t_min,node_id,value,quality FROM readings WHERE run_id=?"
    p = [run_id]
    if until_min is not None:
        q += " AND t_min<=?"; p.append(until_min)
    d = pd.read_sql(q, con, params=p)
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    quality = d.pivot_table(index="t_min", columns="node_id", values="quality", aggfunc="last")
    if only_ok:
        d = d[d.quality == "ok"]
    w = d.pivot_table(index="t_min", columns="node_id", values="value", aggfunc="mean")
    ren = {}
    for c in w.columns:
        kind, key = c.split("-")
        ren[c] = {"LVL": "d_", "FLW": "q_", "RAIN": "rain"}[kind] + ("" if kind == "RAIN" else key)
    w = w.rename(columns=ren)
    w = w.reindex(range(int(w.index.min()), int(w.index.max()) + 1))
    w = w.interpolate(limit=4, limit_direction="both")      # bridge short packet-loss gaps
    w = w.reset_index().rename(columns={"index": "t_min"})
    return w, quality
