import atexit
import multiprocessing
from threading import Event, Lock, Timer
from time import monotonic

from botocore.exceptions import BotoCoreError, ClientError

from .resources_logic import ResourcesLogic
from ..utils.errors import AWSRefreshDeadlineExceeded


def _serve(connection, region, method):
    """Keep clients inside their owning process, never share sessions over IPC."""
    logic = None
    try:
        while True:
            budget = connection.recv()
            try:
                if logic is None:
                    logic = ResourcesLogic(region, task_timeout=budget)
                logic.dal.task_timeout = budget
                data = getattr(logic, method)()
            except (BotoCoreError, ClientError, TimeoutError) as error:
                connection.send(('error', error))
            except Exception:
                connection.send(('error', RuntimeError('Unexpected AWS worker failure')))
            else:
                connection.send(('ok', data))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class ResourceWorker:
    """One reusable process with a killable deadline for each resource query."""

    def __init__(self, region, method, target=_serve):
        self.region = region
        self.method = method
        self.target = target
        self.lock = Lock()
        self.process = None
        self.connection = None
        atexit.register(self.close)

    def fetch(self, budget):
        with self.lock:
            deadline = monotonic() + budget
            if self.process is None or not self.process.is_alive():
                self._stop()
                context = multiprocessing.get_context('spawn')
                self.connection, child = context.Pipe()
                self.process = context.Process(
                    target=self.target, args=(child, self.region, self.method), daemon=True
                )
                try:
                    self.process.start()
                except OSError as error:
                    self._stop()
                    raise BotoCoreError() from error
                finally:
                    child.close()
            process = self.process
            expired = Event()

            def terminate_on_deadline():
                expired.set()
                try:
                    if process.is_alive():
                        process.kill()
                except (OSError, ValueError):
                    pass

            timer = Timer(max(0, deadline - monotonic()), terminate_on_deadline)
            timer.daemon = True
            timer.start()
            try:
                self.connection.send(budget)
                if not self.connection.poll(max(0, deadline - monotonic())):
                    raise AWSRefreshDeadlineExceeded('AWS worker deadline exceeded')
                status, result = self.connection.recv()
                if expired.is_set() or monotonic() >= deadline:
                    raise AWSRefreshDeadlineExceeded('AWS worker deadline exceeded')
            except (EOFError, BrokenPipeError, OSError) as error:
                self._stop()
                if expired.is_set() or monotonic() >= deadline:
                    raise AWSRefreshDeadlineExceeded('AWS worker deadline exceeded') from None
                raise BotoCoreError() from error
            except AWSRefreshDeadlineExceeded:
                self._stop()
                raise
            finally:
                timer.cancel()
                timer.join()
            if status == 'error':
                raise result
            return result

    def _stop(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.kill()
            if self.process.pid is not None:
                self.process.join(timeout=1)
            if not self.process.is_alive():
                self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def close(self):
        with self.lock:
            self._stop()


class ProcessResourcesLogic:
    def __init__(self, region, task_timeout=15):
        self.task_timeout = task_timeout
        self.workers = {
            method: ResourceWorker(region, method)
            for method in ['get_instances', 'get_vpcs', 'get_load_balancers', 'get_images']
        }

    def get_instances(self):
        return self.workers['get_instances'].fetch(self.task_timeout)

    def get_vpcs(self):
        return self.workers['get_vpcs'].fetch(self.task_timeout)

    def get_load_balancers(self):
        return self.workers['get_load_balancers'].fetch(self.task_timeout)

    def get_images(self):
        return self.workers['get_images'].fetch(self.task_timeout)

    def close(self):
        for worker in self.workers.values():
            worker.close()
