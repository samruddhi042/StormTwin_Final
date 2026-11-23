"""demo.py - the scripted storyline used by the dashboard and run_pipeline.py"""
import os
from swmm_model import hyetograph, run_sim, ramp, GATE
from sensors import sensorize, publish_all
from gateway import Gateway, load_series
from bus import make_bus

DB = os.environ.get("STORMTWIN_DB", "stormtwin.db")
RUN = "demo"
STORM = dict(peak=50, dur=150, onset=10)
BLOCK = dict(conduit="C3", t0=15, t1=25, final=0.25)      # debris builds up in C3
STUCK = {"node": "J2", "from_min": 90}                    # a level sensor freezes (sensor fault, NOT hydraulic)
CLEAR_EFFECTIVENESS = 0.85                                # crews only clear 85 % -> closed loop must notice


def rain():
    return hyetograph(STORM["peak"], STORM["dur"], STORM["onset"])


def blockage_actions():
    return ramp(GATE[BLOCK["conduit"]], BLOCK["t0"], BLOCK["t1"], BLOCK["final"])


def truth(planned_actions=()):
    """Ground-truth network. planned_actions are the twin's actions, executed 'for real'
    (blockage clearing is imperfect in reality)."""
    real = []
    for (t, link, s) in planned_actions:
        if link.startswith("O") and link != "OBYP":
            s = CLEAR_EFFECTIVENESS
        real.append((t, link, s))
    return run_sim(rain(), blockage_actions() + real)


def build_demo_db(db=DB, mqtt_host=None, seed=7, uplink_outage=(52, 58)):
    """Truth -> virtual sensors -> MQTT (or in-process bus) -> gateway -> SQLite."""
    df = truth()
    msgs = sensorize(df, seed=seed, stuck=STUCK, run_id=RUN)
    gw = Gateway(db); gw.clear_run(RUN)
    bus = make_bus("mqtt", host=mqtt_host) if mqtt_host else make_bus("local")
    gw.connect(bus)
    def tick(t):
        if uplink_outage and t == uplink_outage[0]: gw.set_uplink(False)
        if uplink_outage and t == uplink_outage[1]: gw.set_uplink(True)
    publish_all(bus, msgs, tick)
    if mqtt_host:                       # wait until the broker has delivered the tail of the stream
        import time
        last, quiet = -1, 0
        while quiet < 3:
            time.sleep(0.5)
            quiet = quiet + 1 if gw.stats["received"] == last else 0
            last = gw.stats["received"]
    gw.flush(); bus.close()
    return df, dict(gw.stats)


def load_demo(db=DB):
    return load_series(db, RUN)
