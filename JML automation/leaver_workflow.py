import requests
import json
import os
from datetime import datetime, timezone
import entra_sync

# Configuration - credentials come from environment variables, never hardcoded
OKTA_DOMAIN = os.environ.get("OKTA_DOMAIN", "https://integrator-1186065.okta.com")
OKTA_API_TOKEN = os.environ.get("OKTA_API_TOKEN", "place_token_here")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "place_token_here")

OKTA_HEADERS = {
    "Authorization": f"SSWS {OKTA_API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json"
}

# Leaver SLA - actions at each stage
SLA = {
    "immediate": "Account deactivated in Okta + Entra ID - all SSO and Microsoft 365 access revoked",
    "24h":        "All Okta and Entra ID group memberships removed - app access fully revoked",
    "30d":        "Account permanently deleted from Okta + Entra ID"
}


def get_user_by_email(email):
    """Fetch a single Okta user by email address."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{email}",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 200:
        return response.json()
    print(f"  Error fetching user {email}: {response.status_code}")
    return None


def get_user_groups(user_id):
    """Fetch all groups a user is a member of in Okta."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/groups",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 200:
        return response.json()
    print(f"  Error fetching groups for {user_id}: {response.status_code}")
    return []


def remove_from_group(user_id, group_id, group_name):
    """Remove a user from an Okta group."""
    response = requests.delete(
        f"{OKTA_DOMAIN}/api/v1/groups/{group_id}/users/{user_id}",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 204:
        print(f"  Removed from group: {group_name}")
    else:
        print(f"  Error removing from group {group_name}: {response.status_code}")


def deactivate_okta_user(user_id):
    """Deactivate a user in Okta (T+0 - immediately revokes all SSO sessions)."""
    response = requests.post(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/lifecycle/deactivate",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 200:
        print(f"  Okta account deactivated - all active sessions terminated")
    else:
        print(f"  Error deactivating user: {response.status_code}")
        print(response.text)


def post_slack_notification(channel, message):
    """Post a message to a Slack channel."""
    payload = {
        "channel": channel,
        "text": message
    }

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json=payload, timeout=30
    )

    data = response.json()
    if data.get("ok"):
        print(f"  Slack notification sent to {channel}")
    else:
        print(f"  Slack error: {data.get('error', 'Unknown error')}")


def run_leaver_workflow(email, notify_channel="#hr-staff"):
    """
    Process an offboarding (Leaver) for a single user.

    Immediate actions (T+0):
    1. Deactivate in Okta - terminates all SSO sessions immediately
    2. Disable account in Entra ID - blocks new Microsoft 365 sign-ins
    3. Revoke Entra sessions + refresh tokens - kills access already issued
    4. Notify HR Slack channel

    Documented SLA actions (not automated in this lab):
    T+24h: Remove all Okta group memberships (access revocation)
    T+30d: Permanent deletion from Okta + Entra ID
    """
    print("=" * 50)
    print("AcmeCorp Leaver Workflow")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print(f"\nProcessing leaver: {email}")

    # Fetch user
    user = get_user_by_email(email)
    if not user:
        print("Aborting - user not found.")
        return

    user_id = user["id"]
    profile = user["profile"]
    first_name = profile.get("firstName")
    last_name = profile.get("lastName")
    department = profile.get("department", "Unknown")

    print(f"  User ID: {user_id}")
    print(f"  Department: {department}")
    print(f"  Status: {user.get('status')}")

    print("\n--- T+0 Immediate Actions ---")

    # Step 1 - Deactivate in Okta
    deactivate_okta_user(user_id)

    # Step 2 - Disable account in Entra ID
    entra_sync.disable_user(email)

    # Step 3 - Revoke all sessions and refresh tokens in Entra ID.
    # Disabling blocks NEW sign-ins only - tokens already issued stay
    # valid until expiry, so a leaver could retain M365 access for up
    # to an hour. Revocation closes that window at T+0.
    entra_sync.revoke_sessions(email)

    # Step 4 - Notify HR
    post_slack_notification(
        notify_channel,
        f":no_entry: *Leaver - Offboarding Initiated*\n"
        f"*Name:* {first_name} {last_name}\n"
        f"*Email:* {email}\n"
        f"*Department:* {department}\n"
        f"*Timestamp:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"*Actions completed:*\n"
        f"• Okta account deactivated - all SSO sessions terminated\n"
        f"• Entra ID account disabled - new Microsoft 365 sign-ins blocked\n"
        f"• Entra ID sessions + refresh tokens revoked - existing access killed\n\n"
        f"*Pending SLA actions:*\n"
        f"• T+24h: {SLA['24h']}\n"
        f"• T+30d: {SLA['30d']}"
    )

    print("\n--- Documented SLA (not automated) ---")
    print(f"  T+24h: {SLA['24h']}")
    print(f"  T+30d: {SLA['30d']}")

    print(f"\nLeaver workflow complete for {first_name} {last_name}.")
    print("Okta + Entra ID access revoked. HR notified.")


if __name__ == "__main__":
    # Test scenario: Nick Front offboarding
    run_leaver_workflow(
        email="nick.front@acmecorp.com",
        notify_channel="#hr-staff"
    )
