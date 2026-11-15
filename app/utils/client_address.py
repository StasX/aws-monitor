from ipaddress import ip_address, ip_network

from flask import current_app, request


def parse_trusted_proxies(value):
    try:
        return tuple(ip_network(item.strip()) for item in value.split(',') if item.strip())
    except ValueError as error:
        raise ValueError('AUTH_TRUSTED_PROXY_CIDRS must contain comma-separated IP networks') from error


def client_address():
    """Walk forwarding addresses from the trusted peer toward the client."""
    peer = request.remote_addr or 'unknown'
    networks = current_app.extensions['trusted_proxy_networks']

    def trusted(address):
        return any(address in network for network in networks)

    try:
        address = ip_address(peer)
        if not trusted(address):
            return str(address)
        # Parse the entire chain before using it; malformed headers fall back
        # to the actual peer rather than creating attacker-controlled keys.
        forwarded = [ip_address(item.strip()) for item in
                     request.headers.get('X-Forwarded-For', '').split(',')]
    except ValueError:
        return peer
    for previous in reversed(forwarded):
        if not trusted(address):
            break
        address = previous
    return str(address)
