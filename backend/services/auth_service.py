from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from fastapi import Cookie, HTTPException, Request, Response

from backend import config
from backend.db import database


SESSION_COOKIE = "tally_session"
logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_google_token(id_token: str) -> dict[str, Any]:
    if id_token.startswith("test:"):
        if not config.ALLOW_DEV_AUTH:
            logger.warning("auth.login.dev_token_rejected reason=dev_auth_disabled")
            raise HTTPException(status_code=401, detail="Dev login is disabled")
        email = id_token.split(":", 1)[1] or "user@example.test"
        logger.info("auth.login.dev_token_accepted email=%s", email)
        return {
            "sub": f"test-{email.lower()}",
            "email": email,
            "name": email.split("@", 1)[0],
            "picture": None,
        }

    try:
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning(
                "auth.login.google_tokeninfo_rejected status_code=%s response=%s",
                response.status_code,
                response.text[:300],
            )
            raise HTTPException(status_code=401, detail="Invalid Google token")
        claims = response.json()
    except HTTPException:
        raise
    except (requests.RequestException, ValueError) as exc:
        logger.warning("auth.login.google_tokeninfo_failed error=%r", exc)
        raise HTTPException(status_code=401, detail="Unable to verify Google token") from exc

    audience = claims.get("aud")
    if not config.GOOGLE_CLIENT_ID:
        logger.error("auth.login.failed reason=missing_google_client_id")
        raise HTTPException(status_code=401, detail="GOOGLE_CLIENT_ID is required for Google login")
    if audience != config.GOOGLE_CLIENT_ID:
        logger.warning("auth.login.failed reason=audience_mismatch audience=%s", audience)
        raise HTTPException(status_code=401, detail="Google token audience mismatch")
    if not claims.get("sub") or not claims.get("email"):
        logger.warning("auth.login.failed reason=missing_identity_claims")
        raise HTTPException(status_code=401, detail="Google token missing required identity claims")
    if str(claims.get("email_verified", "true")).lower() not in {"true", "1"}:
        logger.warning("auth.login.failed reason=email_not_verified email=%s", claims.get("email"))
        raise HTTPException(status_code=401, detail="Google email is not verified")
    logger.info("auth.login.google_token_verified email=%s subject=%s", claims.get("email"), claims.get("sub"))
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
    logger.info("auth.login.success user_id=%s email=%s expires_at=%s", user["id"], user["email"], expires_at)
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


def logout(request: Request, response: Response, tally_session: Optional[str] = None) -> None:
    token = tally_session or request.cookies.get(SESSION_COOKIE) or _bearer_token(request)
    if token:
        database.revoke_session(hash_token(token))
        logger.info("auth.logout.success")
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
