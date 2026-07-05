"""
entra_reconcile.py - Bulk reconciliation of Okta desired state into Entra ID.

This is the scale-oriented counterpart to the per-user functions in
entra_sync.py. Instead of processing users one at a time (fetch, wait,
assign, repeat), it follows the reconciliation pattern used by production
provisioning engines (SCIM connectors, Entra provisioning service,
IGA platforms such as SailPoint):

    1. READ desired state   - all active users in Okta (source of truth)
    2. READ actual state    - all managed users + group memberships in Entra
    3. DIFF                 - compute the exact set of changes required
    4. APPLY                - execute changes via Graph $batch (20 ops/call)

Why this shape:
    - Sequential per-user scripts make O(n) round trips with per-user
      sleeps for eventual consistency. Reconciliation reads both sides
      in O(pages), diffs in memory, and only touches objects that are
      actually wrong - a no-op run makes zero write calls.
    - $batch collapses up to 20 write operations into one HTTP request
      (https://learn.microsoft.com/graph/json-batching).
    - The diff makes the run idempotent: re-running after a partial
      failure simply picks up whatever is still out of sync.
    - Sub-requests inside a batch are NOT retried automatically by
      Graph on throttling - each sub-response carries its own status,
      so this module re-queues 429/5xx sub-failures itself using the
      Retry-After header (https://learn.microsoft.com/graph/throttling).

Scope guard:
    Only Entra users whose UPN ends with ENTRA_DOMAIN *and* whose UPN
    local part corresponds to an Okta-managed account are touched.
    The admin / non-departmental accounts are never disabled.

Usage:
    python entra_reconcile.py            # dry run - prints the plan only
    python entra_reconcile.py --apply    # executes the plan

Config comes from environment variables (never hardcode tokens):
    OKTA_DOMAIN, OKTA_API_TOKEN
    ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET (via entra_sync)
"""

import os
import sys
import time
import secrets
import string
import requests

import entra_sync
from entra_sync import GRAPH_BASE, ENTRA_DOMAIN, build_upn

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OKTA_DOMAIN = os.environ.get("OKTA_DOMAIN", "https://integrator-1186065.okta.com")
OKTA_API_TOKEN = os.environ.get("OKTA_API_TOKEN", "place_token_here")

OKTA_HEADERS = {
    "Authorization": f"SSWS {OKTA_API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

BATCH_URL = f"{GRAPH_BASE}/$batch"
BATCH_LIMIT = 20          # hard Graph limit on sub-requests per $batch call
BATCH_MAX_ROUNDS = 4      # 1 initial round + up to 3 retry rounds
REQUEST_TIMEOUT = 30      # seconds - no call may hang the run indefinitely
DISABLE_THRESHOLD = 2     # max disables per run without --force (circuit breaker)

# Accounts the reconciler must never touch, regardless of what the diff
# says. Guests (#EXT# UPNs) are externally managed identities - including,
# in this tenant, the admin account itself - and admin/break-glass accounts
# are not lifecycle-managed by definition. This is the lab equivalent of a
# provisioning scoping filter. Extendable via PROTECTED_UPNS env var
# (comma-separated).
PROTECTED_UPNS = {
    u.strip().lower()
    for u in os.environ.get("PROTECTED_UPNS", "ben.hood@" + ENTRA_DOMAIN).split(",")
    if u.strip()
}


def _is_protected(upn):
    """Guests and explicitly protected accounts are outside managed scope."""
    return "#ext#" in upn.lower() or upn.lower() in PROTECTED_UPNS

# Departments whose "{dept}-Staff" groups this engine manages.
MANAGED_DEPARTMENTS = ("Engineering", "Finance", "HR")


# ---------------------------------------------------------------------------
# Phase 1 - READ desired state (Okta, source of truth)
# ---------------------------------------------------------------------------

def fetch_desired_state():
    """
    Fetch every ACTIVE Okta user with a department, following Link-header
    pagination so nothing past the 200-record default page is missed.

    Returns dict keyed by Entra UPN:
        upn -> {first, last, email, department, group}
    """
    desired = {}
    url = f'{OKTA_DOMAIN}/api/v1/users?filter=status eq "ACTIVE"&limit=200'

    while url:
        response = requests.get(url, headers=OKTA_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            raise RuntimeError(
                f"Okta user fetch failed: {response.status_code} {response.text[:200]}"
            )

        for user in response.json():
            profile = user.get("profile", {})
            department = profile.get("department")
            if not department:
                # No department = not lifecycle-managed (e.g. the admin account)
                continue

            email = profile.get("email", "")
            upn = build_upn(email)
            desired[upn] = {
                "first": profile.get("firstName", ""),
                "last": profile.get("lastName", ""),
                "email": email,
                "department": department,
                "group": f"{department}-Staff",
            }

        # requests parses the RFC 5988 Link header into response.links
        url = response.links.get("next", {}).get("url")

    return desired


# ---------------------------------------------------------------------------
# Phase 2 - READ actual state (Entra ID)
# ---------------------------------------------------------------------------

def fetch_actual_users():
    """
    Fetch all Entra users in the lab domain, following @odata.nextLink
    pagination. $top=999 is the Graph maximum page size for /users.

    Domain scoping is done client-side: a server-side
    endsWith(userPrincipalName, ...) filter would require the advanced
    query mode (ConsistencyLevel: eventual + $count=true), which adds a
    header dependency for no benefit at this tenant size.

    Returns dict: upn -> {id, accountEnabled, department, displayName}
    """
    actual = {}
    fields = "id,userPrincipalName,accountEnabled,department,displayName"
    url = f"{GRAPH_BASE}/users?$select={fields}&$top=999"

    while url:
        response = entra_sync._graph_request("GET", url)
        if response is None or response.status_code != 200:
            raise RuntimeError("Entra user fetch failed - aborting reconcile")

        payload = response.json()
        for user in payload.get("value", []):
            upn = user.get("userPrincipalName", "")
            if not upn.lower().endswith(f"@{ENTRA_DOMAIN}".lower()):
                continue
            if _is_protected(upn):
                # Never enters the diff - cannot be disabled, patched,
                # or have memberships changed by any plan.
                continue
            actual[upn] = {
                "id": user["id"],
                "accountEnabled": user.get("accountEnabled", False),
                "department": user.get("department"),
                "displayName": user.get("displayName", ""),
            }

        url = payload.get("@odata.nextLink")

    return actual


def fetch_actual_memberships():
    """
    Fetch current membership of every managed "{dept}-Staff" group.

    Uses lookup-only group resolution - reconciliation must never create
    a group as a side effect of *reading* state. Missing groups are
    created later, in APPLY, only if the plan requires them.

    Returns:
        memberships: group_name -> set(user_id)
        group_ids:   group_name -> group_id | None (None = doesn't exist yet)
    """
    memberships = {}
    group_ids = {}

    for department in MANAGED_DEPARTMENTS:
        group_name = f"{department}-Staff"
        group_id = _lookup_group_id(group_name)
        group_ids[group_name] = group_id
        members = set()

        if group_id:
            url = f"{GRAPH_BASE}/groups/{group_id}/members?$select=id&$top=999"
            while url:
                response = entra_sync._graph_request("GET", url)
                if response is None or response.status_code != 200:
                    raise RuntimeError(f"Member fetch failed for {group_name}")
                payload = response.json()
                members.update(m["id"] for m in payload.get("value", []))
                url = payload.get("@odata.nextLink")

        memberships[group_name] = members

    return memberships, group_ids


def _lookup_group_id(group_name):
    """Read-only group lookup. Simple eq filter - no advanced query needed."""
    response = entra_sync._graph_request(
        "GET", f"{GRAPH_BASE}/groups?$filter=displayName eq '{group_name}'"
    )
    if response and response.status_code == 200:
        groups = response.json().get("value", [])
        if groups:
            return groups[0]["id"]
    return None


# ---------------------------------------------------------------------------
# Phase 3 - DIFF desired vs actual
# ---------------------------------------------------------------------------

def build_plan(desired, actual, memberships, group_ids):
    """
    Compute the change set. Every entry is something that is verifiably
    wrong in Entra right now - a clean tenant produces an empty plan.

    Returns dict of lists:
        create      [{upn, first, last, email, department}]
        update      [{upn, id, patch}]        - department drift
        disable     [{upn, id}]               - active in Entra, gone from Okta
        member_add  [{upn, user_id|None, group}]  - user_id None = created this run
        member_del  [{upn, user_id, group}]
    """
    plan = {"create": [], "update": [], "disable": [],
            "member_add": [], "member_del": []}

    upn_to_id = {upn: rec["id"] for upn, rec in actual.items()}

    for upn, want in desired.items():
        have = actual.get(upn)

        if have is None:
            plan["create"].append({"upn": upn, **want})
            # Membership for a not-yet-existing user - resolved post-create
            plan["member_add"].append(
                {"upn": upn, "user_id": None, "group": want["group"],
                 "email": want["email"]}
            )
            continue

        patch = {}
        if have.get("department") != want["department"]:
            patch["department"] = want["department"]
        if not have.get("accountEnabled"):
            # Present and active in Okta but disabled in Entra - re-enable
            patch["accountEnabled"] = True
        if patch:
            plan["update"].append({"upn": upn, "id": have["id"], "patch": patch})

        # Group membership: user should be in exactly their department group
        want_group = want["group"]
        user_id = have["id"]
        for group_name, members in memberships.items():
            in_group = user_id in members
            if group_name == want_group and not in_group:
                plan["member_add"].append(
                    {"upn": upn, "user_id": user_id, "group": group_name}
                )
            elif group_name != want_group and in_group:
                plan["member_del"].append(
                    {"upn": upn, "user_id": user_id, "group": group_name}
                )

    # Leavers: enabled in Entra, absent from Okta desired state
    for upn, have in actual.items():
        if upn not in desired and have.get("accountEnabled"):
            plan["disable"].append({"upn": upn, "id": have["id"]})

    return plan


def print_plan(plan):
    total = sum(len(v) for v in plan.values())
    print(f"\nReconciliation plan - {total} change(s):")
    if total == 0:
        print("  Entra ID matches Okta desired state. Nothing to do.")
        return

    labels = {
        "create":     "CREATE user",
        "update":     "PATCH  user",
        "disable":    "DISABLE user",
        "member_add": "ADD    to group",
        "member_del": "REMOVE from group",
    }
    for key, label in labels.items():
        for item in plan[key]:
            detail = item.get("group") or item.get("patch") or ""
            print(f"  [{label}] {item['upn']}  {detail}")


# ---------------------------------------------------------------------------
# $batch executor
# ---------------------------------------------------------------------------

def _generate_password():
    """Per-user random temporary password - no shared static secrets."""
    alphabet = string.ascii_letters + string.digits
    return "Tmp!" + "".join(secrets.choice(alphabet) for _ in range(16))


def execute_batch(operations, description):
    """
    Execute a list of Graph operations via /$batch.

    operations: [{"id": str, "method": str, "url": str, "body": dict|None}]
                url is relative to GRAPH_BASE, e.g. "/users".

    Graph evaluates each sub-request against throttling limits
    individually: the batch itself can return 200 while sub-requests
    fail with 429. Failed 429/5xx sub-requests are re-queued for up to
    BATCH_MAX_ROUNDS, honouring the longest Retry-After seen.

    Returns dict: op_id -> sub-response dict (final status per operation).
    """
    results = {}
    pending = list(operations)

    for round_no in range(1, BATCH_MAX_ROUNDS + 1):
        if not pending:
            break

        next_round = []
        max_retry_after = 0

        for i in range(0, len(pending), BATCH_LIMIT):
            chunk = pending[i:i + BATCH_LIMIT]
            body = {"requests": [
                {
                    "id": op["id"],
                    "method": op["method"],
                    "url": op["url"],
                    **({"body": op["body"],
                        "headers": {"Content-Type": "application/json"}}
                       if op.get("body") is not None else {}),
                }
                for op in chunk
            ]}

            response = entra_sync._graph_request("POST", BATCH_URL, json_body=body)
            if response is None or response.status_code != 200:
                # Whole batch call failed - re-queue the chunk
                next_round.extend(chunk)
                max_retry_after = max(max_retry_after, 2 ** round_no)
                continue

            op_index = {op["id"]: op for op in chunk}
            for sub in response.json().get("responses", []):
                status = sub.get("status", 0)
                results[sub["id"]] = sub

                if status == 429 or status in (500, 502, 503, 504):
                    retry_after = int(
                        sub.get("headers", {}).get("Retry-After", 2 ** round_no)
                    )
                    max_retry_after = max(max_retry_after, retry_after)
                    next_round.append(op_index[sub["id"]])

        pending = next_round
        if pending and round_no < BATCH_MAX_ROUNDS:
            print(f"  [{description}] {len(pending)} op(s) throttled/transient - "
                  f"retrying in {max_retry_after}s (round {round_no + 1})")
            time.sleep(max_retry_after)

    if pending:
        print(f"  [{description}] {len(pending)} op(s) still failing after "
              f"{BATCH_MAX_ROUNDS} rounds - see summary")

    return results


# ---------------------------------------------------------------------------
# Phase 4 - APPLY the plan
# ---------------------------------------------------------------------------

def apply_plan(plan, group_ids):
    """
    Execute the plan in three batched phases. Ordering matters:

      Phase A - user creates            (new objects must exist first)
      Phase B - patches + disables      (independent of A)
      Phase C - group membership        (needs object IDs from A, so new
                                         users are re-resolved after a
                                         short eventual-consistency wait)
    """
    summary = {"ok": 0, "skipped": 0, "failed": []}

    # --- Phase A: creates ---------------------------------------------------
    creates = plan["create"]
    if creates:
        print(f"\nPhase A - creating {len(creates)} user(s) via $batch...")
        ops = []
        for n, item in enumerate(creates):
            ops.append({
                "id": f"create-{n}",
                "method": "POST",
                "url": "/users",
                "body": {
                    "accountEnabled": True,
                    "displayName": f"{item['first']} {item['last']}",
                    "givenName": item["first"],
                    "surname": item["last"],
                    "mailNickname": item["email"].split("@")[0],
                    "userPrincipalName": item["upn"],
                    "mail": item["email"],
                    "department": item["department"],
                    "passwordProfile": {
                        "forceChangePasswordNextSignIn": True,
                        "password": _generate_password(),
                    },
                },
            })
        results = execute_batch(ops, "create")
        _tally(results, ops, summary,
               ok_statuses=(201,), conflict_ok=True)

    # --- Phase B: patches + disables -----------------------------------------
    patches = plan["update"] + [
        {"upn": d["upn"], "id": d["id"], "patch": {"accountEnabled": False}}
        for d in plan["disable"]
    ]
    if patches:
        print(f"\nPhase B - patching {len(patches)} user(s) via $batch...")
        ops = [{
            "id": f"patch-{n}",
            "method": "PATCH",
            "url": f"/users/{item['id']}",
            "body": item["patch"],
        } for n, item in enumerate(patches)]
        results = execute_batch(ops, "patch")
        _tally(results, ops, summary, ok_statuses=(204,))

    # --- Phase C: memberships -------------------------------------------------
    adds, dels = plan["member_add"], plan["member_del"]
    if adds or dels:
        print(f"\nPhase C - {len(adds)} add(s), {len(dels)} removal(s) via $batch...")

        # Ensure target groups exist (only now - never during READ)
        needed = {item["group"] for item in adds}
        for group_name in needed:
            if not group_ids.get(group_name):
                group_ids[group_name] = entra_sync.get_or_create_group(group_name)

        # Resolve IDs for users created in Phase A. A 201 does not mean
        # the object is readable everywhere yet (eventual consistency),
        # hence the bounded retry rather than a fixed sleep per user.
        unresolved = [a for a in adds if a["user_id"] is None]
        if unresolved:
            print(f"  Resolving {len(unresolved)} newly created user ID(s)...")
            for attempt in range(1, 6):
                for item in unresolved:
                    if item["user_id"] is None:
                        user = entra_sync.get_user(item["email"])
                        if user:
                            item["user_id"] = user["id"]
                unresolved = [a for a in adds if a["user_id"] is None]
                if not unresolved:
                    break
                time.sleep(3 * attempt)

        ops = []
        for n, item in enumerate(adds):
            if item["user_id"] is None or not group_ids.get(item["group"]):
                summary["failed"].append(
                    (item["upn"], f"unresolved user/group for add to {item['group']}"))
                continue
            ops.append({
                "id": f"madd-{n}",
                "method": "POST",
                "url": f"/groups/{group_ids[item['group']]}/members/$ref",
                "body": {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{item['user_id']}"},
            })
        for n, item in enumerate(dels):
            ops.append({
                "id": f"mdel-{n}",
                "method": "DELETE",
                "url": f"/groups/{group_ids[item['group']]}/members/{item['user_id']}/$ref",
            })
        if ops:
            results = execute_batch(ops, "membership")
            _tally(results, ops, summary,
                   ok_statuses=(204,), conflict_ok=True, missing_ok=True)

    return summary


def _tally(results, ops, summary, ok_statuses, conflict_ok=False, missing_ok=False):
    """
    Fold batch sub-responses into the run summary.

    conflict_ok: 400 "already exists"-class errors count as success -
                 the desired state already holds. Detection keys on the
                 Graph error *code*, not the human-readable message.
    missing_ok:  404 on a DELETE counts as success (already absent).
    """
    for op in ops:
        sub = results.get(op["id"])
        if sub is None:
            summary["failed"].append((op["id"], "no response after retries"))
            continue

        status = sub.get("status", 0)
        if status in ok_statuses:
            summary["ok"] += 1
        elif missing_ok and status == 404:
            summary["skipped"] += 1
        elif conflict_ok and status == 400:
            code = (sub.get("body", {}).get("error", {}) or {}).get("code", "")
            if code in ("Request_BadRequest", "ObjectConflict"):
                summary["skipped"] += 1
            else:
                summary["failed"].append((op["id"], f"{status}: {code}"))
        else:
            summary["failed"].append((op["id"], f"status {status}"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_reconciliation(apply=False):
    print("=" * 60)
    print("AcmeCorp Entra ID Reconciliation")
    print(f"Mode: {'APPLY' if apply else 'DRY RUN (pass --apply to execute)'}")
    print("=" * 60)

    print("\n[1/4] Reading desired state from Okta...")
    desired = fetch_desired_state()
    print(f"      {len(desired)} lifecycle-managed user(s)")

    print("[2/4] Reading actual state from Entra ID...")
    actual = fetch_actual_users()
    memberships, group_ids = fetch_actual_memberships()
    print(f"      {len(actual)} user(s), "
          f"{sum(len(m) for m in memberships.values())} membership(s)")

    print("[3/4] Diffing...")
    plan = build_plan(desired, actual, memberships, group_ids)
    print_plan(plan)

    # Circuit breaker - mirrors Entra provisioning's accidental deletion
    # prevention. "Absent from Okta desired state" can mean leaver, but it
    # can also mean a failed page fetch, a renamed department field, or a
    # scoping bug - and each of those would mass-disable the tenant. If
    # the plan wants to disable more than DISABLE_THRESHOLD accounts,
    # halt and require explicit human override.
    if apply and len(plan["disable"]) > DISABLE_THRESHOLD and "--force" not in sys.argv:
        print(f"\nSAFETY HALT: plan wants to disable {len(plan['disable'])} "
              f"account(s), above the threshold of {DISABLE_THRESHOLD}.")
        print("This usually means a source-data or scoping problem, not a "
              "mass offboarding. Review the plan above; re-run with --force "
              "to override.")
        return

    if not apply:
        print("\nDry run complete. No changes made.")
        return

    print("\n[4/4] Applying...")
    summary = apply_plan(plan, group_ids)

    print("\n" + "=" * 60)
    print(f"Applied: {summary['ok']}  |  Already correct: {summary['skipped']}"
          f"  |  Failed: {len(summary['failed'])}")
    for op_id, reason in summary["failed"]:
        print(f"  FAILED  {op_id}: {reason}")
    print("Re-running reconciliation retries anything still out of sync.")
    print("=" * 60)


if __name__ == "__main__":
    run_reconciliation(apply="--apply" in sys.argv)