"""Export the existing StormTwin SQLite sensor replay to browser-friendly JSON.

Pure Python standard library. Does not synthesize values or require PySWMM.
"""
from pathlib import Path
import sqlite3, json, statistics

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'stormtwin.db'
TARGET = ROOT / 'web' / 'data' / 'demo.json'
CHANNELS = {**{f'J{i}': f'LVL-J{i}' for i in range(1, 8)},
            **{f'C{i}': f'FLW-C{i}' for i in range(1, 8)}, 'rain': 'RAIN-1'}


def build(db=DB, out=TARGET):
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        vals = con.execute('SELECT t_min, node_id, value, quality, battery, rssi FROM readings WHERE run_id=? ORDER BY t_min', ('demo',)).fetchall()
    if not vals:
        raise RuntimeError(f'No demo readings in {db}. Run `python run_pipeline.py` first.')
    by_time = {}
    for r in vals:
        t = int(r['t_min'])
        by_time.setdefault(t, {})[r['node_id']] = r
    records = []
    for t in range(1, max(by_time) + 1):
        observed = by_time.get(t, {})
        rec = {'t': t, 'readings': {}, 'quality': {}, 'battery': {}, 'rssi': {}}
        for logical, channel in CHANNELS.items():
            row = observed.get(channel)
            rec['readings'][logical] = round(float(row['value']), 4) if row and row['value'] is not None and row['quality'] != 'rejected' else None
            rec['quality'][logical] = str(row['quality']) if row else 'missing'
            if row:
                rec['battery'][logical] = round(float(row['battery']), 1) if row['battery'] is not None else None
                rec['rssi'][logical] = int(row['rssi']) if row['rssi'] is not None else None
        records.append(rec)
    meta = {
        'source': 'stormtwin.db / original simulator generated IoT telemetry',
        'mode': 'recorded synthetic SWMM storm replay',
        'minuteCount': len(records),
        'rawReadings': len(vals),
        'channels': list(CHANNELS),
        'channelTypes': {**{f'J{i}':'water level' for i in range(1,8)}, **{f'C{i}':'flow rate' for i in range(1,8)}, 'rain':'rainfall'},
        'units': {**{f'J{i}':'m' for i in range(1,8)}, **{f'C{i}':'m³/s' for i in range(1,8)}, 'rain':'mm/h'},
        'scenario': {'blockagePipe':'C3','scriptedRestriction':75,'blockageStartsMin':15,'blockageEstablishedMin':25,'sensorFreeze':'J2','sensorFreezeStartsMin':90,'observedFirstFloodMin':75},
        'reference': {'timeMin':60,'source':'Original Streamlit dashboard screenshot at minute 60 (user-supplied)',
            'rain_mmh':31,'risk':0.39,'alarmThreshold':0.8,'DHI_C3':50.1,'inferredBlockagePercent':72,
            'timeToOverflowMin':19,'baselineOverflowM3':615,
            'strategies':[
                {'id':'baseline','label':'No intervention','volume':615,'peakDepth':2.0,'delay':None},
                {'id':'clear','label':'Clear blockage','volume':0,'peakDepth':1.05,'delay':8},
                {'id':'bypass','label':'Open bypass','volume':0,'peakDepth':1.44,'delay':3},
                {'id':'pump','label':'Deploy pump','volume':0,'peakDepth':1.56,'delay':5},
                {'id':'combo','label':'Pump + bypass','volume':0,'peakDepth':0.75,'delay':3},
            ]},
        'topology': [
            {'id':'C1','from':'J1','to':'J2'}, {'id':'C2','from':'J2','to':'J3'},
            {'id':'C3','from':'J3','to':'J4'}, {'id':'C4','from':'J4','to':'J5'},
            {'id':'C5','from':'J5','to':'OUT1'}, {'id':'C6','from':'J6','to':'J3'},
            {'id':'C7','from':'J7','to':'J4'},
        ]
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'meta':meta,'samples':records}, ensure_ascii=False, separators=(',', ':')),encoding='utf-8')
    return out

if __name__ == '__main__':
    path=build(); print(f'Exported replay: {path} ({path.stat().st_size:,} bytes)')
