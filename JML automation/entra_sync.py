import requests
import time
import os
import secrets
import string


def _load_env(path=".env"):
    """
    Minimal .env loader - no python-dotenv dependency. Runs at import,
    so every workflow that imports entra_sync gets the values before
    reading its own config. Existing environment variables win.
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

# Configuration - credentials come from .env / environment, never hardcoded
TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "your-tenant-id-here")
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "your-client-id-here")
CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "your-client-secret-here")
ENTRA_DOMAIN = os.environ.get("ENTRA_DOMAIN", "benhood98aol.onmicrosoft.com")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
REQUEST_TIMEOUT = 30  # seconds - no API call may hang the run indefinitely

# Module-level caches - populated on first use, reused within a run
_token_cache = {
    "access_token": None,
    "expires_at": 0.0
}
_group_cache = {}  # group_name -> group_id


def get_access_token():
    """
    Obtain a Microsoft Graph API access token via OAuth 2.0 client credentials flow.
    Token is cached at module level and reused until 60 seconds before expiry.
    """
    now = time.time()

    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    for attempt in (1, 2):
        response = requests.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default"
        }, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            data = response.json()
            _token_cache["access_token"] = data["access_token"]
            _token_cache["expires_at"] = now + data.get("expires_in", 3600)
            return _token_cache["access_token"]

        # The token endpoint sits outside _graph_request, so transient
        # failures (429/5xx) get one simple retry of their own here.
        if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            print(f"  [Entra] Token endpoint transient error "
                  f"({response.status_code}) - retrying in 2s...")
            time.sleep(2)
            continue
        break

    print(f"  [Entra] Token error: {response.status_code} - {response.text}")
    return None


def _graph_request(method, url, json_body=None, attempt=1):
    """
    Central Graph API request handler with token management and retry logic.

    401  - Token expired mid-run: refresh once and retry immediately.
    429  - Rate limited: wait Retry-After duration then retry (up to MAX_RETRIES).
    5xx  - Transient server error: exponential backoff (1s, 2s, 4s).
    400/404 - Deterministic failures: returned as-is, no retry.
    """
    token = get_access_token()
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.request(method, url, headers=headers, json=json_body,
                                timeout=REQUEST_TIMEOUT)

    if response.status_code in (200, 201, 204, 400, 404):
        return response

    if response.status_code == 401 and attempt == 1:
        print(f"  [Entra] Token expired mid-run - refreshing...")
        _token_cache["access_token"] = None
        return _graph_request(method, url, json_body=json_body, attempt=2)

    if response.status_code == 429 and attempt <= MAX_RETRIES:
        retry_after = int(response.headers.get("Retry-After", RETRY_BASE_DELAY * attempt))
        print(f"  [Entra] Rate limited (429) - waiting {retry_after}s "
              f"(attempt {attempt}/{MAX_RETRIES})...")
        time.sleep(retry_after)
        return _graph_request(method, url, json_body=json_body, attempt=attempt + 1)

    if response.status_code in (500, 503, 504) and attempt <= MAX_RETRIES:
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        print(f"  [Entra] Server error ({response.status_code}) - "
              f"retrying in {delay:.0f}s (attempt {attempt}/{MAX_RETRIES})...")
        time.sleep(delay)
        return _graph_request(method, url, json_body=json_body, attempt=attempt + 1)

    print(f"  [Entra] Request failed: {response.status_code} - {response.text[:200]}")
    return None


def build_upn(okta_email):
    """
    Transform an Okta acmecorp.com email to an Entra ID UPN.
    Example: nick.front@acmecorp.com -> nick.front@benhood98aol.onmicrosoft.com
    """
    local = okta_email.split("@")[0]
    return f"{local}@{ENTRA_DOMAIN}"


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

def _generate_temp_password():
    """Per-user random temporary password - no shared static secret."""
    alphabet = string.ascii_letters + string.digits
    return "Tmp!" + "".join(secrets.choice(alphabet) for _ in range(16))


def _is_conflict(error):
    """
    True if a 400 error body means 'the desired object already exists'.
    Keys on the Graph error code first (stable contract), with a message
    fallback because user-create conflicts surface under the generic
    Request_BadRequest code rather than a dedicated conflict code.
    """
    code = error.get("code", "")
    msg = error.get("message", "").lower()
    return (code == "ObjectConflict"
            or "already exists" in msg
            or "conflicting object" in msg
            or "object references already exist" in msg)


def provision_user(first_name, last_name, email, department, manager=""):
    """
    Create a user in Entra ID via Microsoft Graph.
    Called by joiner_workflow.py and create_users_from_csv.py.
    Returns (success: bool, upn: str | None)

    Note: the manager attribute is NOT set here. In Graph, manager is a
    directory relationship, not a create-payload field - it is assigned
    afterwards via set_manager() with a $ref write.
    """
    upn = build_upn(email)
    local = email.split("@")[0]

    payload = {
        "accountEnabled": True,
        "displayName": f"{first_name} {last_name}",
        "givenName": first_name,
        "surname": last_name,
        "mailNickname": local,
        "userPrincipalName": upn,
        "mail": email,
        "department": department,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": _generate_temp_password()
        }
    }

    response = _graph_request("POST", f"{GRAPH_BASE}/users", json_body=payload)
    if response is None:
        return False, None

    if response.status_code == 201:
        print(f"  [Entra] Provisioned → {upn}")
        return True, upn

    if response.status_code == 400:
        error = response.json().get("error", {})
        if _is_conflict(error):
            print(f"  [Entra] Already exists → {upn}")
            return True, upn
        print(f"  [Entra] Provision failed: {error.get('message', '')}")

    return False, None


def set_manager(email, manager_email):
    """
    Assign a user's manager in Entra ID.

    Manager is a directory relationship set with a $ref PUT referencing
    the manager's object - it cannot be included in the user create
    payload. Called by joiner_workflow.py after provisioning, when the
    Okta manager attribute contains a resolvable email address.
    """
    upn = build_upn(email)
    manager = get_user(manager_email)
    if not manager:
        print(f"  [Entra] Manager not found in Entra: {manager_email} - skipped")
        return False

    response = _graph_request(
        "PUT",
        f"{GRAPH_BASE}/users/{upn}/manager/$ref",
        json_body={"@odata.id": f"{GRAPH_BASE}/users/{manager['id']}"}
    )

    if response is not None and response.status_code == 204:
        print(f"  [Entra] Manager set → {manager_email}")
        return True

    print(f"  [Entra] Manager assignment failed for {upn}")
    return False


def update_department(email, new_department):
    """
    Update the department attribute on an Entra ID user.
    Called by mover_workflow.py after the Okta profile update.
    """
    upn = build_upn(email)
    response = _graph_request(
        "PATCH",
        f"{GRAPH_BASE}/users/{upn}",
        json_body={"department": new_department}
    )

    if response is not None and response.status_code == 204:
        print(f"  [Entra] Department updated → {new_department} ({upn})")
        return True

    print(f"  [Entra] Update failed for {upn}")
    return False


def disable_user(email):
    """
    Disable a user account in Entra ID.
    T+0 Leaver action - blocks all Microsoft 365 sign-ins without data loss.
    """
    upn = build_upn(email)
    response = _graph_request(
        "PATCH",
        f"{GRAPH_BASE}/users/{upn}",
        json_body={"accountEnabled": False}
    )

    if response is not None and response.status_code == 204:
        print(f"  [Entra] Account disabled → {upn}")
        return True

    print(f"  [Entra] Disable failed for {upn}")
    return False


def revoke_sessions(email):
    """
    Revoke all refresh tokens and session cookies for a user.

    T+0 Leaver action alongside disable_user(). Disabling an account
    blocks NEW sign-ins, but access and refresh tokens already issued
    remain valid until expiry - so a leaver could retain Microsoft 365
    access for up to an hour after 'offboarding'. revokeSignInSessions
    invalidates them immediately.
    """
    upn = build_upn(email)
    response = _graph_request(
        "POST", f"{GRAPH_BASE}/users/{upn}/revokeSignInSessions"
    )

    if response is not None and response.status_code in (200, 204):
        print(f"  [Entra] Sessions and refresh tokens revoked → {upn}")
        return True

    print(f"  [Entra] Session revocation failed for {upn}")
    return False


def delete_user(email):
    """
    Permanently delete a user from Entra ID.
    T+30d Leaver action. Graph DELETE moves the user to the deleted items
    recycle bin (30-day retention) before permanent removal.
    """
    upn = build_upn(email)
    response = _graph_request("DELETE", f"{GRAPH_BASE}/users/{upn}")

    if response is not None and response.status_code == 204:
        print(f"  [Entra] User deleted (soft) → {upn}")
        return True

    print(f"  [Entra] Delete failed for {upn}")
    return False


def purge_deleted_user(email):
    """
    Permanently purge a soft-deleted user from the Entra ID recycle bin.

    Entra ID DELETE is a soft delete - the object retains its
    userPrincipalName for 30 days, which blocks recreating a user with
    the same UPN. This finds the soft-deleted object and purges it so
    the UPN is immediately free for re-provisioning. Used by
    reset_lab.py during teardown.

    Requires the User.DeleteRestore.All application permission (admin
    consented) in addition to User.ReadWrite.All. Returns True if the
    UPN is free (whether purged here or never in the recycle bin).
    """
    upn = build_upn(email)

    response = _graph_request(
        "GET",
        f"{GRAPH_BASE}/directory/deletedItems/microsoft.graph.user"
        f"?$filter=userPrincipalName eq '{upn}'"
    )

    if response is None or response.status_code != 200:
        print(f"  [Entra] Could not query recycle bin for {upn}")
        return False

    items = response.json().get("value", [])
    if not items:
        # Nothing in the recycle bin - UPN is already free
        return True

    object_id = items[0]["id"]
    purge = _graph_request(
        "DELETE", f"{GRAPH_BASE}/directory/deletedItems/{object_id}"
    )

    if purge and purge.status_code == 204:
        print(f"  [Entra] Purged from recycle bin → {upn}")
        return True

    print(f"  [Entra] Purge failed for {upn}")
    return False


def get_user(email):
    """
    Fetch a user record from Entra ID by Okta email.
    $select explicitly requests fields omitted from Graph API's default response.
    """
    upn = build_upn(email)
    fields = "id,displayName,userPrincipalName,mail,accountEnabled,department,givenName,surname"
    response = _graph_request("GET", f"{GRAPH_BASE}/users/{upn}?$select={fields}")

    if response is not None and response.status_code == 200:
        return response.json()
    return None


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------

def get_group_id(group_name):
    """
    Read-only group lookup by display name. Returns the object ID or None.

    A simple eq filter on displayName runs in Graph's default query mode -
    no ConsistencyLevel header needed. Note Graph reads are eventually
    consistent: a group created moments ago may not be returned yet,
    which is why creation paths cache IDs rather than re-querying.
    """
    if group_name in _group_cache:
        return _group_cache[group_name]

    response = _graph_request(
        "GET",
        f"{GRAPH_BASE}/groups?$filter=displayName eq '{group_name}'"
    )

    if response is not None and response.status_code == 200:
        groups = response.json().get("value", [])
        if groups:
            _group_cache[group_name] = groups[0]["id"]
            return groups[0]["id"]
    return None


def get_or_create_group(group_name):
    """
    Return the Entra ID object ID for a group, creating it if it doesn't exist.

    Group IDs are cached at module level after first lookup. In a single script
    run processing multiple users, each group is queried or created once and the
    ID is reused for all subsequent assignments - avoiding repeated API calls.

    Groups are created as security groups (not Microsoft 365 groups), which is
    the correct type for access control and Conditional Access policy targeting.
    """
    group_id = get_group_id(group_name)
    if group_id:
        return group_id

    # Group not found - create it
    mail_nickname = group_name.replace("-", "").replace(" ", "")
    response = _graph_request(
        "POST",
        f"{GRAPH_BASE}/groups",
        json_body={
            "displayName": group_name,
            "mailEnabled": False,
            "mailNickname": mail_nickname,
            "securityEnabled": True
        }
    )

    if response is not None and response.status_code == 201:
        group_id = response.json()["id"]
        _group_cache[group_name] = group_id
        print(f"  [Entra] Group created: {group_name}")
        # Brief pause - newly created groups have the same propagation window
        # as users and may not immediately accept member additions
        time.sleep(5)
        return group_id

    print(f"  [Entra] Failed to get or create group: {group_name}")
    return None


def assign_to_group(email, group_name):
    """
    Add an Entra ID user to a group.

    Called during Joiner provisioning and Mover (new department group).

    Includes a retry loop on the user lookup to handle Entra ID's eventual
    consistency window - a user provisioned moments earlier may not yet be
    retrievable when this function is called immediately after.
    """
    upn = build_upn(email)

    # Retry user lookup to account for post-provisioning propagation delay.
    # Entra ID eventual consistency means a 201 from provisioning does not
    # guarantee the user is immediately available for all operations.
    user = None
    for attempt in range(1, 6):
        user = get_user(email)
        if user:
            break
        if attempt < 5:
            print(f"  [Entra] Waiting for user to be indexed ({attempt}/5)...")
            time.sleep(5)

    if not user:
        print(f"  [Entra] Cannot assign to group - user not found: {upn}")
        return False

    user_id = user["id"]
    group_id = get_or_create_group(group_name)
    if not group_id:
        return False

    # Retry the membership POST - group and user objects may not be fully
    # replicated in all Microsoft backend systems immediately after creation,
    # even when a GET already succeeds. 5s intervals allow replication to settle.
    for assignment_attempt in range(1, 4):
        response = _graph_request(
            "POST",
            f"{GRAPH_BASE}/groups/{group_id}/members/$ref",
            json_body={"@odata.id": f"{GRAPH_BASE}/users/{user_id}"}
        )

        if response is not None and response.status_code == 204:
            print(f"  [Entra] Assigned to group: {group_name}")
            return True

        if response is not None and response.status_code == 400:
            error = response.json().get("error", {})
            if _is_conflict(error):
                print(f"  [Entra] Already in group: {group_name}")
                return True
            print(f"  [Entra] Assignment error (400): {error.get('message', '')}")
            return False

        if assignment_attempt < 3:
            print(f"  [Entra] Assignment pending, retrying in 5s "
                  f"({assignment_attempt}/3)...")
            time.sleep(5)

    if response is not None:
        print(f"  [Entra] Assignment error ({response.status_code}): "
              f"{response.text[:300]}")

    print(f"  [Entra] Group assignment failed: {group_name}")
    return False


def remove_from_group(email, group_name):
    """
    Remove an Entra ID user from a group.

    Called by mover_workflow.py (old department group) and documented as a
    T+24h SLA action in the Leaver workflow, consistent with the Okta side.
    """
    user = get_user(email)
    if not user:
        print(f"  [Entra] Cannot remove from group - user not found")
        return False

    user_id = user["id"]
    # Lookup-only: a removal must never CREATE the group it is removing
    # someone from. If the group doesn't exist, the user isn't in it.
    group_id = get_group_id(group_name)
    if not group_id:
        print(f"  [Entra] Group does not exist: {group_name} - nothing to remove")
        return True

    response = _graph_request(
        "DELETE",
        f"{GRAPH_BASE}/groups/{group_id}/members/{user_id}/$ref"
    )

    if response is not None and response.status_code == 204:
        print(f"  [Entra] Removed from group: {group_name}")
        return True

    # 404 means user wasn't in the group - not a failure
    if response is not None and response.status_code == 404:
        print(f"  [Entra] User not in group: {group_name}")
        return True

    print(f"  [Entra] Group removal failed: {group_name}")
    return False


# ---------------------------------------------------------------------------
# Standalone connectivity test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("entra_sync.py - Connectivity & Provisioning Test")
    print("=" * 55)

    print("\n[1] Testing Graph API authentication...")
    token = get_access_token()
    if not token:
        print("    FAILED - Check TENANT_ID, CLIENT_ID, CLIENT_SECRET")
        raise SystemExit(1)
    print("    OK - Token acquired")

    print("\n[2] Provisioning test user: nick.front@acmecorp.com")
    success, upn = provision_user(
        first_name="Nick",
        last_name="Front",
        email="nick.front@acmecorp.com",
        department="Engineering"
    )
    if not success:
        print("    FAILED - Check app registration API permissions")
        print("    Required: User.ReadWrite.All (Application, admin consented)")
        raise SystemExit(1)

    print("\n[3] Verifying user in Entra ID...")
    user = None
    for attempt in range(1, 5):
        user = get_user("nick.front@acmecorp.com")
        if user:
            break
        print(f"    Not yet indexed - retrying in 3s (attempt {attempt}/4)...")
        time.sleep(3)

    if user:
        print(f"    OK - {user.get('displayName')} ({user.get('userPrincipalName')})")
        print(f"         accountEnabled : {user.get('accountEnabled')}")
        print(f"         department     : {user.get('department')}")
        print(f"         mail           : {user.get('mail')}")
    else:
        print("    FAILED - User not found after 4 retry attempts")
        raise SystemExit(1)

    print("\n[4] Testing group creation and assignment...")
    result = assign_to_group("nick.front@acmecorp.com", "Engineering-Staff")
    if not result:
        print("    FAILED - Check Group.ReadWrite.All permission")
        raise SystemExit(1)

    print("\n" + "=" * 55)
    print("All checks passed.")
    print("Verify at entra.microsoft.com > Users and > Groups")
    print("before running JML scripts.")
    print("=" * 55)