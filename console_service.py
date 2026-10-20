"""Per-browser SSH sessions with cancellable handshakes and bounded capacity."""
import codecs
import socket
import threading
import time
import uuid


class ConsoleSessions:
    def __init__(self, client_factory, emit, max_sessions=16):
        self.client_factory = client_factory
        self.emit = emit
        self.lock = threading.RLock()
        self.sessions = {}
        self.capacity = threading.BoundedSemaphore(max_sessions)

    def connect(self, sid, vps_id, endpoint, username, password, attempt_id='', cols=100, rows=28, private_key=None):
        self.close(sid)
        if not self.capacity.acquire(blocking=False):
            self.emit('ssh_error', {'error': 'Console capacity reached. Try again shortly.', 'attempt_id': attempt_id}, room=sid)
            return False
        info = dict(token=uuid.uuid4().hex, vps_id=vps_id, attempt_id=attempt_id,
                    client=None, channel=None, last_activity=time.monotonic())
        with self.lock:
            self.sessions[sid] = info
        threading.Thread(target=self._open, args=(sid, info, endpoint, username, password, cols, rows, private_key), daemon=True).start()
        return True

    def _current(self, sid, info):
        with self.lock:
            return self.sessions.get(sid) is info

    def _event(self, event, sid, info, **data):
        if self._current(sid, info):
            self.emit(event, dict(vps_id=info['vps_id'], attempt_id=info['attempt_id'], **data), room=sid)

    def _open(self, sid, info, endpoint, username, password, cols, rows, private_key=None):
        client = channel = None
        try:
            client = self.client_factory()
            with self.lock:
                if not self._current(sid, info):
                    return
                info['client'] = client
            key = parse_private_key(private_key, password) if private_key else None
            private_key = None
            auth = {'pkey':key} if key else {'password':password}
            client.connect(hostname=endpoint['host'], port=int(endpoint['port']),
                           username=username, **auth, timeout=12,
                           auth_timeout=12, banner_timeout=12,
                           allow_agent=False, look_for_keys=False)
            password = key = auth = None
            if not self._current(sid, info):
                return
            transport = client.get_transport()
            if transport:
                transport.set_keepalive(25)
            channel = client.invoke_shell(term='xterm-256color', width=max(20, min(int(cols), 300)), height=max(5, min(int(rows), 150)))
            channel.settimeout(.5)
            info['channel'] = channel
            self._event('ssh_connected', sid, info, host=endpoint['host'], port=endpoint['port'], username=username)
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while self._current(sid, info) and not channel.closed:
                if time.monotonic() - info['last_activity'] > 3600:
                    self._event('ssh_error', sid, info, error='Session ended after one hour without keyboard input.')
                    break
                try:
                    data = channel.recv(8192)
                    if not data:
                        break
                    text = decoder.decode(data)
                    if text:
                        self._event('ssh_output', sid, info, data=text)
                except socket.timeout:
                    continue
        except Exception as exc:
            name = type(exc).__name__
            if isinstance(exc, ValueError):
                message = 'Private key could not be read. Use an OpenSSH/PEM private key and its passphrase if encrypted.'
            elif 'Authentication' in name:
                message = 'SSH rejected these credentials. Check the guest username, password, and SSH authentication policy.'
            elif isinstance(exc, (socket.timeout, TimeoutError)):
                message = 'SSH timed out. Check the guest SSH service and node firewall.'
            else:
                message = 'Could not open SSH. Check that the VPS is running and SSH is available on its forwarded port.'
            self._event('ssh_error', sid, info, error=message)
        finally:
            password = private_key = key = auth = None
            for resource in (channel, client):
                if resource:
                    try:
                        resource.close()
                    except Exception:
                        pass
            with self.lock:
                if self.sessions.get(sid) is info:
                    self.emit('ssh_disconnected', {'vps_id': info['vps_id'], 'attempt_id': info['attempt_id']}, room=sid)
                    self.sessions.pop(sid, None)
            self.capacity.release()

    def input(self, sid, vps_id, data):
        with self.lock:
            info = self.sessions.get(sid)
            if not info or info['vps_id'] != vps_id or not info.get('channel'):
                return False
            channel = info['channel']
            info['last_activity'] = time.monotonic()
        if not isinstance(data, str) or len(data.encode('utf-8')) > 65536:
            return False
        try:
            channel.sendall(data.encode('utf-8'))
            return True
        except Exception:
            self.close(sid)
            return False

    def resize(self, sid, vps_id, cols, rows):
        with self.lock:
            info = self.sessions.get(sid)
            channel = info.get('channel') if info and info['vps_id'] == vps_id else None
        try:
            if channel:
                channel.resize_pty(width=max(20, min(int(cols), 300)), height=max(5, min(int(rows), 150)))
        except (ValueError, TypeError, OSError):
            pass

    def close(self, sid, vps_id=None):
        with self.lock:
            info = self.sessions.get(sid)
            if not info or (vps_id is not None and info['vps_id'] != vps_id):
                return
            self.sessions.pop(sid, None)
        for key in ('channel', 'client'):
            if info.get(key):
                try:
                    info[key].close()
                except Exception:
                    pass


def parse_private_key(value, passphrase=None):
    import io
    import paramiko
    if not isinstance(value,str) or not 20<len(value)<=32768:raise ValueError('Invalid private key')
    for kind in (paramiko.Ed25519Key,paramiko.ECDSAKey,paramiko.RSAKey):
        try:return kind.from_private_key(io.StringIO(value),password=passphrase or None)
        except (paramiko.SSHException,ValueError):pass
    raise ValueError('Invalid or encrypted private key')
