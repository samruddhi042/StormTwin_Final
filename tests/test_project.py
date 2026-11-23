"""Run with: python -m unittest discover -s tests -v (no external dependencies)."""
import sys, json, sqlite3, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_demo import build
from dashboard_server import numeric

class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/'web/data/demo.json'
        cls.data=json.loads(cls.path.read_text(encoding='utf-8'))

    def test_replay_is_original_data(self):
        d=self.data
        self.assertEqual(d['meta']['rawReadings'],3515)
        self.assertEqual(d['meta']['minuteCount'],239)
        self.assertEqual(len(d['meta']['channels']),15)
        self.assertEqual(len(d['samples']),239)
        with sqlite3.connect(str(ROOT/'stormtwin.db')) as conn:
            j3=conn.execute("SELECT value FROM readings WHERE t_min=60 AND node_id='LVL-J3'").fetchone()[0]
        self.assertEqual(d['samples'][59]['readings']['J3'],round(j3,4))

    def test_quality_flags_preserved(self):
        samples=self.data['samples']
        self.assertEqual(samples[109]['quality']['J2'],'suspect')
        self.assertEqual(samples[59]['quality']['J2'],'ok')
        self.assertGreater(sum(1 for s in samples if s['quality']['J2']=='suspect'),100)

    def test_missing_packets_are_not_invented(self):
        s=self.data['samples']
        missing=sum(v is None for x in s for v in x['readings'].values())
        self.assertGreater(missing,0)
        self.assertTrue(all(x['readings']['J3'] is None if x['quality']['J3']=='missing' else True for x in s))

    def test_reference_is_labeled(self):
        r=self.data['meta']['reference']
        self.assertIn('screenshot',r['source'].lower())
        self.assertEqual(r['timeMin'],60)
        self.assertEqual(r['alarmThreshold'],0.8)
        self.assertEqual(r['baselineOverflowM3'],615)
        self.assertEqual(len(r['strategies']),5)

    def test_reexport_idempotent(self):
        path=build()
        self.assertEqual(path,self.path)
        self.assertEqual(json.loads(path.read_text())['meta']['rawReadings'],3515)

    def test_parameter_validation(self):
        self.assertEqual(numeric(2,0,3,1),2)
        self.assertEqual(numeric(200,0,3,1),1)
        self.assertEqual(numeric('bad',0,3,1),1)

if __name__=='__main__':unittest.main()
