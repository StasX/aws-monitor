import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import ANY, Mock, patch

from botocore.exceptions import NoCredentialsError

from app.logic.resources_cache import ResourcesCache
from app.utils.dal import DAL
from app.utils.errors import CachedDataExpiredError


class CacheTests(unittest.TestCase):
    def test_maximum_age_hides_and_evicts_payload_during_failure_cooldown(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                resources, _ = cache.get_resources('us-east-1', 30, max_data_age=40)
            original_time = resources['freshness']['instance_data']['fetched_at']
            logic.get_instances.side_effect = NoCredentialsError()
            with patch('app.logic.resources_cache.monotonic', return_value=131):
                cache.get_resources('us-east-1', 30, max_data_age=40)
            with patch('app.logic.resources_cache.monotonic', return_value=139):
                resources, _ = cache.get_resources('us-east-1', 30, max_data_age=40)
            self.assertEqual(resources['instance_data'], ['get_instances'])
            with patch('app.logic.resources_cache.monotonic', return_value=140):
                resources, errors = cache.get_resources('us-east-1', 30, max_data_age=40)
            self.assertEqual(resources['instance_data'], [])
            self.assertIsInstance(errors['instance_data'], CachedDataExpiredError)
            self.assertIsNone(cache.entries['instance_data'][1])
            self.assertTrue(resources['freshness']['instance_data']['expired'])
            self.assertEqual(resources['freshness']['instance_data']['fetched_at'], original_time)
            self.assertEqual(resources['vpc_data'], ['get_vpcs'])
            logic.get_instances.side_effect = None
            with patch('app.logic.resources_cache.monotonic', return_value=142):
                resources, errors = cache.get_resources('us-east-1', 30, max_data_age=40)
            self.assertEqual(resources['instance_data'], ['get_instances'])
            self.assertNotIn('instance_data', errors)
            self.assertFalse(resources['freshness']['instance_data']['expired'])

    def test_maximum_age_forces_refresh_even_with_long_cache_ttl(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                cache.get_resources('us-east-1', 300, max_data_age=10)
            with patch('app.logic.resources_cache.monotonic', return_value=110):
                cache.get_resources('us-east-1', 300, max_data_age=10)
        self.assertEqual(logic.get_instances.call_count, 2)

    def test_fetch_age_survives_failures_and_resets_on_recovery(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                resources, _ = cache.get_resources('us-east-1', 30)
            original = resources['freshness']['instance_data']
            self.assertEqual(original['age_seconds'], 0)
            self.assertFalse(original['stale'])
            self.assertTrue(original['fetched_at'].endswith('+00:00'))
            logic.get_instances.side_effect = NoCredentialsError()
            with patch('app.logic.resources_cache.monotonic', return_value=131):
                cache.get_resources('us-east-1', 30)
            with patch('app.logic.resources_cache.monotonic', return_value=135):
                resources, _ = cache.get_resources('us-east-1', 30)
            stale = resources['freshness']['instance_data']
            self.assertEqual(stale['fetched_at'], original['fetched_at'])
            self.assertEqual(stale['age_seconds'], 35)
            self.assertTrue(stale['stale'])
            self.assertEqual(resources['freshness']['vpc_data']['age_seconds'], 4)
            logic.get_instances.side_effect = None
            with patch('app.logic.resources_cache.monotonic', return_value=142):
                resources, _ = cache.get_resources('us-east-1', 30)
            self.assertEqual(resources['freshness']['instance_data']['age_seconds'], 0)
            self.assertFalse(resources['freshness']['instance_data']['stale'])

    def make_logic(self):
        logic = Mock()
        for name in ['get_instances', 'get_vpcs', 'get_load_balancers', 'get_images']:
            getattr(logic, name).return_value = [name]
        return logic

    def test_cache_expiry_reuses_logic_and_clients(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic) as factory:
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                first = cache.get_resources('us-east-1', 30)
                self.assertEqual(cache.get_resources('us-east-1', 30), first)
            logic.get_instances.assert_called_once()
            with patch('app.logic.resources_cache.monotonic', return_value=131):
                cache.get_resources('us-east-1', 30)
            self.assertEqual(logic.get_instances.call_count, 2)
            factory.assert_called_once_with('us-east-1', task_timeout=15)

    def test_failed_sections_retry_without_refetching_successes(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        logic.get_instances.side_effect = [NoCredentialsError(), ['recovered']]
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                resources, errors = cache.get_resources('us-east-1', 30)
                self.assertIn('instance_data', errors)
            with patch('app.logic.resources_cache.monotonic', return_value=109):
                for _ in range(5):
                    _, errors = cache.get_resources('us-east-1', 30)
                    self.assertIn('instance_data', errors)
                logic.get_instances.assert_called_once()
            with patch('app.logic.resources_cache.monotonic', return_value=110):
                resources, errors = cache.get_resources('us-east-1', 30)
        self.assertEqual(resources['instance_data'], ['recovered'])
        self.assertEqual(errors, {})
        self.assertNotIn('instance_data', cache.retry_after)
        logic.get_vpcs.assert_called_once()

    def test_concurrent_requests_share_one_parallel_refresh(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        barrier = Barrier(4)

        def load():
            # All four calls must be running concurrently to pass this barrier.
            barrier.wait(timeout=5)
            return ['resource']

        for name in ['get_instances', 'get_vpcs', 'get_load_balancers', 'get_images']:
            getattr(logic, name).side_effect = load
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(cache.get_resources, 'us-east-1', 30) for _ in range(2)]
                results = [future.result(timeout=10) for future in futures]
                self.assertTrue(any(not errors for _, errors in results))
        for name in ['get_instances', 'get_vpcs', 'get_load_balancers', 'get_images']:
            getattr(logic, name).assert_called_once()

    def test_repeated_failure_restarts_custom_cooldown(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        logic.get_instances.side_effect = NoCredentialsError()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            for timestamp, expected_calls in [(100, 1), (104, 1), (105, 2), (109, 2)]:
                with self.subTest(timestamp=timestamp), patch(
                    'app.logic.resources_cache.monotonic', return_value=timestamp
                ):
                    _, errors = cache.get_resources('us-east-1', 30, failure_cooldown=5)
                    self.assertIn('instance_data', errors)
                    self.assertEqual(logic.get_instances.call_count, expected_calls)

    def test_zero_failure_cooldown_allows_immediate_recovery(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        logic.get_instances.side_effect = [NoCredentialsError(), ['recovered']]
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            cache.get_resources('us-east-1', 30, failure_cooldown=0)
            resources, errors = cache.get_resources('us-east-1', 30, failure_cooldown=0)
        self.assertEqual(resources['instance_data'], ['recovered'])
        self.assertEqual(errors, {})

    def test_stale_data_is_retained_during_failure_cooldown(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                cache.get_resources('us-east-1', 30)
            logic.get_instances.side_effect = NoCredentialsError()
            with patch('app.logic.resources_cache.monotonic', return_value=131):
                cache.get_resources('us-east-1', 30)
            with patch('app.logic.resources_cache.monotonic', return_value=135):
                resources, errors = cache.get_resources('us-east-1', 30)
        self.assertEqual(resources['instance_data'], ['get_instances'])
        self.assertIn('instance_data', errors)
        self.assertEqual(logic.get_instances.call_count, 2)

    def test_region_change_clears_cached_results(self):
        cache = ResourcesCache(logger=Mock())
        with patch('app.logic.resources_cache.ResourcesLogic') as factory:
            factory.side_effect = [self.make_logic(), self.make_logic()]
            cache.get_resources('us-east-1', 30)
            cache.get_resources('eu-west-1', 30)
        self.assertEqual(factory.call_count, 2)

    def test_zero_ttl_disables_result_caching(self):
        logic = self.make_logic()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            cache = ResourcesCache(logger=Mock())
            cache.get_resources('us-east-1', 0)
            cache.get_resources('us-east-1', 0)
        self.assertEqual(logic.get_instances.call_count, 2)

    def test_clients_are_created_once_under_concurrent_access(self):
        dal = DAL('us-east-1')
        with patch('app.utils.dal.boto3.Session') as session:
            with ThreadPoolExecutor(max_workers=4) as executor:
                clients = list(executor.map(lambda _: dal.ec2_client, range(8)))
            self.assertTrue(all(client is clients[0] for client in clients))
            session.assert_called_once_with(region_name='us-east-1')
            session.return_value.client.assert_called_once_with('ec2', config=ANY)
            config = session.return_value.client.call_args.kwargs['config']
            self.assertEqual(config.connect_timeout, 3)
            self.assertEqual(config.read_timeout, 5)

    def test_slow_refresh_has_deadline_and_does_not_block_other_visitors(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        entered, release = Event(), Event()

        def slow_load():
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError('Test did not release the AWS loader')
            return ['updated']

        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            logic.get_instances.side_effect = slow_load
            try:
                with ThreadPoolExecutor(max_workers=2) as callers:
                    first = callers.submit(cache.get_resources, 'us-east-1', 30, 0.03)
                    self.assertTrue(entered.wait(timeout=1))
                    second = callers.submit(cache.get_resources, 'us-east-1', 30, 3)
                    resources, errors = second.result(timeout=0.5)
                    self.assertIsInstance(errors['instance_data'], TimeoutError)
                    resources, errors = first.result(timeout=0.5)
                    self.assertIsInstance(errors['instance_data'], TimeoutError)
                    self.assertEqual(resources['vpc_data'], ['get_vpcs'])
                    logic.get_instances.assert_called_once()
            finally:
                release.set()
                cache.executor.shutdown(wait=True)
            # A late successful response is published without another AWS call.
            resources, errors = cache.get_resources('us-east-1', 30)
            self.assertEqual(resources['instance_data'], ['updated'])
            self.assertEqual(errors, {})

    def test_expired_data_remains_available_during_refresh(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        release = Event()
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            with patch('app.logic.resources_cache.monotonic', return_value=100):
                cache.get_resources('us-east-1', 30)
            logic.get_instances.side_effect = lambda: release.wait(timeout=5) and ['updated']
            try:
                with patch('app.logic.resources_cache.monotonic', return_value=131):
                    resources, errors = cache.get_resources('us-east-1', 30, 0.01)
                self.assertEqual(resources['instance_data'], ['get_instances'])
                self.assertIsInstance(errors['instance_data'], TimeoutError)
            finally:
                release.set()
                cache.executor.shutdown(wait=True)


    def test_pending_section_does_not_block_other_sections(self):
        cache = ResourcesCache(logger=Mock())
        logic = self.make_logic()
        release = Event()

        def slow_load():
            if not release.wait(timeout=5):
                raise AssertionError('Test did not release AWS loader')
            return ['instances']

        logic.get_instances.side_effect = slow_load
        logic.get_vpcs.side_effect = [NoCredentialsError(), ['recovered VPCs'], ['new VPCs']]
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            try:
                with patch('app.logic.resources_cache.monotonic', return_value=100):
                    resources, errors = cache.get_resources('us-east-1', 30, 0.1)
                self.assertIn('instance_data', errors)
                self.assertIn('vpc_data', errors)
                self.assertEqual(resources['ami_data'], ['get_images'])
                # A failed section retries after its cooldown, despite pending EC2.
                with patch('app.logic.resources_cache.monotonic', return_value=111):
                    resources, errors = cache.get_resources('us-east-1', 30)
                self.assertEqual(resources['vpc_data'], ['recovered VPCs'])
                self.assertNotIn('vpc_data', errors)
                logic.get_images.assert_called_once()
                # Healthy sections refresh after expiry, still without duplicating EC2.
                with patch('app.logic.resources_cache.monotonic', return_value=142):
                    resources, errors = cache.get_resources('us-east-1', 30)
                self.assertEqual(resources['vpc_data'], ['new VPCs'])
                self.assertEqual(logic.get_images.call_count, 2)
                self.assertEqual(logic.get_load_balancers.call_count, 2)
                logic.get_instances.assert_called_once()
                self.assertIn('instance_data', errors)
            finally:
                release.set()
                cache.executor.shutdown(wait=True)

    def test_failure_after_request_deadline_is_logged_once(self):
        logger = Mock()
        cache = ResourcesCache(logger=logger)
        logic = self.make_logic()
        release = Event()

        def fail_later():
            if not release.wait(timeout=5):
                raise AssertionError('Test did not release AWS loader')
            raise NoCredentialsError()

        logic.get_instances.side_effect = fail_later
        with patch('app.logic.resources_cache.ResourcesLogic', return_value=logic):
            try:
                cache.get_resources('us-east-1', 30, refresh_timeout=0.01)
                logger.warning.assert_not_called()
            finally:
                release.set()
                cache.executor.shutdown(wait=True)
            logger.warning.assert_called_once_with(
                'AWS resource fetch failed for %s (%s)', 'instance_data', 'NoCredentialsError'
            )
            # Cached display cannot duplicate the background completion log.
            cache.get_resources('us-east-1', 30)
            self.assertEqual(logger.warning.call_count, 1)
