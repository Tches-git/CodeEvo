import json
import logging
import unittest

from starlette.requests import Request

from codeevo.logging_config import JsonFormatter
from codeevo.network import TrustedProxyResolver
from codeevo.observability import trace_id_var


def make_request(peer: str, headers=None, scheme: str = "http") -> Request:
    raw_headers = [
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": raw_headers,
        "client": (peer, 12345),
        "server": ("codeevo", 8080),
    })


class TrustedProxyTests(unittest.TestCase):
    def test_untrusted_peer_cannot_spoof_client_or_scheme(self):
        resolver = TrustedProxyResolver(("10.0.0.0/8",))
        request = make_request("192.0.2.10", {
            "X-Forwarded-For": "198.51.100.8",
            "X-Forwarded-Proto": "https",
        })

        self.assertEqual("192.0.2.10", resolver.client_ip(request))
        self.assertEqual("http", resolver.scheme(request))

    def test_trusted_chain_returns_nearest_untrusted_origin(self):
        resolver = TrustedProxyResolver(("10.0.0.0/8",))
        request = make_request("10.0.0.2", {
            "X-Forwarded-For": "203.0.113.20, 198.51.100.7, 10.0.0.3",
            "X-Forwarded-Proto": "https",
        })

        self.assertEqual("198.51.100.7", resolver.client_ip(request))
        self.assertEqual("https", resolver.scheme(request))

    def test_invalid_forwarded_chain_is_ignored(self):
        resolver = TrustedProxyResolver(("10.0.0.0/8",))
        request = make_request("10.0.0.2", {
            "X-Forwarded-For": "203.0.113.20, not-an-ip",
        })

        self.assertEqual("10.0.0.2", resolver.client_ip(request))


class StructuredLoggingTests(unittest.TestCase):
    def test_json_formatter_emits_only_allowlisted_context(self):
        formatter = JsonFormatter()
        record = logging.getLogger("codeevo.test").makeRecord(
            "codeevo.test",
            logging.INFO,
            __file__,
            1,
            "request.completed",
            (),
            None,
            extra={
                "request_id": "request-1",
                "status": 200,
                "password": "do-not-log-this",
            },
        )
        token = trace_id_var.set("trace-1")
        try:
            payload = json.loads(formatter.format(record))
        finally:
            trace_id_var.reset(token)

        self.assertEqual("request-1", payload["request_id"])
        self.assertEqual("trace-1", payload["trace_id"])
        self.assertNotIn("password", payload)
        self.assertNotIn("do-not-log-this", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
