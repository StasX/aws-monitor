import unittest
from unittest.mock import MagicMock, Mock, patch

import boto3
from botocore.stub import Stubber

from app import create_app
from app.utils.dal import DAL
from app.utils.errors import AWSRefreshDeadlineExceeded
from app.logic.resources_logic import ResourcesLogic


class PaginationTests(unittest.TestCase):
    def test_deadline_stops_before_requesting_another_page(self):
        dal = DAL('us-east-1', task_timeout=1)
        client = Mock()
        dal._clients['ec2'] = client
        clock = [0]
        page = Mock()

        def consume_page(key, default):
            clock[0] = 2
            return [{'VpcId': 'vpc-incomplete'}]

        page.get.side_effect = consume_page
        # A mock iterator lets us verify the second network fetch never starts.
        iterator = MagicMock()
        iterator.__iter__.side_effect = lambda: iterator
        iterator.__next__.side_effect = [page, {'Vpcs': [{'VpcId': 'vpc-second'}]}]
        client.get_paginator.return_value.paginate.return_value = iterator
        with patch('app.utils.dal.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(AWSRefreshDeadlineExceeded):
                dal.get_vpcs()
        iterator.__next__.assert_called_once()

    def test_page_arriving_after_deadline_is_discarded(self):
        dal = DAL('us-east-1', task_timeout=1)
        client = Mock()
        dal._clients['ec2'] = client
        clock = [0]

        def late_page():
            clock[0] = 2
            return {'Vpcs': [{'VpcId': 'vpc-late'}]}

        iterator = MagicMock()
        iterator.__iter__.side_effect = lambda: iterator
        iterator.__next__.side_effect = late_page
        client.get_paginator.return_value.paginate.return_value = iterator
        with patch('app.utils.dal.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(AWSRefreshDeadlineExceeded):
                dal.get_vpcs()
        iterator.__next__.assert_called_once()

    def test_client_lock_wait_obeys_task_deadline(self):
        dal = DAL('us-east-1', task_timeout=0.01)
        dal._client_lock.acquire()
        try:
            with patch('app.utils.dal.boto3.Session') as session:
                with self.assertRaises(AWSRefreshDeadlineExceeded):
                    dal.get_vpcs()
                session.assert_not_called()
        finally:
            dal._client_lock.release()

    def setUp(self):
        patcher = patch('app.logic.resources_cache.ResourcesLogic', ResourcesLogic)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Explicit fake credentials keep these tests independent of local AWS setup.
        self.session = boto3.Session(
            aws_access_key_id='testing', aws_secret_access_key='testing',
            region_name='us-east-1',
        )

    def test_all_resource_types_follow_continuation_tokens(self):
        cases = [
            ('ec2', 'describe_instances', 'Reservations', 'get_instances', {},
             [{'ReservationId': 'r-first'}], [{'ReservationId': 'r-second'}]),
            ('ec2', 'describe_vpcs', 'Vpcs', 'get_vpcs', {},
             [{'VpcId': 'vpc-first'}], [{'VpcId': 'vpc-second'}]),
            ('ec2', 'describe_images', 'Images', 'get_images', {'Owners': ['self']},
             [{'ImageId': 'ami-first'}], [{'ImageId': 'ami-second'}]),
            ('elbv2', 'describe_load_balancers', 'LoadBalancers', 'get_load_balancers', {},
             [{'LoadBalancerName': 'lb-first'}], [{'LoadBalancerName': 'lb-second'}]),
        ]
        for service, operation, key, method, parameters, first, second in cases:
            with self.subTest(operation=operation):
                client = self.session.client(service)
                dal = DAL('us-east-1')
                dal._clients[service] = client
                output_token = 'NextToken' if service == 'ec2' else 'NextMarker'
                input_token = 'NextToken' if service == 'ec2' else 'Marker'
                with Stubber(client) as stubber:
                    stubber.add_response(operation, {key: first, output_token: 'page2'}, parameters)
                    # An empty intermediate page must not end pagination.
                    stubber.add_response(operation, {key: [], output_token: 'page3'},
                                         {**parameters, input_token: 'page2'})
                    stubber.add_response(operation, {key: second},
                                         {**parameters, input_token: 'page3'})
                    self.assertEqual(getattr(dal, method)(), first + second)
                    stubber.assert_no_pending_responses()
                client.close()

    def test_dashboard_displays_instances_from_second_page(self):
        ec2 = self.session.client('ec2')
        elb = self.session.client('elbv2')
        with Stubber(ec2) as ec2_stub, Stubber(elb) as elb_stub:
            for index in [1, 2]:
                response = {'Reservations': [{'Instances': [{
                    'InstanceId': f'i-page{index}', 'InstanceType': 't3.micro',
                    'State': {'Name': 'running'},
                }]}]}
                if index == 1:
                    response['NextToken'] = 'page2'
                ec2_stub.add_response('describe_instances', response,
                                     {} if index == 1 else {'NextToken': 'page2'})
            elb_stub.add_response('describe_load_balancers', {'LoadBalancers': []}, {})
            # Independent operation paginators can run in any order.
            ec2_proxy = Mock()
            instances_paginator = ec2.get_paginator('describe_instances')

            def get_paginator(operation):
                if operation == 'describe_instances':
                    return instances_paginator
                paginator = Mock()
                paginator.paginate.return_value = [{}]
                return paginator

            ec2_proxy.get_paginator.side_effect = get_paginator
            with patch('app.utils.dal.boto3.Session') as session:
                session.return_value.client.side_effect = lambda service, **kwargs: {'ec2': ec2_proxy, 'elbv2': elb}[service]
                application = create_app()
                from werkzeug.security import generate_password_hash
                application.config.update(DASHBOARD_USERNAME='tester', DASHBOARD_PASSWORD_HASH=generate_password_hash('test-password', method='pbkdf2:sha256:1000'))
                response = application.test_client().get('/', auth=('tester', 'test-password'))
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('i-page1', html)
            self.assertIn('i-page2', html)
            ec2_stub.assert_no_pending_responses()
            elb_stub.assert_no_pending_responses()
        ec2.close()
        elb.close()

    def test_later_page_failure_is_not_presented_as_complete_data(self):
        client = self.session.client('ec2')
        dal = DAL('us-east-1')
        dal._clients['ec2'] = client
        from botocore.exceptions import ClientError

        with Stubber(client) as stubber:
            stubber.add_response('describe_vpcs', {
                'Vpcs': [{'VpcId': 'vpc-first'}], 'NextToken': 'page2',
            }, {})
            stubber.add_client_error('describe_vpcs', service_error_code='UnauthorizedOperation',
                                    expected_params={'NextToken': 'page2'})
            with self.assertRaises(ClientError):
                dal.get_vpcs()
            stubber.assert_no_pending_responses()
        client.close()
