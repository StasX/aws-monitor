from os import environ
from time import perf_counter

from flask import g, request
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, multiprocess


class RequestMetrics:
    def __init__(self, application):
        self.registry = CollectorRegistry()
        self.requests = Counter(
            'aws_monitor_http_requests_total', 'Completed HTTP requests.',
            ['method', 'route', 'status'], registry=self.registry,
        )
        self.duration = Histogram(
            'aws_monitor_http_request_duration_seconds', 'HTTP request duration in seconds.',
            ['method', 'route'], registry=self.registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
        )
        # Publish useful zero-valued series even before the first health check.
        self.requests.labels('GET', '/health', '200')
        self.duration.labels('GET', '/health')
        application.before_request(self.start_request)
        application.after_request(self.finish_request)

    @staticmethod
    def start_request():
        g.metrics_started = perf_counter()

    def finish_request(self, response):
        # Scrapes do not count themselves. Route templates and bounded methods
        # avoid labels containing arbitrary URLs, resource names, or credentials.
        if request.endpoint != 'monitoring_view.metrics':
            route = request.url_rule.rule if request.url_rule else 'unmatched'
            method = request.method if request.method in {
                'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT'
            } else 'OTHER'
            self.requests.labels(method, route, str(response.status_code)).inc()
            self.duration.labels(method, route).observe(perf_counter() - g.metrics_started)
        return response

    def render(self):
        if environ.get('PROMETHEUS_MULTIPROC_DIR'):
            # A fresh registry avoids exposing the local worker twice.
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
        else:
            registry = self.registry
        return generate_latest(registry)
