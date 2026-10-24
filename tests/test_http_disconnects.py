"""Fault injection for response-writing disconnect handling."""
import unittest

from scical.server.httpd import Handler


class _DisconnectedHandler:
    path = "/api/status"
    command = "GET"
    close_connection = False
    attempts = 0

    def _host_ok(self):
        return True

    def _authorised(self):
        return True

    def _api(self, path, query):
        return object()

    def _send(self, response):
        self.attempts += 1
        raise ConnectionAbortedError(10053, "client disconnected")


class DisconnectTests(unittest.TestCase):
    def test_winerror_abort_is_expected_transport_failure(self):
        handler = _DisconnectedHandler()
        Handler._handle(handler)
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.attempts, 1)

    def test_broken_pipe_and_reset_use_same_boundary(self):
        for error_type in (BrokenPipeError, ConnectionResetError):
            class Client:
                path = "/api/status"
                command = "GET"
                close_connection = False
                attempts = 0
                _host_ok = _DisconnectedHandler._host_ok
                _authorised = _DisconnectedHandler._authorised
                _api = _DisconnectedHandler._api

                def _send(self, response):
                    self.attempts += 1
                    raise error_type("socket closed")

            handler = Client()
            Handler._handle(handler)
            self.assertTrue(handler.close_connection)
            self.assertEqual(handler.attempts, 1)


if __name__ == "__main__":
    unittest.main()
