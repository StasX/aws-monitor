import boto3
from threading import Lock
from botocore.config import Config
from time import monotonic

from .errors import AWSRefreshDeadlineExceeded


class DAL:
    """Fetch AWS responses without depending on Flask or presentation code."""

    def __init__(self, region, task_timeout=15):
        self.region = region
        self.task_timeout = task_timeout
        self._session = None
        self._clients = {}
        self._client_lock = Lock()

    def _get_client(self, service, deadline=None):
        # Sessions and client creation are serialized; initialized clients are shared.
        acquired = self._client_lock.acquire(
            timeout=max(0, deadline - monotonic()) if deadline is not None else -1
        )
        if not acquired:
            raise AWSRefreshDeadlineExceeded('AWS client initialization deadline exceeded')
        try:
            if deadline is not None:
                self._check_deadline(deadline)
            if service in self._clients:
                return self._clients[service]
            if self._session is None:
                self._session = boto3.Session(region_name=self.region)
            if service not in self._clients:
                self._clients[service] = self._session.client(
                    service, config=Config(connect_timeout=3, read_timeout=5,
                                           retries={'mode': 'standard', 'total_max_attempts': 2})
                )
            return self._clients[service]
        finally:
            self._client_lock.release()

    @property
    def ec2_client(self):
        return self._get_client('ec2')

    @property
    def elb_client(self):
        return self._get_client('elbv2')

    def get_instances(self):
        return self._get_pages('ec2', 'describe_instances', 'Reservations')

    def get_vpcs(self):
        return self._get_pages('ec2', 'describe_vpcs', 'Vpcs')

    def get_load_balancers(self):
        return self._get_pages('elbv2', 'describe_load_balancers', 'LoadBalancers')

    def get_images(self):
        return self._get_pages('ec2', 'describe_images', 'Images', Owners=['self'])

    def _get_pages(self, service, operation, result_key, **parameters):
        deadline = monotonic() + self.task_timeout
        self._check_deadline(deadline)
        client = self._get_client(service, deadline)
        pages = iter(client.get_paginator(operation).paginate(**parameters))
        resources = []
        while True:
            self._check_deadline(deadline)
            try:
                page = next(pages)
            except StopIteration:
                return resources
            # Discard incomplete or late results instead of caching a partial list.
            self._check_deadline(deadline)
            resources.extend(page.get(result_key, []))

    @staticmethod
    def _check_deadline(deadline):
        if monotonic() >= deadline:
            raise AWSRefreshDeadlineExceeded('AWS resource refresh deadline exceeded')
