"""StormTwin NEXT local interactive frontend + optional real PySWMM what-if API.

Run: python dashboard_server.py
No Python dependencies needed for the interface. Real forecasts require `pip install -r requirements.txt`.
"""
import os, sys, json, functools, threading, webbrowser, argparse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
CACHE = {}
_LOCK = threading.Lock()


def numeric(v, lo, hi, fallback):
    try:
        f = float(v)
        if not (lo <= f <= hi): raise ValueError()
        return f
    except (ValueError, TypeError):
        return fallback


def compute_scenarios(args):
    """Runs *original* project source, no invented physics.

    Note: rain forecast in twin.mixed_rain uses the demo's scripted future profile.
    """
    t = int(numeric(args.get('minute',60), 30, 125, 60))
    rainfall = numeric(args.get('rainFactor',1.0), 0.7, 1.3, 1)
    blockage = numeric(args.get('blockage', 72), 0, 98, 72)
    delays = {x:int(numeric(args.get(x, defaults), 1, 30, defaults)) for x,defaults in [('clear',8),('bypass',3),('pump',5)]}
    key=(t,rainfall,blockage,tuple(delays.values()))
    with _LOCK:
        if key in CACHE:
            return CACHE[key]
    import demo, twin
    w, _ = demo.load_demo(str(ROOT/'stormtwin.db'))
    est = twin.estimate_blockage(w, t)
    # An explicitly hypothetical change of C3's opening: not observed, only the next scenario forecast.
    est['settings']['C3'] = round(1 - blockage/100, 3)
    rain = twin.mixed_rain(w, t, demo.rain(), rainfall)
    sim = twin.simulate_scenarios(est, rain, t, delays)
    result={
        'source':'EPA SWMM via PySWMM, using the uploaded project hydraulic model',
        'forecastCaveat':'Future rain uses the original scripted storm curve × forecast factor; this is not a live weather forecast.',
        'minute':t,'blockage':blockage,'settings':est['settings'],
        'strategies':[]
    }
    ids={'Baseline (no action)':'baseline','Clear blockage':'clear','Open bypass pipe':'bypass','Temporary pump':'pump','Pump + bypass':'combo'}
    for name, item in sim.items():
        df=item['df']; m=item['metrics']
        plotted=df[(df.t_min>=t-4) & (df.t_min<=min(t+100,239))]
        series=[]
        for _, row in plotted.iloc[::2].iterrows():
            depth=row.get('d_J3')
            series.append([int(row['t_min']), round(float(depth),3)])
        result['strategies'].append({'id':ids.get(name,name),'label':name,
            'volume':round(float(m['flood_volume_m3']),1),'peakDepth':round(float(m['peak_depth_m']),3),
            'timeToFlood':m['time_to_flood_min'],'reduction':m['flood_reduction_pct'], 'flooded':m['flooded_nodes'],'series':series})
    with _LOCK:
        if len(CACHE)>12:CACHE.clear()
        CACHE[key]=result
    return result


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_POST(self):
        if urlparse(self.path).path != '/api/swmm':
            self._respond(404, {'error':'Unknown endpoint'})
            return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>16_384:
                self._respond(400, {'error':'Invalid request length'}); return
            request=json.loads(self.rfile.read(size))
            result=compute_scenarios(request)
            self._respond(200,result)
        except ImportError as exc:
            self._respond(503, {'error':f'SWMM libraries missing: {exc}. Install using pip install -r requirements.txt, then restart the server.'})
        except Exception as exc:
            self._respond(500, {'error':f'Simulation failed: {exc.__class__.__name__}: {exc}'})

    def _respond(self, code, obj):
        raw=json.dumps(obj, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(raw)

    def log_message(self, fmt, *args):
        sys.stderr.write('[StormTwin] '+fmt%args+'\n')


def main():
    p=argparse.ArgumentParser(description='Run StormTwin NEXT interactive web experience')
    p.add_argument('--port',type=int,default=8502)
    p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    if not (WEB/'data'/'demo.json').is_file():
        from export_demo import build
        build()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url=f'http://localhost:{args.port}'
    print('\n  StormTwin NEXT — Urban Flood Digital Twin')
    print(f'  Open: {url}')
    print('  Press Ctrl+C to exit.\n')
    if not args.no_browser:
        threading.Timer(0.8, lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt: pass
    finally:server.server_close()

if __name__=='__main__':main()
