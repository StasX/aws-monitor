import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/release_metadata.py'


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'metadata.json'
        self.output = Path(self.directory.name) / 'output'
        self.data = {'name': 'aws-monitor', 'version': {
            'dev': '1.0.47', 'qa': '1.0.34', 'prod': '1.0.20'},
            'description': 'Keep this field'}
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def run_command(self, command, environment):
        return subprocess.run(
            [sys.executable, str(SCRIPT), command, '--path', str(self.path)],
            env={**os.environ, 'RELEASE_ENV': environment, 'GITHUB_OUTPUT': str(self.output)},
            capture_output=True, text=True, timeout=10,
        )

    def test_tags_match_jenkins_conventions(self):
        for environment, version in self.data['version'].items():
            with self.subTest(environment=environment):
                self.output.write_text('', encoding='utf-8')
                result = self.run_command('prepare', environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                suffix = '' if environment == 'prod' else f'-{environment}'
                self.assertEqual(self.output.read_text(encoding='utf-8'),
                                 f'tag={version}{suffix}\nlatest=latest{suffix}\n')

    def test_bump_preserves_other_environments_and_fields(self):
        result = self.run_command('bump', 'qa')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {**self.data, 'version': {**self.data['version'], 'qa': '1.0.35'}}
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), expected)

    def test_invalid_environment_cannot_modify_metadata(self):
        result = self.run_command('bump', 'invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), self.data)

    def test_invalid_version_cannot_inject_workflow_output(self):
        self.data['version']['dev'] = '1.2.3\ntag=other-image'
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        result = self.run_command('prepare', 'dev')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
