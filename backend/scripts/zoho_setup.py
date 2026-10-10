"""Turn a Zoho Self Client grant code into a permanent refresh token.

A grant code is valid for only a few minutes and can be used once; a refresh
token does not expire and is what the app actually stores. Run this straight
after generating the code in the API console:

    .venv/Scripts/python.exe scripts/zoho_setup.py --code 1000.abc123...

It prints the refresh token to paste into backend/.env, then verifies the
connection. With no --code it only checks the settings and the existing token.

Nothing here writes a secret to disk or to the log.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

settings = get_settings()

REQUIRED_SCOPES = (
    "ZohoCRM.modules.READ",
    "ZohoCRM.modules.attachments.READ",
    "ZohoCRM.settings.modules.READ",
)


def check_settings() -> bool:
    print("=== settings ===")
    ok = True
    if settings.zoho_data_centre not in ("in", "com", "eu", "com.au", "jp"):
        print(f"[FAIL] ZOHO_DATA_CENTRE={settings.zoho_data_centre!r} is not a "
              "known Zoho data centre")
        ok = False
    else:
        print(f"[ OK ] data centre .{settings.zoho_data_centre}")
        print(f"       accounts: {settings.zoho_accounts_url}")
        print(f"       api:      {settings.zoho_api_url}")

    for name, value in (("ZOHO_CLIENT_ID", settings.zoho_client_id),
                        ("ZOHO_CLIENT_SECRET", settings.zoho_client_secret)):
        if value:
            print(f"[ OK ] {name} is set ({len(value)} characters)")
        else:
            print(f"[FAIL] {name} is empty")
            ok = False
    return ok


def exchange(code: str) -> str:
    """Swap a one-time grant code for a refresh token."""
    print("\n=== exchanging the grant code ===")
    response = httpx.post(
        f"{settings.zoho_accounts_url}/oauth/v2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.zoho_client_id,
            "client_secret": settings.zoho_client_secret,
            "code": code,
        },
        timeout=30.0,
    )
    payload = response.json()

    if "refresh_token" not in payload:
        print(f"[FAIL] Zoho did not return a refresh token: {payload}")
        if payload.get("error") == "invalid_code":
            print("       The code has expired or was already used. Generate a "
                  "fresh one — they last about 10 minutes and work once.")
        raise SystemExit(1)

    print("[ OK ] refresh token received\n")
    print("Put this line in backend/.env:\n")
    print(f"    ZOHO_REFRESH_TOKEN={payload['refresh_token']}\n")
    return payload["refresh_token"]


def access_token(refresh_token: str) -> str:
    response = httpx.post(
        f"{settings.zoho_accounts_url}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.zoho_client_id,
            "client_secret": settings.zoho_client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30.0,
    )
    payload = response.json()
    if "access_token" not in payload:
        print(f"[FAIL] could not get an access token: {payload}")
        raise SystemExit(1)
    return payload["access_token"]


def verify(refresh_token: str) -> None:
    """Prove the token works and show which modules it can read."""
    print("=== verifying ===")
    token = access_token(refresh_token)
    print("[ OK ] access token obtained")

    response = httpx.get(
        f"{settings.zoho_api_url}/crm/v7/settings/modules",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
        timeout=30.0,
    )
    if response.status_code != 200:
        print(f"[FAIL] reading modules returned HTTP {response.status_code}: "
              f"{response.text[:300]}")
        print("       If this says OAUTH_SCOPE_MISMATCH, the grant code was "
              "generated without " + ", ".join(REQUIRED_SCOPES))
        raise SystemExit(1)

    modules = [m for m in response.json().get("modules", [])
               if m.get("api_supported")]
    print(f"[ OK ] {len(modules)} readable module(s). Likely places for CSPs:")
    for module in modules:
        name = (module.get("api_name") or "").lower()
        if any(k in name for k in ("lead", "contact", "account", "csp",
                                   "vendor", "deal")):
            print(f"       {module.get('api_name'):<28} "
                  f"\"{module.get('plural_label')}\"")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="the Self Client grant code")
    args = parser.parse_args()

    if not check_settings():
        print("\nFix the items marked FAIL in backend/.env, then run again.")
        raise SystemExit(1)

    if args.code:
        verify(exchange(args.code))
        return

    if not settings.zoho_refresh_token:
        print("\nNo ZOHO_REFRESH_TOKEN yet. Generate a grant code in the API "
              "console with these scopes:\n       " + ",".join(REQUIRED_SCOPES)
              + "\nthen run:\n"
              "    .venv/Scripts/python.exe scripts/zoho_setup.py --code <code>")
        raise SystemExit(1)

    verify(settings.zoho_refresh_token)


main()
