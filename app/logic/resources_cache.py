from concurrent.futures import ThreadPoolExecutor, wait
from threading import RLock
from time import monotonic
import logging
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError

from .resource_worker import ProcessResourcesLogic as ResourcesLogic
from ..utils.errors import CachedDataExpiredError


class ResourcesCache:
    """Bound request waits and refresh each resource section independently."""

    def __init__(self, logger=None):
        self.logger = logger if logger is not None else logging.getLogger(__name__)
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='aws-refresh')
        self.region = None
        self.logic = None
        self.entries = {}
        self.pending = {}
        self.errors = {}
        self.retry_after = {}

    def get_resources(self, region, ttl, refresh_timeout=3, failure_cooldown=10,
                      task_timeout=15, max_data_age=900):
        with self.lock:
            if self.region != region:
                self.region = region
                self.logic = ResourcesLogic(region, task_timeout=task_timeout)
                self.entries.clear()
                self.pending.clear()
                self.errors.clear()
                self.retry_after.clear()
            loaders = {
                'instance_data': self.logic.get_instances,
                'vpc_data': self.logic.get_vpcs,
                'lb_data': self.logic.get_load_balancers,
                'ami_data': self.logic.get_images,
            }
            now = monotonic()
            started = {}
            for section, loader in loaders.items():
                # A running query only suppresses another query for its own section.
                if section in self.pending:
                    continue
                if now < self.retry_after.get(section, 0):
                    continue
                entry = self.entries.get(section)
                if entry is None or entry[1] is None or now >= entry[0] or now - entry[3] >= max_data_age:
                    self.errors.pop(section, None)
                    future = self.executor.submit(loader)
                    self.pending[section] = future
                    started[section] = future
                    future.add_done_callback(
                        lambda completed, key=section: self._complete(
                            key, completed, ttl, failure_cooldown
                        )
                    )
        # Do not use an executor context manager here: shutdown would wait past
        # the request deadline. Running calls finish in this bounded shared pool.
        if started:
            done, _ = wait(started.values(), timeout=max(0, refresh_timeout))
            for section, future in started.items():
                if future in done:
                    self._complete(section, future, ttl, failure_cooldown)
        with self.lock:
            return self._snapshot(loaders, max_data_age)

    def _complete(self, section, future, ttl, failure_cooldown):
        with self.lock:
            # Ignore old region results and callbacks already processed by a caller.
            if self.pending.get(section) is not future:
                return
            self.pending.pop(section)
            try:
                data = future.result()
            except Exception as error:
                self.errors[section] = error
                # Log once per actual failed query, never when serving cached errors.
                # Do not include AWS responses, credentials, or exception messages.
                self.logger.warning(
                    'AWS resource fetch failed for %s (%s)', section, type(error).__name__
                )
                if isinstance(error, (BotoCoreError, ClientError, TimeoutError)):
                    self.retry_after[section] = monotonic() + max(0, failure_cooldown)
            else:
                fetched = monotonic()
                self.entries[section] = (
                    fetched + max(0, ttl), data, datetime.now(timezone.utc), fetched
                )
                self.errors.pop(section, None)
                self.retry_after.pop(section, None)

    def _snapshot(self, loaders, max_data_age):
        resources, errors = {'freshness': {}}, {}
        now = monotonic()
        for section in loaders:
            entry = self.entries.get(section)
            expired = entry is not None and (entry[1] is None or now - entry[3] >= max_data_age)
            resources[section] = entry[1] if entry is not None and not expired else []
            error = self.errors.get(section)
            if section in self.pending:
                error = TimeoutError('AWS refresh is still in progress')
            if error is not None:
                if not isinstance(error, (BotoCoreError, ClientError, TimeoutError)):
                    raise error
                errors[section] = error
            if expired:
                # Retain only fetch metadata; do not retain an unusable payload.
                self.entries[section] = (entry[0], None, entry[2], entry[3])
                errors[section] = CachedDataExpiredError()
            if entry is not None:
                resources['freshness'][section] = {
                    'fetched_at': entry[2].isoformat(),
                    'fetched_label': entry[2].strftime('%Y-%m-%d %H:%M:%S UTC'),
                    'age_seconds': max(0, int(now - entry[3])),
                    'stale': expired or now >= entry[0] or error is not None,
                    'expired': expired,
                }
        return resources, errors
