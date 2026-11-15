import importlib.util
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from app.utils.env import env_number


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_invalid_numbers_are_rejected_with_setting_name(self):
        for value in ['', 'garbage', 'NaN', 'inf', '-inf', '1e999', '-1', '101']:
            with self.subTest(value=value), patch.dict(os.environ, {'TEST_NUMBER': value}):
                with self.assertRaisesRegex(ValueError, 'TEST_NUMBER.*between 0 and 100'):
                    env_number('TEST_NUMBER', 10, minimum=0, maximum=100)

    def test_integer_settings_reject_fractions_and_invalid_values(self):
        for value in ['1.5', '2.0', '', 'NaN', 'inf', '0', '-1', '33', '1e2', '9' * 500]:
            with self.subTest(value=value), patch.dict(os.environ, {'TEST_WORKERS': value}):
                with self.assertRaisesRegex(ValueError, 'TEST_WORKERS.*integer'):
                    env_number('TEST_WORKERS', 2, minimum=1, maximum=32, integer=True)

    def test_defaults_and_inclusive_boundaries(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_number('TEST_NUMBER', 10, minimum=0, maximum=100), 10)
        for value in ['0', '0.1', '100']:
            with self.subTest(value=value), patch.dict(os.environ, {'TEST_NUMBER': value}):
                self.assertEqual(env_number('TEST_NUMBER', 10, minimum=0, maximum=100), float(value))

    def test_application_settings_are_validated_when_loaded(self):
        for name in ['AWS_CACHE_TTL', 'AWS_REFRESH_TIMEOUT', 'AWS_FAILURE_COOLDOWN', 'AWS_TASK_TIMEOUT', 'AWS_MAX_DATA_AGE']:
            with self.subTest(name=name), patch.dict(os.environ, {name: 'nan'}, clear=True):
                spec = importlib.util.spec_from_file_location(
                    'app.utils.validation_test', ROOT / 'app/utils/app_config.py'
                )
                module = importlib.util.module_from_spec(spec)
                with self.assertRaisesRegex(ValueError, name):
                    spec.loader.exec_module(module)

    def test_gunicorn_settings_are_validated_when_loaded(self):
        for name in ['APP_PORT', 'WEB_CONCURRENCY', 'GUNICORN_THREADS']:
            with self.subTest(name=name), patch.dict(os.environ, {name: '0'}, clear=True):
                with self.assertRaisesRegex(ValueError, name):
                    runpy.run_path(str(ROOT / 'gunicorn.conf.py'))
        with patch.dict(os.environ, {}, clear=True):
            settings = runpy.run_path(str(ROOT / 'gunicorn.conf.py'))
            self.assertEqual(settings['workers'], 2)
            self.assertEqual(settings['threads'], 4)
            self.assertEqual(settings['bind'], '0.0.0.0:5001')

    def test_gunicorn_port_uses_environment_and_validates_range(self):
        for port in ['1', '8080', '65535']:
            with self.subTest(port=port), patch.dict(os.environ, {'APP_PORT': port, 'APP_HOST': '127.0.0.1'}, clear=True):
                settings = runpy.run_path(str(ROOT / 'gunicorn.conf.py'))
                self.assertEqual(settings['bind'], f'127.0.0.1:{port}')
        for port in ['0', '-1', '65536', '8080.5', '', 'invalid']:
            with self.subTest(port=port), patch.dict(os.environ, {'APP_PORT': port}, clear=True):
                with self.assertRaisesRegex(ValueError, 'APP_PORT'):
                    runpy.run_path(str(ROOT / 'gunicorn.conf.py'))
