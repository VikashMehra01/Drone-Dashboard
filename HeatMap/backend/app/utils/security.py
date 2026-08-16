"""
security.py — Password hashing and JWT helpers.

Uses the `bcrypt` library directly (avoids passlib's bcrypt version check
which breaks on bcrypt >= 4.x) and PyJWT for token handling.
"""
from __future__ import annotations

import datetime
from typing import Optional

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload["exp"] = expire
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

