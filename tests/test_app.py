import os
import unittest
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, PartialCredentialsError

from app import create_app
from app.utils.app_config import AppConfig
from app.logic.resources_logic import ResourcesLogic


class ApplicationTests(unittest.TestCase):
    @staticmethod
    def make_client():
        client = Mock()

        def get_paginator(operation):
            paginator = Mock()
            paginator.paginate.side_effect = lambda **kwargs: [getattr(client, operation)(**kwargs)]
            return paginator

        client.get_paginator.side_effect = get_paginator
        return client

    def setUp(self):
        # Keep AWS mocks in-process; real process isolation is tested separately.
        patcher = patch('app.logic.resources_cache.ResourcesLogic', ResourcesLogic)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app()
        self.app.config.update(TESTING=True, AWS_REGION='eu-west-1', AWS_CACHE_TTL=0)
        self.client = self.app.test_client()

    def test_monitoring_does_not_access_aws(self):
        with patch('app.utils.dal.boto3.Session') as session:
            response = self.client.get('/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'status': 'ok'})
            self.assertEqual(self.client.get('/metrics').status_code, 200)
            session.assert_not_called()

    def test_refresh_timeout_displays_previous_data_with_warning(self):
        cache = self.app.extensions['resources_cache']
        snapshot = {
            'instance_data': [], 'vpc_data': [], 'lb_data': [],
            'ami_data': [{'AMI ID': 'ami-previous', 'Name': 'Previous image'}],
        }
        with patch.object(cache, 'get_resources', return_value=(
            snapshot, {'ami_data': TimeoutError('internal details')}
        )):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Showing previously fetched data.', html)
        self.assertIn('ami-previous', html)
        self.assertIn('Reload shortly', html)
        self.assertNotIn('internal details', html)

    def test_empty_stale_snapshot_shows_age_and_warning(self):
        cache = self.app.extensions['resources_cache']
        snapshot = {
            'instance_data': [], 'vpc_data': [], 'lb_data': [], 'ami_data': [],
            'freshness': {'ami_data': {
                'fetched_at': '2026-11-15T10:00:00+00:00',
                'fetched_label': '2026-11-15 10:00:00 UTC',
                'age_seconds': 125, 'stale': True,
            }},
        }
        with patch.object(cache, 'get_resources', return_value=(
            snapshot, {'ami_data': NoCredentialsError()}
        )):
            response = self.client.get('/')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('2026-11-15 10:00:00 UTC', html)
        self.assertIn('data-age-seconds="125"', html)
        self.assertIn('Stale data', html)
        self.assertIn('Showing previously fetched data.', html)
        self.assertIn('No successful fetch yet', html)

    def test_expired_resource_data_is_not_rendered(self):
        logic = Mock()
        logic.get_instances.return_value = [{
            'ID': 'i-too-old', 'State': 'running', 'Type': 't3.micro', 'Public IP': 'N/A',
        }]
        for name in ['get_vpcs', 'get_load_balancers', 'get_images']:
            getattr(logic, name).return_value = []
        self.app.config.update(AWS_CACHE_TTL=30, AWS_MAX_DATA_AGE=10)
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                self.assertIn('i-too-old', self.client.get('/').get_data(as_text=True))
            logic.get_instances.side_effect = NoCredentialsError()
            with patch('app.logic.resources_cache.monotonic', return_value=110):
                with self.assertLogs(self.app.logger, level='WARNING'):
                    response = self.client.get('/')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('i-too-old', html)
        self.assertIn('Previously fetched data is too old to display.', html)
        self.assertIn('Expired data', html)

    def test_configuration_is_static_after_import(self):
        with patch.dict(os.environ, {'APP_HOST': 'changed', 'AWS_REGION': 'changed'}):
            application = create_app()
            self.assertEqual(application.config['APP_HOST'], AppConfig.APP_HOST)
            self.assertEqual(application.config['AWS_REGION'], AppConfig.AWS_REGION)

    def test_cached_failure_is_not_logged_on_each_visit(self):
        logic = Mock()
        logic.get_instances.side_effect = NoCredentialsError()
        for name in ['get_vpcs', 'get_load_balancers', 'get_images']:
            getattr(logic, name).return_value = []
        self.app.config['AWS_CACHE_TTL'] = 30
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                with self.assertLogs(self.app.logger, level='WARNING') as logs:
                    self.assertEqual(self.client.get('/').status_code, 200)
                self.assertEqual(len(logs.records), 1)
            with patch('app.logic.resources_cache.monotonic', return_value=105):
                with self.assertNoLogs(self.app.logger, level='WARNING'):
                    for _ in range(5):
                        response = self.client.get('/')
                        self.assertIn('credentials are missing', response.get_data(as_text=True))
                logic.get_instances.assert_called_once()
            with patch('app.logic.resources_cache.monotonic', return_value=110):
                with self.assertLogs(self.app.logger, level='WARNING') as logs:
                    self.assertEqual(self.client.get('/').status_code, 200)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logic.get_instances.call_count, 2)

    def test_dashboard_renders_aws_resources_and_escapes_names(self):
        ec2 = self.make_client()
        ec2.describe_instances.return_value = {
            'Reservations': [{'Instances': [{
                'InstanceId': 'i-test',
                'State': {'Name': 'running'},
                'InstanceType': 't3.micro',
            }]}]
        }
        ec2.describe_vpcs.return_value = {
            'Vpcs': [{'VpcId': 'vpc-test', 'CidrBlock': '10.0.0.0/16'}]
        }
        ec2.describe_images.return_value = {
            'Images': [{'ImageId': 'ami-test', 'Name': '<script>bad</script>'}]
        }
        elb = self.make_client()
        elb.describe_load_balancers.return_value = {
            'LoadBalancers': [{
                'LoadBalancerName': 'lb-test', 'DNSName': 'example.test',
            }]
        }
        with patch('app.utils.dal.boto3.Session') as session:
            session.return_value.client.side_effect = lambda service, **kwargs: {'ec2': ec2, 'elbv2': elb}[service]
            response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for expected in [
            '<!DOCTYPE html>', 'i-test', 'running', 't3.micro', 'N/A',
            'vpc-test', '10.0.0.0/16', 'ami-test', 'lb-test', 'example.test',
            '&lt;script&gt;bad&lt;/script&gt;',
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, html)
        self.assertNotIn('<script>bad</script>', html)
        session.assert_called_once_with(region_name='eu-west-1')
        ec2.describe_images.assert_called_once_with(Owners=['self'])

    def test_dashboard_handles_empty_resource_lists(self):
        ec2 = self.make_client()
        ec2.describe_instances.return_value = {'Reservations': []}
        ec2.describe_vpcs.return_value = {'Vpcs': []}
        ec2.describe_images.return_value = {'Images': []}
        elb = self.make_client()
        elb.describe_load_balancers.return_value = {'LoadBalancers': []}
        with patch('app.utils.dal.boto3.Session') as session:
            session.return_value.client.side_effect = lambda service, **kwargs: {'ec2': ec2, 'elbv2': elb}[service]
            self.assertEqual(self.client.get('/').status_code, 200)

    def test_aws_failures_preserve_other_sections(self):
        failures = [
            (NoCredentialsError(), 'credentials are missing'),
            (PartialCredentialsError(provider='env', cred_var='AWS_SECRET_ACCESS_KEY'),
             'credentials are missing'),
            (ClientError({'Error': {'Code': 'UnauthorizedOperation', 'Message': 'private details'}},
                         'DescribeInstances'), 'access denied'),
            (ClientError({'Error': {'Code': 'ExpiredToken', 'Message': 'private details'}},
                         'DescribeInstances'), 'invalid or expired'),
            (EndpointConnectionError(endpoint_url='https://private-endpoint.test'),
             'Please try again later'),
            (ClientError({'Error': {'Code': 'Throttling', 'Message': 'private details'}},
                         'DescribeInstances'), 'Please try again later'),
        ]
        for error, message in failures:
            with self.subTest(error=error), patch('app.utils.dal.boto3.Session') as session:
                self.setUp()
                ec2 = self.make_client()
                ec2.describe_instances.side_effect = error
                ec2.describe_vpcs.return_value = {
                    'Vpcs': [{'VpcId': 'vpc-still-visible', 'CidrBlock': '10.0.0.0/16'}]
                }
                ec2.describe_images.return_value = {'Images': []}
                elb = self.make_client()
                elb.describe_load_balancers.return_value = {'LoadBalancers': []}
                session.return_value.client.side_effect = lambda service, **kwargs: {'ec2': ec2, 'elbv2': elb}[service]
                with self.assertLogs(self.app.logger, level='WARNING'):
                    response = self.client.get('/')
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn(message, html)
                self.assertIn('vpc-still-visible', html)
                self.assertEqual(html.count('role="alert"'), 1)
                self.assertNotIn('private details', html)
                self.assertNotIn('private-endpoint.test', html)

    def test_session_initialization_failure_shows_errors_for_all_sections(self):
        with patch('app.utils.dal.boto3.Session', side_effect=NoCredentialsError()):
            with self.assertLogs(self.app.logger, level='WARNING'):
                response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True).count('role="alert"'), 4)

    def test_client_initialization_failure_is_isolated(self):
        with patch('app.utils.dal.boto3.Session') as session:
            ec2 = self.make_client()
            ec2.describe_instances.return_value = {'Reservations': []}
            ec2.describe_vpcs.return_value = {'Vpcs': []}
            ec2.describe_images.return_value = {'Images': [{'ImageId': 'ami-still-visible'}]}

            def create_client(service, **kwargs):
                if service == 'elbv2':
                    raise EndpointConnectionError(endpoint_url='https://private-endpoint.test')
                return ec2

            session.return_value.client.side_effect = create_client
            with self.assertLogs(self.app.logger, level='WARNING'):
                response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('ami-still-visible', html)
        self.assertEqual(html.count('role="alert"'), 1)


if __name__ == '__main__':
    unittest.main()
