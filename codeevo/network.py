"""Trusted reverse-proxy boundary for client address and scheme resolution."""
import ipaddress
from typing import Iterable

from starlette.requests import Request


class TrustedProxyResolver:
    def __init__(self, cidrs: Iterable[str] = ()):
        self.networks = tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in cidrs
            if value.strip()
        )

    @staticmethod
    def _address(value: str):
        try:
            return ipaddress.ip_address(value.strip())
        except ValueError:
            return None

    def is_trusted(self, value: str) -> bool:
        address = self._address(value)
        return bool(address and any(address in network for network in self.networks))

    def client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if not self.is_trusted(peer):
            return peer

        forwarded = request.headers.get("X-Forwarded-For", "")
        values = [item.strip() for item in forwarded.split(",") if item.strip()]
        if not values or any(self._address(item) is None for item in values):
            return peer

        # Walk from the nearest hop to the origin and stop at the first
        # untrusted address. This prevents a client-controlled leftmost value
        # from overriding addresses added by trusted proxies.
        for value in reversed(values):
            if not self.is_trusted(value):
                return value
        return values[0]

    def scheme(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if self.is_trusted(peer):
            value = request.headers.get("X-Forwarded-Proto", "").strip().lower()
            if value in {"http", "https"}:
                return value
        return request.url.scheme
