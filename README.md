# StormTwin – software-only IoT + AI Digital Twin for urban stormwater drains

The hardware in the patent draft is replaced by software. **EPA SWMM plays the physical drain network**;
everything else (sensor nodes → MQTT → gateway → database → AI → Digital Twin → what-if → dashboard → closed loop) is real code.

```
SWMM "real world" ──► virtual sensor nodes ──► MQTT ──► gateway (validate/buffer) ──► SQLite
  (demo.py)            (sensors.py)           (bus.py)        (gateway.py)              │
        ▲                                                                              ▼
        │ intervention executed                                   AI risk (ml.py) + Digital Twin (twin.py)
        └────────────────────  Streamlit dashboard (app.py) ◄────  blockage fit, DHI, what-if scenarios
```

## Run it
```bash
pip install -r requirements.txt
python run_pipeline.py            # trains the models (~5 min for 200 storms; use --events 60 for a quick one) and prints the storyline
streamlit run app.py              # dashboard
# optional real broker:  docker compose up -d  &&  MQTT_HOST=localhost python run_pipeline.py
```
Without `MQTT_HOST` an in-process bus with the same topics (`stormwater/zoneA/<node>/telemetry`) is used.

## Demo script (dashboard sidebar → "Current time")
| t (min) | What to show |
|---|---|
| 40–55 | All green. Rain is rising; gateway already flags the frozen level sensor on J2 as *suspect* (sensors tab) – a sensor fault is not treated as a hydraulic fault. |
| **60** | Alert. The twin finds C3 ≈ 72 % blocked and predicts overflow at J3 in ~19 min. **What-if** tab ranks clear / bypass / pump / pump+bypass. |
| 70–80 | Shorten the lead time: fewer options remain, response delays start to matter (sidebar sliders). |
| any | **Closed loop** tab → *Execute*: the hidden real network is only 85 % cleared; the twin sees its forecast was off and learns the 85 %. |
(Real flood in the demo starts at t = 75 min.)

## What was measured (synthetic storms from the same SWMM model – not field data)
* Drain-failure classifier (Random Forest, 30-min horizon): AUC 0.98 on 50 held-out storms; at the alarm threshold chosen on validation storms all 17 flooding storms were warned about, 0 false-alarm storms of 33.
* **Median warning lead time of the classifier alone is only ~3 min** at that strict threshold. The early warning in the demo comes from the **twin**: blockage identified ≈15 min before the first overflow, 0 false blockages on 12 healthy test storms. Lowering the threshold buys lead time at the cost of false alarms – a tunable trade-off worth showing in your report.
* Details: `metrics.json`.

## Files
`swmm_model.py` network + blockage gates + runner · `sensors.py` virtual ESP32 nodes · `bus.py` MQTT/in-process · `gateway.py` edge validation + DB ·
`ml.py` dataset, Random Forest, Isolation Forest · `twin.py` blockage estimation, Drain Health Index, scenarios, closed-loop update · `demo.py` storyline · `app.py` dashboard.

## Limits you should state honestly
* All data are simulated; "accuracy" means agreement with SWMM, not with a real drain.
* Blockage = effective opening of an inlet gate; one fitted factor per conduit, greedy search (max 3 blockages). Not a full data-assimilation scheme (EnKF/Bayesian would be the upgrade).
* One rain gauge for the whole catchment; the what-if rain forecast is the true future rain × a "forecast accuracy" factor.
* Not included: ROS 2, Gazebo/Webots, Unreal. If your course needs ROS 2, add a thin node that republishes the MQTT telemetry on `/stormwater/sensors` and subscribes to risk/DHI.
* The Mosquitto `docker-compose.yml` is untested here; the MQTT path was tested against a pure-Python broker (amqtt).
* Patent note from your own draft still applies: claims should be validated by a formal prior-art search.
