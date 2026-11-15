import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from prometheus_client.parser import text_string_to_metric_families

from app import create_app


ROOT = Path(__file__).resolve().parents[1]


def samples(body):
    return [sample for family in text_string_to_metric_families(body) for sample in family.samples]


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, DASHBOARD_USERNAME='operator', DASHBOARD_PASSWORD_HASH='invalid')
        self.client = self.app.test_client()

    def test_scrapes_are_public_parseable_and_never_query_aws(self):
        with patch('app.utils.dal.boto3.Session') as session:
            response = self.client.get('/metrics')
            self.assertEqual(response.status_code, 200)
            self.assertIn('text/plain', response.content_type)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            names = {sample.name for sample in samples(response.get_data(as_text=True))}
            self.assertIn('aws_monitor_http_requests_total', names)
            self.assertIn('aws_monitor_http_request_duration_seconds_bucket', names)
            self.assertEqual(response.data, self.client.get('/metrics').data)
            session.assert_not_called()

    def test_requests_statuses_latency_and_bounded_routes(self):
        self.client.get('/health')
        self.client.get('/')
        self.client.get('/unknown/private-resource?secret=hidden')
        parsed = samples(self.client.get('/metrics').get_data(as_text=True))
        counters = [sample for sample in parsed if sample.name == 'aws_monitor_http_requests_total']
        for route, status in [('/health', '200'), ('/', '401'), ('unmatched', '404')]:
            matching = [sample for sample in counters if sample.labels == {'method': 'GET', 'route': route, 'status': status}]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].value, 1)
        durations = [sample for sample in parsed if sample.name == 'aws_monitor_http_request_duration_seconds_count']
        self.assertEqual(sum(sample.value for sample in durations), 3)
        self.assertNotIn('private-resource', str(parsed))
        self.assertNotIn('hidden', str(parsed))

    def test_multiple_app_factories_have_independent_registries(self):
        self.client.get('/health')
        other = create_app().test_client()
        parsed = samples(other.get('/metrics').get_data(as_text=True))
        count = next(sample.value for sample in parsed if sample.name == 'aws_monitor_http_requests_total')
        self.assertEqual(count, 0)

    def test_multiprocess_scrape_aggregates_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, 'PROMETHEUS_MULTIPROC_DIR': directory}
            worker_code = '''
from app import create_app
client = create_app().test_client()
for _ in range(2):
    assert client.get('/health').status_code == 200
'''
            for _ in range(2):
                subprocess.run([sys.executable, '-c', worker_code], cwd=ROOT, env=environment,
                               capture_output=True, text=True, check=True, timeout=30)
            scrape = subprocess.run(
                [sys.executable, '-c', "from app import create_app; print(create_app().test_client().get('/metrics').get_data(as_text=True))"],
                cwd=ROOT, env=environment, capture_output=True, text=True, check=True, timeout=30,
            )
            parsed = samples(scrape.stdout)
            counts = [sample for sample in parsed if sample.name == 'aws_monitor_http_requests_total']
            self.assertEqual(len(counts), 1)
            self.assertEqual(counts[0].value, 4)
            duration_count = next(sample.value for sample in parsed if sample.name == 'aws_monitor_http_request_duration_seconds_count')
            self.assertEqual(duration_count, 4)

    def test_gunicorn_start_clears_only_metric_files(self):
        with tempfile.TemporaryDirectory() as directory:
            metric_file = Path(directory) / 'counter_123.db'
            retained_file = Path(directory) / 'keep.txt'
            metric_file.touch()
            retained_file.touch()
            with patch.dict(os.environ, {'PROMETHEUS_MULTIPROC_DIR': directory}):
                config = runpy.run_path(str(ROOT / 'gunicorn.conf.py'))
                config['on_starting'](None)
            self.assertFalse(metric_file.exists())
            self.assertTrue(retained_file.exists())
