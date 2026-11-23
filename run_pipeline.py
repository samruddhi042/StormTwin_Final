"""
run_pipeline.py - one command to (re)build everything and print the storyline.
   python run_pipeline.py            # train + demo
   python run_pipeline.py --events 60  # faster training
   MQTT_HOST=localhost python run_pipeline.py   # use a real Mosquitto broker
"""
import argparse, json, os, time
import numpy as np
import demo, ml, twin
from swmm_model import summarise


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--events", type=int, default=160)
    a = ap.parse_args()
    t0 = time.time()
    if not os.path.exists("models.joblib"):
        print(f"[1/3] Generating {a.events} SWMM events -> sensors -> gateway -> features ...")
        ds = ml.make_dataset(a.events)
        rep = ml.train(ds)
        json.dump(rep, open("metrics.json", "w"), indent=2)
        print(json.dumps(rep, indent=2))
    else:
        print("[1/3] models.joblib exists (delete it to retrain)")
    print("[2/3] Building demo run through the IoT pipeline ...")
    truth, stats = demo.build_demo_db(mqtt_host=os.environ.get("MQTT_HOST"))
    print("      gateway stats:", stats); print("      truth:", summarise(truth))
    w, q = demo.load_demo()
    print("[3/3] Twin storyline")
    exp = twin.expected_response(w)
    feats = ml.predict_risk(ml.build_features(w, exp))
    for t in range(40, 80, 5):
        wt = w[w.t_min <= t]
        r = feats[feats.t_min == t].risk.max()
        est = twin.estimate_blockage(wt, t)
        blocked = {c: s for c, s in est["settings"].items() if s < 1}
        print(f"  t={t:3d}  ML max risk={r:.2f}  twin blockage={blocked}")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
