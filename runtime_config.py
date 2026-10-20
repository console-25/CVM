"""Stable deployment secrets; never ship the generated secret file."""
import os
from pathlib import Path
import secrets


def persistent_secret(path=None):
    configured = os.environ.get('SECRET_KEY')
    if configured:
        return configured
    target = Path(path or os.environ.get('HVM_SECRET_FILE', '.hvm-secret')).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = target.read_text().strip()
        if len(value) < 32:
            raise RuntimeError('HVM secret file is invalid. Restore it or configure SECRET_KEY.')
        return value
    with os.fdopen(fd, 'w') as stream:
        stream.write(value + '\n')
    return value
