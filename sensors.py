"""
sensors.py - Virtual IoT sensor nodes (replace the ESP32/STM32 hardware).

Takes the "ground truth" SWMM output and turns it into imperfect telemetry:
  * Gaussian noise, ADC-like quantisation
  * tipping-bucket quantisation for rain (0.2 mm per tip)
  * random packet loss (LoRa/NB-IoT style)
  * occasional spikes, and optional "stuck sensor" faults
  * battery drain and RSSI
Each message follows the telemetry packet in the patent draft:
  node_id, timestamp, sensor_type, value, unit, battery, rssi, status
"""
import datetime as dt
import numpy as np
from swmm_model import NODES, CONDUITS

T0 = dt.datetime(2026, 1, 1, 0, 0, 0)
ZONE = "zoneA"


def topic_for(node_id):
    return f"stormwater/{ZONE}/{node_id}/telemetry"


def sensorize(df, seed=0, loss=0.02, spike_p=0.002, stuck=None, depth_sigma=0.01,
              flow_noise=0.03, run_id="run"):
    """
    df    : SWMM ground-truth DataFrame
    stuck : optional {"node": "J2", "from_min": 60} -> level sensor freezes
    returns list[dict] telemetry messages in time order
    """
    rng = np.random.default_rng(seed)
    msgs, bat, bucket = [], {}, 0.0
    last_val = {}
    for _, row in df.iterrows():
        t = int(row.t_min)
        ts = (T0 + dt.timedelta(minutes=t)).isoformat()
        chans = [(f"LVL-{n}", "water_level", "m", row["d_" + n]) for n in NODES]
        chans += [(f"FLW-{c}", "flow_rate", "m3/s", row["q_" + c]) for c in CONDUITS]
        chans += [("RAIN-1", "rainfall", "mm/h", row["rain"])]
        for nid, stype, unit, truth in chans:
            if rng.random() < loss:
                continue                                   # packet lost
            if stype == "water_level":
                v = truth + rng.normal(0, depth_sigma)
                v = round(max(v, 0.0), 3)
            elif stype == "flow_rate":
                v = truth * (1 + rng.normal(0, flow_noise)) + rng.normal(0, 0.003)
                v = round(max(v, 0.0), 4)
            else:                                           # tipping bucket, 0.2 mm/tip
                bucket = bucket + truth / 60.0              # mm collected this minute
                tips = int(bucket // 0.2)                   # bucket tips every 0.2 mm
                bucket -= tips * 0.2
                v = round(tips * 0.2 * 60, 1)               # reported as mm/h
            if rng.random() < spike_p and stype != "rainfall":
                v = round(v * rng.choice([5.0, -1.0]) + 1.5, 3)   # electrical spike
            if stuck and nid == f"LVL-{stuck['node']}" and t >= stuck["from_min"]:
                v = last_val.setdefault(nid, v) if nid in last_val else v
                last_val[nid] = v
            else:
                last_val[nid] = v
            bat[nid] = bat.get(nid, 100.0) - 0.002
            msgs.append({"run_id": run_id, "node_id": nid, "timestamp": ts, "t_min": t,
                         "sensor_type": stype, "value": v, "unit": unit,
                         "battery": round(bat[nid], 2),
                         "rssi": int(rng.normal(-95, 4)), "device_status": "OK"})
    return msgs


def publish_all(bus, msgs, on_tick=None):
    """Publish telemetry on MQTT topics. on_tick(t_min) is called when the minute changes."""
    cur = None
    for m in msgs:
        if on_tick and m["t_min"] != cur:
            cur = m["t_min"]; on_tick(cur)
        bus.publish(topic_for(m["node_id"]), m)
