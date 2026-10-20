"""Browser CSRF protection and bounded sensitive-request rate limiting."""
import collections
import secrets
import threading
import time
from flask import request,session,jsonify


def install_browser_security(app):
    attempts=collections.OrderedDict()
    lock=threading.Lock()
    def csrf_token():
        if '_csrf_token' not in session:session['_csrf_token']=secrets.token_urlsafe(32)
        return session['_csrf_token']
    app.jinja_env.globals['csrf_token']=csrf_token
    @app.before_request
    def protect_browser_writes():
        if request.method not in ('POST','PUT','PATCH','DELETE'):return None
        # Versioned API uses its own API-key authentication, never cookie fallback.
        if request.path.startswith('/api/v1/') and (request.headers.get('X-API-Key') or request.args.get('api_key')):return None
        expected=session.get('_csrf_token')
        supplied=request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token')
        if not expected or not isinstance(supplied,str) or not secrets.compare_digest(expected,supplied):
            return jsonify(success=False,error='Your form session expired. Reload the page and try again.'),403
        sensitive=request.path in ('/login','/register','/forgot-password') or '/password' in request.path or '/console/connect' in request.path
        if sensitive:
            identity=(session.get('_user_id',request.remote_addr),request.path)
            now=time.monotonic()
            with lock:
                bucket=attempts.setdefault(identity,collections.deque())
                while bucket and bucket[0]<now-60:bucket.popleft()
                if len(bucket)>=12:return jsonify(success=False,error='Too many attempts. Wait one minute and try again.'),429,{'Retry-After':'60'}
                bucket.append(now);attempts.move_to_end(identity)
                while len(attempts)>4096:attempts.popitem(last=False)
