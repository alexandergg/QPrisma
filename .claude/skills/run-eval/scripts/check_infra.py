"""
Infrastructure readiness checker for QPrisma evaluation.

Verifies that all required services are running and accessible:
- API server at localhost:8000
- Authentication works
- At least one video is indexed

Usage:
    python .claude/skills/run-eval/scripts/check_infra.py
"""

import json
import sys

import httpx

API_URL = "http://localhost:8000"
TIMEOUT = 10


def check_api_server() -> dict:
    """Check if the API server is responding."""
    try:
        resp = httpx.get(f"{API_URL}/docs", timeout=TIMEOUT)
        return {"status": "ok", "http_status": resp.status_code}
    except httpx.ConnectError:
        return {"status": "error", "message": "API server not running at localhost:8000"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_auth() -> dict:
    """Check if authentication works."""
    try:
        resp = httpx.post(
            f"{API_URL}/auth/login",
            json={"email": "user@example.com", "password": "stringst"},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            return {"status": "ok", "token": token}
        return {"status": "error", "message": f"Login failed: HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"status": "error", "message": "API server not reachable"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_indexed_videos(token: str) -> dict:
    """Check if at least one video is indexed."""
    try:
        headers = {"Authorization": f"Bearer {token}"}
        resp = httpx.get(f"{API_URL}/media", headers=headers, timeout=TIMEOUT)
        if resp.status_code == 200:
            media = resp.json()
            items = media if isinstance(media, list) else media.get("items", [])
            indexed = [m for m in items if m.get("status") == "completed"]
            return {
                "status": "ok" if indexed else "warning",
                "total_media": len(items),
                "indexed": len(indexed),
                "message": None if indexed else "No indexed videos found",
            }
        return {"status": "error", "message": f"Media endpoint: HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def main():
    print("QPrisma Evaluation Infrastructure Check")
    print("=" * 45)

    results = {}
    all_ok = True

    # 1. API Server
    print("\n1. API Server...", end=" ")
    api_result = check_api_server()
    results["api_server"] = api_result
    if api_result["status"] == "ok":
        print("OK")
    else:
        print(f"FAIL - {api_result['message']}")
        all_ok = False

    # 2. Authentication
    print("2. Authentication...", end=" ")
    auth_result = check_auth()
    results["auth"] = {k: v for k, v in auth_result.items() if k != "token"}
    if auth_result["status"] == "ok":
        print("OK")
    else:
        print(f"FAIL - {auth_result['message']}")
        all_ok = False

    # 3. Indexed Videos (only if auth succeeded)
    token = auth_result.get("token", "")
    print("3. Indexed Videos...", end=" ")
    if token:
        video_result = check_indexed_videos(token)
        results["indexed_videos"] = video_result
        if video_result["status"] == "ok":
            print(f"OK ({video_result['indexed']} indexed)")
        elif video_result["status"] == "warning":
            print(f"WARNING - {video_result['message']}")
        else:
            print(f"FAIL - {video_result['message']}")
            all_ok = False
    else:
        results["indexed_videos"] = {"status": "skipped", "message": "Auth failed"}
        print("SKIPPED (auth failed)")

    # Summary
    print("\n" + "=" * 45)
    if all_ok:
        print("All checks passed. Ready to run evaluation.")
    else:
        print("Some checks failed. Fix issues before running evaluation.")

    # Output JSON for programmatic use
    print(f"\n{json.dumps(results, indent=2)}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
