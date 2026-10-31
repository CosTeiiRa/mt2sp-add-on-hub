"""Real loopback HTTP tests with invented packages and disposable installations."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from helpers import package
from mt2sp_hub.browser import LocalServer, Session
from mt2sp_hub.core.packages import MAX_ARCHIVE
from mt2sp_hub.errors import HubError
from mt2sp_hub.installation.manager import Manager, initialize


class BrowserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'practice'
        initialize(self.root)
        self.server = LocalServer()
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.assertTrue(self.server.session.idle.wait(5))

    def call(self, method='GET', path='/api/state', body=None, headers=None, auth=True):
        supplied = {'Origin': self.server.origin}
        if auth:
            supplied['X-Hub-Token'] = self.server.secret
        if method == 'POST':
            supplied.update({'Content-Type': 'application/json',
                             'X-Hub-Revision': str(self.server.session.snapshot()['revision'])})
        supplied.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), raw
        finally:
            connection.close()

    def action(self, action, value=None, headers=None, wait=True):
        body = {'action': action}
        if value is not None:
            body['value'] = str(value)
        if action == 'confirm':
            body['review'] = self.server.session.snapshot()['review']['id']
        status, _, raw = self.call('POST', '/api/action', json.dumps(body), headers)
        self.assertEqual(status, 202, raw)
        if wait:
            self.assertTrue(self.server.session.idle.wait(10))
        return self.server.session.snapshot()

    def upload(self, raw, headers=None):
        status, _, result = self.call('POST', '/api/import', raw,
                                     {'Content-Type': 'application/zip', **(headers or {})})
        self.assertEqual(status, 202, result)
        self.assertTrue(self.server.session.idle.wait(10))
        return self.server.session.snapshot()

    def test_loopback_assets_have_no_secret_paths_or_external_dependencies(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for path in ('/', '/app.js', '/style.css'):
            status, headers, raw = self.call(path=path, auth=False)
            self.assertEqual(status, 200)
            self.assertNotIn(self.server.secret.encode(), raw)
            self.assertNotIn(str(self.root).encode(), raw)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
            self.assertEqual(headers['X-Frame-Options'], 'DENY')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        for path in ('/../pyproject.toml', '/%2e%2e/pyproject.toml', '/api/action', '/?token=guess'):
            self.assertEqual(self.call(path=path)[0], 404)

    def test_api_requires_secret_exact_host_and_same_origin(self):
        self.action('select', self.root)
        for headers, auth in (({}, False), ({'X-Hub-Token': 'wrong'}, True),
                              ({'Host': 'attacker.invalid'}, True),
                              ({'Origin': 'https://attacker.invalid'}, True),
                              ({'Origin': 'null'}, True), ({'Sec-Fetch-Site': 'cross-site'}, True)):
            status, _, raw = self.call(headers=headers, auth=auth)
            self.assertEqual(status, 403)
            self.assertNotIn(str(self.root).encode(), raw)
        self.assertEqual(self.call('OPTIONS', '/api/action')[0], 501)
        self.assertEqual(self.call('POST', '/api/action', b'{"action":"check"}', auth=False)[0], 403)
        self.assertEqual(self.call('POST', '/api/action', b'{"action":"check"}',
                                  {'Origin': ''})[0], 403)
        self.assertEqual(self.server.session.snapshot()['revision'], 2)

    def test_duplicate_headers_simple_forms_and_unbounded_bodies_are_refused(self):
        for headers in ({'Content-Type': 'text/plain'}, {'Content-Length': '9000'},
                        {'Transfer-Encoding': 'chunked'}, {'Content-Length': '-1'},
                        {'Content-Length': '999999999999999999999'}):
            self.assertEqual(self.call('POST', '/api/action', b'{}', headers)[0], 400)
        self.assertEqual(self.call('POST', '/api/import', b'',
                                  {'Content-Type': 'application/zip', 'Content-Length': str(MAX_ARCHIVE + 1)})[0], 400)
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.putrequest('GET', '/api/state')
            connection.putheader('Host', self.server.host)  # Duplicate the automatic Host.
            connection.putheader('X-Hub-Token', self.server.secret)
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.server.session.snapshot()['revision'], 0)

    def test_invalid_actions_and_fields_never_reach_the_engine(self):
        invalid = ['[]', '{"action":"check","action":"stop"}', '{"action":[]}',
                   '{"action":"shell","value":"example"}', '{"action":"check","extra":true}',
                   '{"action":"select","value":"relative/path"}',
                   '{"action":"remove","value":"--help"}']
        for body in invalid:
            self.assertEqual(self.call('POST', '/api/action', body)[0], 400, body)
        self.assertEqual(self.call('POST', '/api/action', '{"action":"confirm","review":null}')[0], 409)
        self.assertEqual(self.server.session.snapshot()['revision'], 0)

    def test_full_http_lifecycle_reviews_before_mutation_and_preserves_disabled_updates(self):
        self.action('select', self.root)
        state = self.upload(package().raw)
        self.assertIn('not installed -> 1.0.0 (enabled)', state['review']['text'])
        self.assertEqual(Manager(self.root).status()['packages'], [])
        self.action('cancel')
        self.assertEqual(Manager(self.root).status()['packages'], [])
        self.upload(package().raw)
        self.action('confirm')
        self.action('disable', 'example.one')
        self.action('confirm')
        state = self.upload(package(version='1.1.0').raw)
        self.assertIn('1.0.0 (disabled) -> 1.1.0 (disabled)', state['review']['text'])
        self.action('confirm')
        self.assertFalse(Manager(self.root).status()['packages'][0]['enabled'])
        self.action('enable', 'example.one')
        self.action('confirm')
        self.assertEqual((self.root / 'client/message.txt').read_bytes(), b'invented client data')
        self.action('remove', 'example.one')
        self.action('confirm')
        self.assertEqual(Manager(self.root).status()['packages'], [])
        self.assertFalse((self.root / 'client/message.txt').exists())

    def test_stale_tab_cannot_change_folder_confirm_new_review_or_replay(self):
        self.action('select', self.root)
        old = self.upload(package().raw)
        self.action('cancel')
        new = self.upload(package(version='1.1.0').raw)
        body = json.dumps({'action': 'confirm', 'review': old['review']['id']})
        self.assertEqual(self.call('POST', '/api/action', body,
                                  {'X-Hub-Revision': str(old['revision'])})[0], 409)
        self.assertEqual(self.call('POST', '/api/action', body)[0], 409)
        self.assertEqual(self.server.session.snapshot()['review'], new['review'])
        state = self.action('confirm')
        self.assertEqual(state['packages'][0]['version'], '1.1.0')
        body = json.dumps({'action': 'confirm', 'review': new['review']['id']})
        self.assertEqual(self.call('POST', '/api/action', body,
                                  {'X-Hub-Revision': str(new['revision'])})[0], 409)
        self.assertEqual(Manager(self.root).status()['generation'], 1)

    def test_busy_operation_keeps_state_readable_and_blocks_stop_or_other_tab(self):
        gate = Event()
        self.addCleanup(gate.set)
        self.server.session.start(0, lambda: gate.wait(5) and 'Finished.')
        status, _, raw = self.call()
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)['busy'])
        for action in ('stop', 'check', 'cancel'):
            self.assertEqual(self.call('POST', '/api/action', json.dumps({'action': action}))[0], 409)
        self.assertEqual(self.call('POST', '/api/import', package().raw,
                                  {'Content-Type': 'application/zip'})[0], 409)
        gate.set()
        self.assertTrue(self.server.session.idle.wait(5))
        self.assertFalse(self.server.session.snapshot()['busy'])

    def test_failed_and_interrupted_uploads_clear_busy_and_remove_temporary_zip(self):
        self.action('select', self.root)
        upload_root = self.root.parent / 'uploads'
        upload_root.mkdir()
        with patch('tempfile.tempdir', str(upload_root)):
            self.assertTrue(self.upload(b'not a ZIP')['error'])
            self.assertEqual(list(upload_root.iterdir()), [])
            self.action('check')
            connection = socket.create_connection(self.server.server_address, timeout=5)
            try:
                headers = ('POST /api/import HTTP/1.0\r\nHost: {}\r\nOrigin: {}\r\n'
                           'X-Hub-Token: {}\r\nX-Hub-Revision: {}\r\n'
                           'Content-Type: application/zip\r\nContent-Length: 100\r\n\r\npartial').format(
                               self.server.host, self.server.origin, self.server.secret,
                               self.server.session.snapshot()['revision'])
                connection.sendall(headers.encode())
                connection.shutdown(socket.SHUT_WR)
                self.assertIn(b'400', connection.recv(8192))
            finally:
                connection.close()
            self.assertTrue(self.server.session.idle.wait(5))
            self.assertTrue(self.server.session.snapshot()['error'])
            self.assertEqual(list(upload_root.iterdir()), [])
        self.assertEqual(Manager(self.root).status()['packages'], [])

    def test_reopened_session_recovers_actual_interrupted_transaction(self):
        def fail(step):
            if step == 'file:client/message.txt':
                raise OSError('invented interruption')
        manager = Manager(self.root, checkpoint=fail)
        with self.assertRaises(OSError):
            manager.apply(manager.plan([package()])['plan'])
        state = self.action('select', self.root)
        self.assertTrue(state['recovery_required'])
        self.assertTrue(self.upload(package().raw)['error'])
        self.action('recover')
        self.assertTrue(Manager(self.root).status()['recovery_required'])
        state = self.action('confirm')
        self.assertIn('Previous deployment restored.', state['message'])
        self.assertFalse(state['recovery_required'])
        self.assertFalse((self.root / 'client/message.txt').exists())

    def test_upload_cleanup_failure_still_releases_busy_state(self):
        self.action('select', self.root)
        temporary = Mock()
        temporary.name = str(self.root.parent / 'blocked-upload')
        Path(temporary.name).mkdir()
        temporary.cleanup.side_effect = OSError('invented-private-detail')
        with patch('mt2sp_hub.browser.tempfile.TemporaryDirectory', return_value=temporary), \
                patch('mt2sp_hub.browser.Handler.read_body', side_effect=OSError('interrupted upload')):
            status, _, raw = self.call('POST', '/api/import', b'partial', {'Content-Type': 'application/zip'})
        self.assertEqual(status, 400)
        self.assertNotIn(b'invented-private-detail', raw)
        self.assertTrue(self.server.session.idle.wait(5))
        self.assertFalse(self.server.session.snapshot()['busy'])
        self.assertTrue(self.server.session.snapshot()['error'])

    def test_unexpected_worker_error_is_redacted_and_stop_is_explicit(self):
        self.action('select', self.root)
        with patch.object(self.server.session.workflow, 'refresh', side_effect=OSError('invented-private-detail')):
            state = self.action('check')
        self.assertTrue(state['error'])
        self.assertNotIn('invented-private-detail', json.dumps(state))
        self.assertFalse(state['ready'])
        state = self.action('stop')
        self.assertTrue(state['stopped'])
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def test_worker_start_failure_does_not_leave_operation_busy(self):
        session = Session()
        with patch('mt2sp_hub.browser.Thread.start', side_effect=RuntimeError('invented-private-detail')):
            with self.assertRaises(RuntimeError):
                session.start(0, lambda: 'unused')
        self.assertTrue(session.idle.is_set())
        self.assertFalse(session.snapshot()['busy'])
        self.assertNotIn('invented-private-detail', session.snapshot()['message'])


if __name__ == '__main__':
    unittest.main()
