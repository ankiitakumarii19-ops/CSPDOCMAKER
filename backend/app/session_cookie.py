"""
CSP DocMaker — the sign-in kept in a protected cookie (No. 173)

The browser used to keep the sign-in token in localStorage, where any
script on the page could read it. Now the server hands the browser an
HttpOnly cookie (scripts cannot read it), SameSite=Strict, Secure on HTTPS,
lasting as long as the token. The token stays out of the reply's body for
the browser.

  * The browser asks for the cookie with the header X-Session-Cookie: 1 on
    sign-in; a script or test that does not ask gets the token in the body
    and sends it as "Authorization: Bearer", exactly as before.
  * A request signed in by the cookie that changes something must carry
    X-Requested-With: CSPDocMaker — a page on another site cannot add that
    header, so it cannot act in someone's name (cross-site request forgery).
  * Logging out removes the cookie.

The cookie's name is SESSION_COOKIE_NAME, so a test copy of the app on the
same address keeps its own sign-in.
"""

from typing import Optional, Tuple

from app.config import get_settings

WANT_HEADER = "x-session-cookie"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "CSPDocMaker"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def name() -> str:
    return get_settings().session_cookie_name


def token_from(request) -> Tuple[Optional[str], Optional[str]]:
    """(token, "bearer" | "cookie") — a Bearer header first, else the cookie."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip(), "bearer"
    cookie = request.cookies.get(name())
    if cookie:
        return cookie, "cookie"
    return None, None


def wants_cookie(request) -> bool:
    return request.headers.get(WANT_HEADER) == "1"


def forged(request, via: Optional[str]) -> bool:
    """A cookie-signed change without the app's own header."""
    return (via == "cookie" and request.method.upper() not in SAFE_METHODS
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE)


def set_on(response, token: str, seconds: int) -> None:
    secure = get_settings().public_app_url.lower().startswith("https://")
    response.set_cookie(name(), token, max_age=max(int(seconds), 60),
                        httponly=True, secure=secure, samesite="strict",
                        path="/")


def clear_on(response) -> None:
    response.delete_cookie(name(), path="/")
