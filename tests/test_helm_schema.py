from pathlib import Path
import shutil
import subprocess
import unittest


CHART = Path(__file__).resolve().parents[1] / 'chart'


@unittest.skipUnless(shutil.which('helm'), 'Helm is required for chart validation')
class HelmSchemaTests(unittest.TestCase):
    def render(self, *overrides):
        command = ['helm', 'template', 'schema-test', str(CHART)]
        for override in overrides:
            # Helm --set parses decimal values as strings; --set-json preserves numbers.
            value = override.partition('=')[2]
            flag = '--set-json' if '.' in value and value.replace('.', '', 1).isdigit() else '--set'
            command.extend([flag, override])
        return subprocess.run(command, capture_output=True, text=True, timeout=30)

    def test_defaults_and_valid_boundaries_render(self):
        for overrides in [
            (),
            ('app.cacheTtl=0', 'app.refreshTimeout=0', 'app.failureCooldown=0',
             'app.taskTimeout=0.1', 'app.maxDataAge=1', 'app.workers=1',
             'app.threads=1', 'pod.targetPort=1', 'pod.port=1'),
            ('app.cacheTtl=86400', 'app.refreshTimeout=30', 'app.failureCooldown=3600',
             'app.taskTimeout=300', 'app.maxDataAge=86400', 'app.workers=32',
             'app.threads=64', 'pod.targetPort=65535', 'pod.port=65535'),
        ]:
            with self.subTest(overrides=overrides):
                result = self.render(*overrides)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_runtime_values_fail_schema_validation(self):
        cases = {
            'app.cacheTtl': ['-1', '86401', 'nan'],
            'app.refreshTimeout': ['-1', '31', 'inf'],
            'app.failureCooldown': ['-1', '3601'],
            'app.taskTimeout': ['0', '301'],
            'app.maxDataAge': ['0', '86401'],
            'app.workers': ['0', '33', '1.5', 'invalid'],
            'app.threads': ['0', '65', '2.5'],
            'app.awsRegion': [''],
            'pod.targetPort': ['0', '65536', '1.5'],
            'pod.port': ['0', '65536'],
            'replicas': ['0', '1.5'],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    result = self.render(f'{name}={value}')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('schema', result.stderr.lower())
                    self.assertIn(name.rsplit('.', 1)[-1], result.stderr)

    def test_unknown_app_setting_is_rejected(self):
        result = self.render('app.cacheTTL=60')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cacheTTL', result.stderr)
