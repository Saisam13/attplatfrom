"""Username/password auth: a users table + server-side sessions (httponly
cookie). Replaces the shared team PIN — each teammate gets their own account
instead of one secret the whole team (and anyone who finds it) shares.

Bootstrapping: create_user() is only reachable via /api/auth/setup while the
users table is empty (see main.py) — that's the one-time "create the first
account" flow, done by whoever opens the app, not seeded with any password
chosen on their behalf.
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

from .db import SessionLocal, User, AuthSession

SESSION_COOKIE = 'att_session'
SESSION_MAX_AGE_DAYS = 30
PBKDF2_ITERATIONS = 200_000

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300
_login_failures = {}


def _login_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _login_failures.get(ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
    _login_failures[ip] = attempts
    return len(attempts) >= _LOGIN_MAX_ATTEMPTS


def _record_login_failure(ip):
    _login_failures.setdefault(ip, []).append(time.time())


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f'{salt}:{digest.hex()}'


def verify_password(password: str, stored: str) -> bool:
    if not stored or ':' not in stored:
        return False
    salt, digest_hex = stored.split(':', 1)
    check = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return hmac.compare_digest(check.hex(), digest_hex)


def _user_out(u) -> dict:
    return {
        'id': u.id, 'username': u.username, 'display_name': u.display_name or u.username,
        'created_at': u.created_at.isoformat() if u.created_at else '',
        'last_login_at': u.last_login_at.isoformat() if u.last_login_at else '',
    }


def any_users_exist() -> bool:
    session = SessionLocal()
    try:
        return session.query(User).first() is not None
    finally:
        session.close()


def create_user(username: str, password: str, display_name: str = '') -> dict:
    username = (username or '').strip().lower()
    if not username or not password:
        raise ValueError('username and password are required')
    if len(password) < 6:
        raise ValueError('password must be at least 6 characters')
    session = SessionLocal()
    try:
        if session.query(User).filter(User.username == username).first():
            raise ValueError('that username is already taken')
        u = User(username=username, display_name=(display_name or '').strip() or username,
                  password_hash=hash_password(password))
        session.add(u)
        session.commit()
        return _user_out(u)
    finally:
        session.close()


def authenticate(username: str, password: str, ip: str):
    """Returns the user dict on success, None on wrong credentials.
    Raises PermissionError('too_many_attempts') if this IP is rate-limited."""
    if _login_rate_limited(ip):
        raise PermissionError('too_many_attempts')
    session = SessionLocal()
    try:
        u = session.query(User).filter(User.username == (username or '').strip().lower()).first()
        if not u or not verify_password(password, u.password_hash):
            _record_login_failure(ip)
            return None
        u.last_login_at = datetime.utcnow()
        session.commit()
        return _user_out(u)
    finally:
        session.close()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionLocal()
    try:
        session.add(AuthSession(token=token, user_id=user_id))
        session.commit()
        return token
    finally:
        session.close()


def get_session_user(token: str):
    if not token:
        return None
    session = SessionLocal()
    try:
        s = session.get(AuthSession, token)
        if not s:
            return None
        if datetime.utcnow() - s.created_at > timedelta(days=SESSION_MAX_AGE_DAYS):
            session.delete(s)
            session.commit()
            return None
        u = session.get(User, s.user_id)
        if not u:
            return None
        s.last_seen_at = datetime.utcnow()
        session.commit()
        return _user_out(u)
    finally:
        session.close()


def delete_session(token: str):
    if not token:
        return
    session = SessionLocal()
    try:
        s = session.get(AuthSession, token)
        if s:
            session.delete(s)
            session.commit()
    finally:
        session.close()


def list_users():
    session = SessionLocal()
    try:
        return [_user_out(u) for u in session.query(User).order_by(User.id).all()]
    finally:
        session.close()


def delete_user(user_id: int):
    """Refuses to delete the last remaining account — that would lock
    everyone out with no way back in short of touching the database."""
    session = SessionLocal()
    try:
        if session.query(User).count() <= 1:
            raise ValueError('cannot delete the last remaining account')
        session.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()
    finally:
        session.close()
