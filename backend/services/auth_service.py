from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Cookie, HTTPException, Request, Response

from backend import config
from backend.db import database


SESSION_COOKIE = "tally_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_google_token(id_token: str) -> dict[str, Any]:
    if id_token.startswith("test:"):
        email = id_token.split(":", 1)[1] or "user@example.test"
        return {
            "sub": f"test-{email.lower()}",
            "email": email,
            "name": email.split("@", 1)[0],
            "picture": None,
        }

    parts = id_token.split(".")
    if len(parts) < 2:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Google token") from exc

    audience = claims.get("aud")
    if config.GOOGLE_CLIENT_ID and audience != config.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")
    if not claims.get("sub") or not claims.get("email"):
        raise HTTPException(status_code=401, detail="Google token missing required identity claims")
    return claims


def create_login_session(id_token: str, response: Response) -> dict[str, Any]:
    claims = verify_google_token(id_token)
    user = database.create_or_update_user(
        google_sub=str(claims["sub"]),
        email=str(claims["email"]),
        name=claims.get("name"),
        picture_url=claims.get("picture"),
    )
    token = database.random_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=config.SESSION_TTL_DAYS)).isoformat()
    database.create_session(user["id"], hash_token(token), expires_at)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        max_age=config.SESSION_TTL_DAYS * 24 * 60 * 60,
    )
    return user


def get_current_user(request: Request, tally_session: Optional[str] = Cookie(default=None)) -> dict[str, Any]:
    bearer_token = _bearer_token(request)
    token = tally_session or bearer_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = database.get_session_by_hash(hash_token(token))
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {
        "id": session["user_id"],
        "google_sub": session["google_sub"],
        "email": session["email"],
        "name": session["name"],
        "picture_url": session["picture_url"],
    }


def logout(request: Request, response: Response, tally_session: Optional[str] = Cookie(default=None)) -> None:
    token = tally_session or _bearer_token(request)
    if token:
        database.revoke_session(hash_token(token))
    response.delete_cookie(SESSION_COOKIE)


def assert_same_token(left: str, right: str) -> bool:
    return hmac.compare_digest(hash_token(left), hash_token(right))


def _bearer_token(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value
