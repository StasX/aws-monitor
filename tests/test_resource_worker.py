import multiprocessing
import os
from threading import Event
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from botocore.exceptions import NoCredentialsError

from app.logic.resource_worker import ResourceWorker, _serve
from app.logic.resource_worker import ProcessResourcesLogic
from app.utils.errors import AWSRefreshDeadlineExceeded


def fake_aws_server(connection, region, method):
    """Run the production IPC loop with a controllable blocking AWS substitute."""
    state = {'calls': 0, 'initializations': 0}
    logic = SimpleNamespace(dal=SimpleNamespace(task_timeout=5))

    def fetch():
        if region == 'missing-credentials':
            raise NoCredentialsError()
        if logic.dal.task_timeout < 1:
            # Deliberately ignores all cooperative deadlines and never returns.
            Event().wait()
        state['calls'] += 1
        return [{'pid': os.getpid(), **state}]

    setattr(logic, method, fetch)

    def initialize(*args, **kwargs):
        state['initializations'] += 1
        return logic

    with patch('app.logic.resource_worker.ResourcesLogic', side_effect=initialize):
        _serve(connection, region, method)


class ResourceWorkerTests(unittest.TestCase):
    def make_worker(self, region='us-east-1'):
        worker = ResourceWorker(region, 'get_vpcs', target=fake_aws_server)
        self.addCleanup(worker.close)
        return worker

    def test_successful_worker_reuses_process_and_logic(self):
        worker = self.make_worker()
        first = worker.fetch(5)[0]
        second = worker.fetch(5)[0]
        self.assertEqual(first['pid'], second['pid'])
        self.assertEqual(second['calls'], 2)
        self.assertEqual(second['initializations'], 1)

    def test_hung_call_is_killed_and_next_fetch_starts_clean_worker(self):
        worker = self.make_worker()
        original_pid = worker.fetch(5)[0]['pid']
        started = monotonic()
        with self.assertRaises(AWSRefreshDeadlineExceeded):
            worker.fetch(0.15)
        self.assertLess(monotonic() - started, 2)
        self.assertNotIn(original_pid, [child.pid for child in multiprocessing.active_children()])
        recovered = worker.fetch(5)[0]
        self.assertNotEqual(recovered['pid'], original_pid)
        self.assertEqual(recovered['calls'], 1)

    def test_aws_errors_cross_process_boundary_without_recreating_worker(self):
        worker = self.make_worker('missing-credentials')
        with self.assertRaises(NoCredentialsError):
            worker.fetch(5)
        pid = worker.process.pid
        with self.assertRaises(NoCredentialsError):
            worker.fetch(5)
        self.assertEqual(worker.process.pid, pid)

    def test_close_terminates_idle_process(self):
        worker = self.make_worker()
        pid = worker.fetch(5)[0]['pid']
        worker.close()
        self.assertIsNone(worker.process)
        self.assertNotIn(pid, [child.pid for child in multiprocessing.active_children()])

    def test_process_logic_fetches_all_sections_with_isolated_workers(self):
        def make_worker(region, method):
            return ResourceWorker(region, method, target=fake_aws_server)

        with patch('app.logic.resource_worker.ResourceWorker', side_effect=make_worker):
            logic = ProcessResourcesLogic('us-east-1', task_timeout=5)
        try:
            pids = {
                getattr(logic, method)()[0]['pid']
                for method in ['get_instances', 'get_vpcs', 'get_load_balancers', 'get_images']
            }
            self.assertEqual(len(pids), 4)
        finally:
            logic.close()

    def test_worker_start_failure_is_reported_as_aws_unavailable(self):
        from botocore.exceptions import BotoCoreError

        worker = self.make_worker()
        with patch('multiprocessing.process.BaseProcess.start', side_effect=OSError('unavailable')):
            with self.assertRaises(BotoCoreError):
                worker.fetch(5)
        self.assertIsNone(worker.process)
