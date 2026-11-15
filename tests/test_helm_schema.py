from pathlib import Path
import shutil
import subprocess
import unittest


CHART = Path(__file__).resolve().parents[1] / 'chart'


@unittest.skipUnless(shutil.which('helm'), 'Helm is required for chart validation')
class HelmSchemaTests(unittest.TestCase):
    def render(self, *overrides):
        command = ['helm', 'template', 'schema-test', str(CHART), '--namespace', 'ci']
        if not any(value.startswith('pod.digest=') for value in overrides):
            command.extend(['--set-string', 'pod.digest=sha256:' + '0' * 64])
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
            'pod.digest': ['invalid', 'sha256:1234'],
            'replicas': ['0', '1.5'],
            'dashboard.maxFailures': ['0', '101', '1.5'],
            'dashboard.windowSeconds': ['0', '3601', '1.5'],
            'dashboard.trustedProxyCidrs': ['invalid', '1'],
            'mongodb.existingSecret': [''],
            'mongodb.database': ['', 'invalid/name', 'a' * 64],
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

    def test_deployment_requires_digest_and_references_runtime_secrets(self):
        missing = self.render('pod.digest=')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('pod.digest is required', missing.stderr)
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('namespace: ci', result.stdout)
        self.assertIn('automountServiceAccountToken: false', result.stdout)
        self.assertIn('type: RuntimeDefault', result.stdout)
        self.assertIn('runAsUser: 10001', result.stdout)
        self.assertIn('name: MONGODB_URI', result.stdout)
        self.assertIn('name: AWS_SECRET_ACCESS_KEY', result.stdout)
        self.assertIn('name: AWS_SESSION_TOKEN', result.stdout)
        self.assertIn('optional: true', result.stdout)
        self.assertEqual(result.stdout.count('secretKeyRef:'), 4)
        self.assertNotIn('volumeMounts:', result.stdout)
        self.assertIn('image: "sm1986/aws-monitor@sha256:', result.stdout)

    def test_trusted_proxy_networks_are_injected(self):
        result = self.render('dashboard.trustedProxyCidrs[0]=10.20.0.0/24')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('name: AUTH_TRUSTED_PROXY_CIDRS\n              value: "10.20.0.0/24"', result.stdout)
