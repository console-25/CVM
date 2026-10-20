"""Bounded background access preparation; all commands execute inside the guest."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import re
import shlex
import threading
import time
import uuid
from urllib.parse import urlparse

METHODS = {'sshx', 'tmate', 'shared_ipv4'}
SESSION_SECONDS = 3600


def validated_link(output, provider):
    pattern = r'https://[^\s\x1b<>"\']+'
    for link in re.findall(pattern, output or ''):
        try:
            parsed = urlparse(link)
            host = parsed.hostname or ''
            if parsed.username or parsed.password or parsed.port not in (None, 443):
                continue
        except ValueError:
            continue
        if provider == 'sshx' and host == 'sshx.io':
            return link
        if provider == 'tmate' and (host == 'tmate.io' or host.endswith('.tmate.io')):
            return link
    return ''


class AccessService:
    def __init__(self, run_guest, shared_endpoint, max_jobs=32):
        self.run_guest = run_guest
        self.shared_endpoint = shared_endpoint
        self.jobs = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='hvm-access')
        self.max_jobs = max_jobs

    def start(self, vps, user_id, method, install=False):
        if method not in METHODS:
            raise ValueError('Choose SSHX, tmate, or Shared IPv4.')
        with self.lock:
            now = time.time()
            for key in list(self.jobs):
                if self.jobs[key]['expires_at'] < now or (self.jobs[key]['state'] in ('failed','ended') and now - self.jobs[key]['created_at'] > 300):
                    del self.jobs[key]
            # Repeated clicks reuse the same active job instead of spawning shells.
            for job in self.jobs.values():
                if (job['user_id'], job['vps_id'], job['method']) == (user_id, vps['id'], method) and job['state'] in ('preparing', 'ready'):
                    return deepcopy(job)
            if len(self.jobs) >= self.max_jobs:
                raise ValueError('Access service is busy. End an existing session or try again shortly.')
            job_id = uuid.uuid4().hex
            job = dict(id=job_id, user_id=user_id, vps_id=vps['id'], method=method,
                       state='preparing', message='Checking your VPS', created_at=now,
                       expires_at=now + SESSION_SECONDS, result={}, vps=deepcopy(vps))
            self.jobs[job_id] = job
            self.executor.submit(self._prepare, job_id, bool(install))
            return deepcopy(job)

    def get(self, job_id, user_id, vps_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job['user_id'] != user_id or job['vps_id'] != vps_id:
                return None
            result = deepcopy(job)
            if result['expires_at'] <= time.time() and result['state'] == 'ready':
                result.update(state='expired', result={}, message='Session expired. Generate a new session.')
            result.pop('vps', None)
            return result

    def _update(self, job_id, **fields):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(fields)

    def _prepare(self, job_id, install):
        with self.lock:
            job = deepcopy(self.jobs[job_id])
        vps, method = job['vps'], job['method']
        try:
            if method == 'shared_ipv4':
                result = self.shared_endpoint(vps)
                with self.lock:
                    if self.jobs.get(job_id, {}).get('state') != 'ended':
                        self._update(job_id, state='ready', message='SSH connection ready', result=result)
                return
            self._update(job_id, message=f'Checking {method} in your VPS')
            probe = self.run_guest(vps, f'command -v {method} >/dev/null 2>&1 && echo HVM_READY || true', 15)
            if 'HVM_READY' not in probe:
                if not install:
                    raise ValueError(f'{method} is not installed. Enable “Install missing tools” and try again, or install it inside the VPS yourself.')
                self._update(job_id, message=f'Installing {method} inside your VPS')
                self.run_guest(vps, self.install_script(method), 300)
            directory = f'/tmp/hvm-access-{job_id}'
            qdir = shlex.quote(directory)
            self.run_guest(vps, f'umask 077; mkdir -m 700 {qdir}', 15)
            self._update(job_id, message='Connecting to the relay')
            if method == 'tmate':
                sock = f'{directory}/tmate.sock'
                # Wait for the actual readiness signal, with a finite timeout.
                script = (f'set -e; tmate -S {sock} new-session -d; '
                          f'nohup sh -c {shlex.quote(f"sleep {SESSION_SECONDS}; tmate -S {sock} kill-server; rm -rf {qdir}")} '
                          f'>/dev/null 2>&1 </dev/null &')
                self.run_guest(vps, script, 15)
                self.run_guest(vps, f'timeout 35 tmate -S {sock} wait tmate-ready', 40)
                ssh = self.run_guest(vps, f"tmate -S {sock} display -p '#{{tmate_ssh}}'", 15).strip()
                web = validated_link(self.run_guest(vps, f"tmate -S {sock} display -p '#{{tmate_web}}'", 15), method)
                if not re.fullmatch(r'ssh [A-Za-z0-9_.@:-]+', ssh) or not web:
                    raise ValueError('tmate did not return a valid session. Check outbound access to tmate.io.')
                result = {'ssh_command': ssh, 'web_url': web}
            else:
                script = (f'nohup timeout {SESSION_SECONDS} sshx --quiet >{qdir}/output 2>&1 '
                          f'</dev/null & echo $! > {qdir}/pid; '
                          f'nohup sh -c {shlex.quote(f"sleep {SESSION_SECONDS + 10}; rm -rf {qdir}")} >/dev/null 2>&1 </dev/null &')
                self.run_guest(vps, script, 15)
                output = self.run_guest(vps,
                    f'i=0; while [ "$i" -lt 35 ]; do '
                    f'if grep -q "https://sshx.io/" {qdir}/output; then cat {qdir}/output; exit 0; fi; '
                    'i=$((i+1)); sleep 1; done; exit 1', 40)
                web = validated_link(output, method)
                if not web:
                    raise ValueError('SSHX did not return a valid session link. Check outbound access to sshx.io.')
                result = {'web_url': web, 'ssh_command': ''}
            # Check for cancellation while the worker was preparing the session.
            with self.lock:
                cancelled = self.jobs.get(job_id, {}).get('state') == 'ended'
            if cancelled:
                self._cleanup(job)
                return
            self._update(job_id, state='ready', message='Your session is ready', result=result, expires_at=time.time() + SESSION_SECONDS)
        except Exception as exc:
            try:
                self._cleanup(job)
            except Exception:
                pass
            with self.lock:
                cancelled = self.jobs.get(job_id, {}).get('state') == 'ended'
            if not cancelled:
                # Node exceptions may contain full commands or session tokens.
                message = str(exc) if isinstance(exc, ValueError) else 'The node could not prepare access. Check that the VPS is running, its node is reachable, and outbound Internet is available.'
                self._update(job_id, state='failed', message=message, result={})

    @staticmethod
    def install_script(method):
        if method == 'sshx':
            # Explicit opt-in; official installer stays inside the authorized guest.
            return ('set -e; command -v curl >/dev/null || { echo "Install curl inside the VPS first" >&2; exit 1; }; '
                    'curl --proto "=https" --tlsv1.2 -fsS --max-time 60 https://sshx.io/get -o /tmp/hvm-sshx-installer-$$; '
                    'trap \'rm -f /tmp/hvm-sshx-installer-$$\' EXIT; sh /tmp/hvm-sshx-installer-$$')
        return ('set -e; if command -v apt-get >/dev/null; then '
                'DEBIAN_FRONTEND=noninteractive apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y tmate; '
                'elif command -v apk >/dev/null; then apk add --no-cache tmate; '
                'elif command -v dnf >/dev/null; then dnf install -y tmate; '
                'elif command -v yum >/dev/null; then yum install -y tmate; '
                'else echo "Install tmate using your guest package manager" >&2; exit 1; fi')

    def _cleanup(self, job):
        if job['method'] == 'shared_ipv4':
            return  # A reusable port mapping must not be deleted with a UI session.
        directory = f"/tmp/hvm-access-{job['id']}"
        if job['method'] == 'tmate':
            script = f'tmate -S {directory}/tmate.sock kill-server 2>/dev/null || true; rm -rf {directory}'
        else:
            script = (f'if [ -f {directory}/pid ]; then p=$(cat {directory}/pid); '
                      'case "$p" in *[!0-9]*|"") ;; *) '
                      'if [ -r /proc/$p/cmdline ] && tr "\\000" " " </proc/$p/cmdline | grep -q "timeout .*sshx"; then kill "$p" 2>/dev/null || true; fi;; esac; fi; '
                      f'rm -rf {directory}')
        self.run_guest(job['vps'], script, 15, cleanup=True)

    def end(self, job_id, user_id, vps_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job['user_id'] != user_id or job['vps_id'] != vps_id:
                return False
            job = deepcopy(job)
            self.jobs[job_id].update(state='ended', result={}, message='Session ended')
        self._cleanup(job)
        return True
