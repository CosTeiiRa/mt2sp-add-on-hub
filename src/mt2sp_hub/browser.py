"""Local browser interface; all installation decisions use the shared workflow."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
import secrets
import tempfile
from threading import BoundedSemaphore, Event, Lock, Thread
import time
import webbrowser

from .core.packages import MAX_ARCHIVE
from .core.validation import encode, identifier, parse_json
from .errors import HubError, require
from .workflow import Workflow, failure


class Session:
    """One workflow shared by tabs. Workers publish only completed snapshots."""
    def __init__(self, workflow=None):
        self.workflow = workflow or Workflow()
        self.lock = Lock()
        self.idle = Event()
        self.idle.set()
        self.revision = 0
        self.busy = self.stopped = False
        self.view = {}
        self.publish('Choose your game folder to begin.')

    def publish(self, message, error=False):
        flow = self.workflow
        status = flow.status or {}
        self.view = dict(root=str(flow.root) if flow.root else '',
                         ready=bool(status and not status.get('recovery_required')),
                         setup_ready=flow.setup_ready, kind=status.get('kind'),
                         recovery_required=bool(status.get('recovery_required')),
                         packages=[{key: row[key] for key in ('id', 'version', 'enabled')}
                                   for row in status.get('packages', [])],
                         review={'id': secrets.token_urlsafe(24), 'text': flow.review.text} if flow.review else None,
                         message=message, error=error, max_archive=MAX_ARCHIVE)

    def snapshot(self):
        with self.lock:
            return dict(deepcopy(self.view), revision=self.revision, busy=self.busy, stopped=self.stopped)

    def check(self, revision):
        require(not self.stopped, 'service_stopped', 'Hub has stopped. Start it again to continue.')
        require(not self.busy, 'operation_busy', 'Wait for the current operation to finish.')
        require(type(revision) is int and revision == self.revision, 'view_stale',
                'This view changed in another tab. Read the latest result before continuing.')

    def reserve(self, revision, message, review=None):
        with self.lock:
            self.check(revision)
            if review is not None:
                require(self.view['review'] and review == self.view['review']['id'],
                        'review_stale', 'Read the current review before confirming it.')
            self.busy = True
            self.idle.clear()
            self.revision += 1
            self.view = dict(self.view, message=message, error=False, review=None)

    def finish(self, message, error=False):
        with self.lock:
            if error:
                self.workflow.invalidate()
            self.publish(message, error)
            self.revision += 1
            self.busy = False
            self.idle.set()

    def run_reserved(self, operation):
        def work():
            try:
                message = operation()
            except Exception as exc:
                self.finish(failure(exc), True)
            else:
                self.finish(message)
        try:
            Thread(target=work, name='hub-operation', daemon=False).start()
        except Exception as exc:
            self.finish(failure(exc), True)
            raise

    def start(self, revision, operation, message='Preparing operation...', review=None):
        self.reserve(revision, message, review)
        self.run_reserved(operation)

    def stop(self, revision):
        with self.lock:
            self.check(revision)
            self.stopped = True
            self.revision += 1
            self.workflow.review = None
            self.view = dict(self.view, review=None, message='Hub stopped. You can close this tab.')


class LocalServer(ThreadingHTTPServer):
    """Fixed loopback binding, bounded requests and an ephemeral launch secret."""
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, session=None):
        self.session = session or Session()
        self.secret = secrets.token_urlsafe(32)
        self.slots = BoundedSemaphore(12)
        super().__init__(('127.0.0.1', 0), Handler)
        self.host = '127.0.0.1:{}'.format(self.server_port)
        self.origin = 'http://' + self.host
        self.url = self.origin + '/#' + self.secret

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Never log tokens, paths, package contents or raw exceptions.


class Handler(BaseHTTPRequestHandler):
    server_version = 'Hub'
    sys_version = ''
    timeout = 15

    def log_message(self, *_):
        pass

    def reply(self, status, body, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, encode({'error': 'http_request', 'message': 'Request refused.'}))

    def header(self, name):
        values = self.headers.get_all(name, [])
        require(len(values) <= 1, 'request_headers', 'Duplicate request header.')
        return values[0] if values else None

    def guard(self, api=False):
        require(self.header('Host') == self.server.host, 'request_host', 'Request host refused.')
        origin = self.header('Origin')
        require(origin in (None, self.server.origin), 'request_origin', 'Request origin refused.')
        require(self.header('Sec-Fetch-Site') in (None, 'none', 'same-origin'),
                'request_site', 'Cross-site requests are refused.')
        if api:
            token = self.header('X-Hub-Token') or ''
            require(token.isascii() and secrets.compare_digest(token, self.server.secret),
                    'session_required', 'Open the private link from your running Hub launcher.')
        if self.command == 'POST':
            require(origin == self.server.origin, 'request_origin', 'Request origin is required.')

    def do_GET(self):
        try:
            self.guard(api=self.path.startswith('/api/'))
            if self.path == '/api/state':
                self.reply(200, encode(self.server.session.snapshot()))
                return
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            require(self.path in assets, 'route_missing', 'Page not found.')
            name, content_type = assets[self.path]
            self.reply(200, files('mt2sp_hub').joinpath('web', name).read_bytes(), content_type)
        except HubError as exc:
            self.reply(404 if exc.code == 'route_missing' else 403, encode({'error': exc.code, 'message': str(exc)}))

    def length(self, limit, content_type):
        require(self.header('Transfer-Encoding') is None, 'request_encoding', 'Chunked requests are not accepted.')
        require(self.header('Content-Type') == content_type, 'request_type', 'Unexpected request type.')
        value = self.header('Content-Length') or ''
        require(value.isascii() and value.isdecimal() and len(value) < 12, 'request_length', 'A bounded body is required.')
        size = int(value)
        require(0 < size <= limit, 'request_limit', 'Request exceeds its size limit.')
        return size

    def read_body(self, size, stream=None):
        deadline = time.monotonic() + 60
        chunks = []
        while size:
            require(time.monotonic() < deadline, 'upload_timeout', 'Upload timed out. Choose the ZIP again.')
            # Return after one socket read so trickling bytes cannot indefinitely
            # reset the idle timeout inside a full-buffer read.
            block = self.rfile.read1(min(size, 65536))
            require(block, 'upload_incomplete', 'Upload was interrupted. Choose the ZIP again.')
            size -= len(block)
            if stream is None:
                chunks.append(block)
            else:
                stream.write(block)
        return b''.join(chunks)

    def revision(self):
        value = self.header('X-Hub-Revision') or ''
        require(value.isascii() and value.isdecimal() and len(value) < 20, 'view_stale', 'Check the latest view first.')
        return int(value)

    def upload(self):
        size = self.length(MAX_ARCHIVE, 'application/zip')
        session = self.server.session
        session.reserve(self.revision(), 'Receiving ZIP and preparing its review...')
        temporary = None
        try:
            temporary = tempfile.TemporaryDirectory(prefix='mt2sp-hub-upload-')
            archive = Path(temporary.name) / 'addon.zip'
            with archive.open('xb') as stream:
                self.read_body(size, stream)
        except Exception as exc:
            try:
                if temporary:
                    temporary.cleanup()
            finally:
                session.finish(failure(exc), True)
            raise

        def prepare():
            try:
                return session.workflow.prepare('add', archive)
            finally:
                temporary.cleanup()
        try:
            session.run_reserved(prepare)
        except Exception:
            temporary.cleanup()
            raise

    def action(self):
        body = parse_json(self.read_body(self.length(8192, 'application/json')), limit=8192)
        require(isinstance(body, dict), 'request_body', 'Expected an operation.')
        action = body.get('action')
        require(isinstance(action, str) and action in
                ('select', 'check', 'attach', 'recover', 'enable', 'disable', 'remove', 'confirm', 'cancel', 'stop'),
                'request_action', 'Unknown operation.')
        expected = {'action', 'value'} if action in ('select', 'enable', 'disable', 'remove') else (
            {'action', 'review'} if action == 'confirm' else {'action'})
        require(set(body) == expected, 'request_body', 'Unexpected operation fields.')
        revision = self.revision()
        session, flow = self.server.session, self.server.session.workflow
        if action == 'select':
            value = body['value']
            require(isinstance(value, str) and 0 < len(value) <= 4096 and '\x00' not in value
                    and Path(value).is_absolute(), 'folder_path', 'Paste the full game folder path.')
            operation = lambda: flow.select(value)
        elif action in ('enable', 'disable', 'remove'):
            value = identifier(body['value'])
            operation = lambda: flow.prepare(action, value)
        elif action in ('attach', 'recover'):
            operation = lambda: flow.prepare(action)
        elif action == 'confirm':
            require(isinstance(body['review'], str) and 0 < len(body['review']) <= 64,
                    'review_stale', 'Read the current review before confirming it.')
            operation = flow.confirm
        elif action == 'check':
            operation = flow.refresh
        elif action == 'cancel':
            def operation():
                flow.review = None
                return 'Review discarded. Installed add-ons have not changed.'
        else:
            session.stop(revision)
            Thread(target=self.server.shutdown, daemon=False).start()
            return
        session.start(revision, operation, review=body.get('review'))

    def do_POST(self):
        try:
            self.guard(api=True)
            if self.path == '/api/import':
                self.upload()
            elif self.path == '/api/action':
                self.action()
            else:
                raise HubError('route_missing', 'Page not found.')
            self.reply(202, encode(self.server.session.snapshot()))
        except HubError as exc:
            status = 409 if exc.code in ('view_stale', 'review_stale', 'operation_busy', 'service_stopped') else 400
            if exc.code in ('request_host', 'request_origin', 'request_site', 'session_required'):
                status = 403
            self.reply(status, encode({'error': exc.code, 'message': str(exc)}))
        except Exception as exc:
            self.reply(400, encode({'error': 'operation_failed', 'message': failure(exc)}))


def launch(root=None, *, open_browser=True):
    try:
        server = LocalServer()
    except OSError:
        print('Could not start the local Hub service. Check local network permissions and try again.')
        return 2
    with server:
        if root is not None:
            server.session.start(0, lambda: server.session.workflow.select(root), 'Checking selected folder...')
        print('Hub runs only on this computer. Keep this launcher open while using it.')
        print('Private local link (do not share): ' + server.url)
        print('Use Stop Hub in the page, or Ctrl+C here, to stop. Closing a tab does not stop an operation.')
        if open_browser:
            try:
                webbrowser.open(server.url)
            except Exception:
                print('Open the private local link above in your browser.')
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            print('\nWaiting for any active operation before stopping...')
        finally:
            server.session.idle.wait()
    return 0


def main():
    from .cli import main as cli_main
    import sys
    return cli_main(['serve', *sys.argv[1:]])
