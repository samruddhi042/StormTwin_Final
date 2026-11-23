"""Cheap dependency-free guards for the redesigned project UI and theme."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
WEB=ROOT/'web'

class UIContractTests(unittest.TestCase):
    def test_six_unique_workspaces(self):
        html=(WEB/'index.html').read_text(encoding='utf8')
        for name in ['overview','twin','iot','scenarios','ai','architecture']:
            self.assertEqual(html.count(f'id="view-{name}"'),1,name)
            self.assertIn(f'<button class="nav-item' , html)
            self.assertIn(f'data-view="{name}"',html)
    def test_controls_and_assets_exist(self):
        html=(WEB/'index.html').read_text(encoding='utf8')
        for cid in ['themeToggle','timeSlider','playPause','assetSelect','networkSvg','sensorGrid',
                    'scenarioCards','runSWMM','archFlow','mobileGuidedDemo','homePhaseTitle']:
            self.assertIn(f'id="{cid}"',html)
    def test_design_tokens_and_light_dark(self):
        css=(WEB/'assets/theme.css').read_text(encoding='utf8')
        for token in ['--primary:hsl(171,100%,35%)','--primary:hsl(171,90%,50%)',
                      '--font-sans:','--sidebar:','--background:','--destructive:']:
            self.assertIn(token,css)
        self.assertIn('html[data-theme="dark"]',css)
    def test_frontend_keeps_data_driven_logic(self):
        script=(WEB/'assets/app.js').read_text(encoding='utf8')
        for element in ['data/demo.json','/api/swmm','state.swmm','localStorage',
                        'changeSelected','drawSensors','drawScenarios']:
            self.assertIn(element,script)

if __name__=='__main__':unittest.main()
