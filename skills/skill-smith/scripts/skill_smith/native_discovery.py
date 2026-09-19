"""One bounded Codex skills/list exchange, owned by llmcall's Windows Job.

No model or provider interface is used. The only outbound methods are initialize,
initialized and skills/list. Raw diagnostics never leave this process owner.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from queue import Empty, Full, Queue
import subprocess
import sys
from threading import Event, Thread
import time


class NativeDiscoveryError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate(config):
    fields = {'enabled', 'executable', 'codex_home', 'cwd', 'timeout_seconds', 'max_output_bytes'}
    if not isinstance(config, dict) or set(config) - fields or type(config.get('enabled')) is not bool:
        raise NativeDiscoveryError('invalid_config')
    required = {'executable', 'codex_home', 'cwd'}
    if config['enabled'] and not required <= config.keys():
        raise NativeDiscoveryError('invalid_config')
    result = dict(config)
    for key in required & config.keys():
        value = config[key]
        if not isinstance(value, str) or not value or len(value) > 32768 or '\x00' in value or not Path(value).is_absolute():
            raise NativeDiscoveryError('invalid_config')
        try:
            path = Path(value).resolve(strict=True)
            if key == 'executable':
                valid = path.is_file() and path.name.lower() == 'codex.exe'
            else:
                valid = path.is_dir()
        except (OSError, ValueError, RuntimeError):
            valid = False
        if not valid:
            raise NativeDiscoveryError('invalid_config')
        result[key] = str(path)
    timeout = config.get('timeout_seconds', 20)
    limit = config.get('max_output_bytes', 4 * 1024 * 1024)
    if (type(timeout) not in (int, float) or not 1 <= timeout <= 60
            or type(limit) is not int or not 1024 <= limit <= 16 * 1024 * 1024):
        raise NativeDiscoveryError('invalid_config')
    result.update(timeout_seconds=timeout, max_output_bytes=limit)
    return result


class _Exchange:
    """Bounded binary pipe workers; the supervisor alone owns process cleanup."""
    def __init__(self, child, limit):
        self.child, self.limit = child, limit
        self.responses = Queue(maxsize=128)
        self.outbound = Queue(maxsize=3)
        self.stopping, self.failed = Event(), Event()
        self.error = None
        self.workers = []

    def fail(self, code):
        if not self.failed.is_set():
            self.error = code
            self.failed.set()

    def read(self, stream, protocol):
        total, pending = 0, bytearray()
        try:
            while True:
                block = stream.read(min(16384, self.limit + 1))
                if not block:
                    if pending:
                        self.fail('invalid_protocol')
                    return
                total += len(block)
                if total > self.limit:
                    self.fail('output_limit')
                    return
                if protocol:
                    pending.extend(block)
                    while b'\n' in pending:
                        line, _, rest = pending.partition(b'\n')
                        pending = bytearray(rest)
                        row = json.loads(line.decode('utf-8'))
                        if not isinstance(row, dict):
                            raise ValueError('not an object')
                        self.responses.put_nowait((row, datetime.now(timezone.utc).isoformat()))
        except Full:
            self.fail('output_limit')
        except (ValueError, UnicodeError, RecursionError):
            self.fail('invalid_protocol')
        except Exception:
            self.fail('io_failed')

    def write(self):
        try:
            while not self.stopping.is_set():
                try:
                    payload = self.outbound.get(timeout=.02)
                except Empty:
                    continue
                view = memoryview(payload)
                while view:
                    count = self.child.stdin.write(view)
                    if not count:
                        raise OSError('incomplete write')
                    view = view[count:]
                self.child.stdin.flush()
        except Exception:
            if not self.stopping.is_set():
                self.fail('io_failed')

    def start(self):
        for target, args in ((self.read, (self.child.stdout, True)),
                             (self.read, (self.child.stderr, False)), (self.write, ())):
            worker = Thread(target=target, args=args, daemon=True, name='catalog-native-io')
            worker.start()
            self.workers.append(worker)

    def send(self, method, params, identity=None):
        row = {'method': method, 'params': params}
        if identity is not None:
            row['id'] = identity
        self.outbound.put_nowait((json.dumps(row, ensure_ascii=True) + '\n').encode('utf-8'))

    def result(self, identity, deadline, control):
        while True:
            if self.failed.is_set():
                raise NativeDiscoveryError(self.error)
            if control.is_set():
                raise NativeDiscoveryError('cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeDiscoveryError('timeout')
            try:
                row, captured = self.responses.get(timeout=min(.02, remaining))
            except Empty:
                if self.child.poll() is not None:
                    raise NativeDiscoveryError('process_exited')
                continue
            if 'method' in row:
                if 'id' in row or not isinstance(row['method'], str):
                    raise NativeDiscoveryError('invalid_protocol')
                continue  # Notifications require no response and prove no discovery.
            if type(row.get('id')) is not int or row['id'] != identity:
                raise NativeDiscoveryError('invalid_protocol')
            if 'error' in row:
                raise NativeDiscoveryError('rpc_error')
            if not isinstance(row.get('result'), dict):
                raise NativeDiscoveryError('invalid_protocol')
            return {'result': row['result'], 'observed_at': captured}

    def finish(self, deadline):
        self.stopping.set()
        for worker in self.workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in self.workers):
            return False
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            stream.close()
        return True


def acquire(config):
    """Return a timestamped skills/list result, or a fixed, non-secret error code."""
    config = validate(config)
    if not config['enabled']:
        return None
    if sys.platform != 'win32':
        raise NativeDiscoveryError('unsupported_platform')
    try:
        from llmcall import process
        budget = process.remaining_timeout(config['timeout_seconds'])
        control = process.current_control()
        if not callable(process.WindowsJob) or not callable(process.current_context):
            raise AttributeError('missing process owner API')
    except (ImportError, AttributeError):
        raise NativeDiscoveryError('process_owner_unavailable') from None
    if control.is_set():
        raise NativeDiscoveryError('cancelled')
    if budget <= 0:
        raise NativeDiscoveryError('timeout')
    deadline = time.monotonic() + budget
    execution_deadline = deadline - min(2, budget * .2)
    job, child, exchange, capture = None, None, None, None
    error, cleanup_failed = None, False
    try:
        job = process.WindowsJob()
        env = dict(process.current_context().env)
        env.update(CODEX_HOME=config['codex_home'], RUST_LOG='off')
        command = [config['executable'], 'app-server', '--strict-config',
                   '-c', 'check_for_update_on_startup=false', '-c', 'analytics.enabled=false']
        if control.is_set():
            raise NativeDiscoveryError('cancelled')
        if time.monotonic() >= execution_deadline:
            raise NativeDiscoveryError('timeout')
        child = job.spawn(command, cwd=config['cwd'], env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, creationflags=0x08000004)
        if control.is_set():
            raise NativeDiscoveryError('cancelled')
        if time.monotonic() >= execution_deadline:
            raise NativeDiscoveryError('timeout')
        exchange = _Exchange(child, config['max_output_bytes'])
        exchange.start()
        job.start(child)
        exchange.send('initialize', {'clientInfo': {'name': 'skill_smith_catalog', 'version': '1'}}, 1)
        exchange.result(1, execution_deadline, control)
        exchange.send('initialized', {})
        exchange.send('skills/list', {'cwds': [config['cwd']], 'forceReload': True}, 2)
        capture = exchange.result(2, execution_deadline, control)
    except NativeDiscoveryError as exc:
        error = exc.code
    except Exception:
        error = 'io_failed' if exchange is not None else 'launch_failed'
    finally:
        if exchange is not None:
            exchange.stopping.set()
        try:
            if job is not None:
                job.close()
        except Exception:
            cleanup_failed = True
        if child is not None:
            try:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except Exception:
                cleanup_failed = True
            try:
                if exchange is not None:
                    if not exchange.finish(deadline):
                        cleanup_failed = True
                else:
                    for stream in (child.stdin, child.stdout, child.stderr):
                        stream.close()
            except Exception:
                cleanup_failed = True
    if cleanup_failed:
        raise NativeDiscoveryError('cleanup_failed')
    if error:
        raise NativeDiscoveryError(error)
    if exchange.failed.is_set():
        raise NativeDiscoveryError(exchange.error)
    if control.is_set():
        raise NativeDiscoveryError('cancelled')
    if time.monotonic() >= deadline:
        raise NativeDiscoveryError('timeout')
    return capture
