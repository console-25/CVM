"""SQLite-backed creation deduplication and short node reservation."""
import functools
import hashlib
import json
import re
import secrets
import time
from flask import request,jsonify,current_app
from flask_login import current_user


def creation_guard(get_db):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            if request.method!='POST':return fn(*args,**kwargs)
            data=request.get_json(silent=True)
            if not isinstance(data,dict):return fn(*args,**kwargs)
            token=request.headers.get('Idempotency-Key')
            if token and not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',token):return jsonify(success=False,error='Invalid request identifier.'),400
            node=str(data.get('node_id',''));owner=str(current_user.id);now=time.time();lease=secrets.token_hex(16)
            digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with get_db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS hvm_create_requests (owner TEXT, token TEXT, digest TEXT, response TEXT, status INTEGER, created REAL, PRIMARY KEY(owner,token))')
                db.execute('CREATE TABLE IF NOT EXISTS hvm_create_leases (node TEXT PRIMARY KEY, lease TEXT, created REAL)')
                db.commit();db.execute('BEGIN IMMEDIATE')
                if token:
                    existing=db.execute('SELECT digest,response,status FROM hvm_create_requests WHERE owner=? AND token=?',(owner,token)).fetchone()
                    if existing:
                        if existing[0]!=digest:return jsonify(success=False,error='Request identifier already used for another configuration. Reload the form.'),409
                        if existing[1]:return current_app.response_class(existing[1],status=existing[2],mimetype='application/json')
                        return jsonify(success=False,error='This deployment is already being processed. Check the VPS list before retrying.'),409
                db.execute('DELETE FROM hvm_create_leases WHERE created<?',(now-600,))
                if db.execute('SELECT node FROM hvm_create_leases WHERE node=?',(node,)).fetchone():return jsonify(success=False,error='Another creation request is checking this node. Retry shortly.'),409
                db.execute('INSERT INTO hvm_create_leases VALUES (?,?,?)',(node,lease,now))
                if token:db.execute('INSERT INTO hvm_create_requests VALUES (?,?,?,NULL,NULL,?)',(owner,token,digest,now))
                db.commit()
            try:
                response=current_app.make_response(fn(*args,**kwargs))
                if token:
                    with get_db() as db:
                        db.execute('UPDATE hvm_create_requests SET response=?,status=? WHERE owner=? AND token=?',(response.get_data(as_text=True),response.status_code,owner,token));db.commit()
                return response
            finally:
                with get_db() as db:
                    db.execute('DELETE FROM hvm_create_leases WHERE node=? AND lease=?',(node,lease));db.execute('DELETE FROM hvm_create_requests WHERE created<? AND response IS NOT NULL',(time.time()-86400,));db.commit()
        return wrapped
    return decorate
