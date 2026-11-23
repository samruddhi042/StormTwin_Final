# StormTwin NEXT · Professional Urban Flood Dashboard (Teal Edition)

**A professional light/dark teal redesign of the original AI-driven urban stormwater digital twin**, designed as a third-year IoT & Sustainability demonstration. Read `README_THEME.md` for the full six-workspace guide.

> **Important:** This remains a *software-only, synthetic* stormwater system. The city illustration is schematic. Real sensor readings in the UI come from the original, SWMM-generated `stormtwin.db`, not from an operating municipal pipeline. No ESP32, pump, or city infrastructure is connected.

## QUICK START (Windows, no extra libraries required)

1. Extract the ZIP.
2. Open the `StormTwin_NEXT` folder.
3. Double-click **`RUN_STORMTWIN_NEXT.bat`**. Alternatively open a terminal in the folder and run:

   ```powershell
   py -3 dashboard_server.py
   ```

4. The browser opens **http://localhost:8502**. If a browser does not open, enter that address yourself.
5. To stop the server, press **Ctrl+C** in its terminal.

**Do not launch `streamlit run app.py` if you want the new dashboard.** `app.py` is deliberately preserved as the original legacy Streamlit interface.

Python 3.11 is recommended for installing the project ML/hydraulic dependencies. The visual replay itself runs on Python 3.9+ standard library.

## What changed

| NEXT feature | What it does | Does it use actual project data? |
|---|---|---|
| Visual twin | SVG city illustration with linked J1–J7, C1–C7, C3 obstruction, bypass, pump and animated flow | Uses actual topology from `swmm_model.py`; schematic positions, not a GIS model |
| Replay controls | Play/pause, 5-minute steps, speed control, timeline | Yes, 239 minutes of recorded synthetic telemetry |
| Guided demo | Automatically plays the key blockage/flooding storyline | Yes, based on the supplied scripted event |
| Asset inspector | Click a junction or pipe for measurement, quality and trace | Yes, directly from `stormtwin.db` export |
| IoT network | 15-channel sensor console with quality flags, battery, RSSI and packet gaps | Yes, saved by original gateway |
| What-if / Scenario Lab | Original T+60 comparison, adjustable rainfall/blockage/delays, visual response animation | Original baseline figures came from user's running Streamlit screenshot; changed values require an SWMM rerun |
| SWMM recompute API | Invokes the **actual original** `twin.estimate_blockage`, `twin.mixed_rain`, `twin.simulate_scenarios` | Yes, when PySWMM and project requirements are installed |
| AI diagnostics | Explains Random Forest, Isolation Forest and twin differences | Uses original `metrics.json` and time-60 recorded reference |
| Architecture | Interactive guide to every Python module and data flow | Yes |
| Gateway sensor-health fix | An unavailable/stale sensor no longer appears as a falsely severe pipe DHI | Code fix in `twin.py` |

### Run real SWMM what-if predictions

The visual interface needs no extra packages, but **clicking `Calculate with real SWMM` requires Python packages from the project**:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "scikit-learn==1.8.0"
python dashboard_server.py
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

The scenario lab calls the original PySWMM hydraulic engine through `/api/swmm`. Because each evaluation reruns a large number of hydraulic simulations, **the first model computation can be slow**, especially on lower-powered computers. The browser reports loading/errors instead of silently faking new predictions.

**Forecast limitation:** The original `twin.mixed_rain` uses the *scripted future storm* multiplied by a factor, not an independent forecast from a weather provider. This must be stated during your demo.

### Rebuild demo telemetry after changing original simulation

```powershell
python run_pipeline.py
python export_demo.py
python dashboard_server.py
```

`export_demo.py` reads `stormtwin.db` through the Python standard library. It keeps invalid/rejected and missing readings as missing instead of interpolating over them.

### Keep the original dashboard available

```powershell
python -m streamlit run app.py
```

It remains unchanged aside from a targeted missing-sensor DHI fix in `twin.py`, so your team's previous code is still present.

## Demonstration: 4-minute faculty walkthrough

1. **Open Network Twin** at minute 60. Point out the orange C3 pipe, animated water, the highlighted blockage, rainfall reading and flood warning. Explain that the displayed ~19-minute lead comes from the **hydraulic twin**, not the Random Forest (0.39 risk vs 0.80 classifier threshold).
2. **Click GUIDED DEMO**. Let the time replay show the C3 blockage beginning at T+15, reaching 75% at T+25, and recorded flooding beginning T+75. Stop or jump to minute 60 to discuss the early-warning decision.
3. **Open IoT Monitoring**. Choose J3 to show recorded water depth, then use minute 110 and J2 to demonstrate the gateway's sensor-fault `suspect` flag.
4. **Open Mitigation Lab** at T+60. Compare baseline 615 m³ overflow with mitigation scenarios shown in the original run. Change C3 obstruction or rain factor. Note that reference values are no longer current and **click Calculate with real SWMM** after installing dependencies.
5. **Open System Design** and explain the code modules from EPA SWMM → virtual sensors → MQTT/local bus → gateway → SQLite → AI/twin → scenario dashboard.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

Also test browser interaction by clicking an asset, scrubbing the timeline, changing IoT channel filters, choosing a scenario, and opening the architecture cards.

## File organization

```
StormTwin_NEXT/
├── dashboard_server.py       # Pure-Python local web server, optional PySWMM API
├── export_demo.py            # Extracts actual gateway records
├── RUN_STORMTWIN_NEXT.bat    # Double-click Windows launcher
├── web/
│   ├── index.html             # Professional six-workspace operator dashboard
│   ├── assets/styles.css     # Original component styles + animations
│   ├── assets/app.js         # Controls, network, charts, scenario visualizations
│   └── data/demo.json        # Export of original SQLite time series
├── web/assets/theme.css      # User-supplied light/dark teal tokens and new design
├── README_THEME.md           # Redesigned navigation and setup
├── tests/test_project.py     # Data integrity / missing-packet / reference tests
├── app.py                    # Original Streamlit dashboard (legacy)
├── swmm_model.py             # Original hydraulic world
├── sensors.py, bus.py, gateway.py
├── ml.py, twin.py, demo.py, run_pipeline.py
├── models.joblib             # Provided pretrained model (not recreated)
├── stormtwin.db              # Provided sensor database
└── requirements.txt
```

## Academic honesty and limitations

- This is **not live municipal telemetry**. All sensors, flooding and operator actuators are simulated.
- The map is an illustrative 2D network, not a calibrated 3D city or real GIS-digital twin.
- Animated water is illustrative, and the scenario schematic is not a hydraulic prediction.
- All dynamically changed what-if values require a SWMM recomputation. The static original T+60 result remains labeled as reference until rerun.
- The user-provided dashboard screenshot supplied the T+60 figures (615 m³ baseline, 19-minute lead, C3 ~72% fitted, other mitigation results). The stored database itself contains time series, **not** all these model forecasts.
- Classifier ROC-AUC 0.9793, precision 0.978, recall 0.379 and 50 held-out events come from `metrics.json`; they are not field-validation results.

This is built to make a *real software simulation* understandable and visually impressive, without overstating field performance.
