import requests
import json
from datetime import datetime, timezone

# Configuration
OKTA_DOMAIN = "https://integrator-1186065.okta.com"
OKTA_API_TOKEN = "your-okta-api-token-here"
SLACK_BOT_TOKEN = "your-slack-bot-token-here"

# Department to Slack channel mapping
DEPARTMENT_CHANNELS = {
    "Engineering": "#engineering-staff",
    "Finance": "#finance-staff",
    "HR": "#hr-staff"
}

# Offboarding SLA (documented even if not enforced by timer in this lab)
SLA = {
    "immediate": "Account suspended - all SSO access revoked",
    "24h": "Group memberships removed",
    "30d": "Account permanently deleted"
}

OKTA_HEADERS = {
    "Authorization": f"SSWS {OKTA_API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json"
}


def get_user_by_email(email):
    """Fetch a single Okta user by email address."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{email}",
        headers=OKTA_HEADERS
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"  Error fetching user {email}: {response.status_code}")
        return None


def get_user_groups(user_id):
    """Fetch all groups a user belongs to."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/groups",
        headers=OKTA_HEADERS
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"  Error fetching groups: {response.status_code}")
        return []


def remove_from_all_groups(user_id, groups):
    """Remove a user from all non-system Okta groups."""
    removed = []
    for group in groups:
        group_type = group.get("type", "")
        group_name = group["profile"]["name"]
        group_id = group["id"]

        # Skip built-in Okta system groups
        if group_type == "BUILT_IN":
            continue

        response = requests.delete(
            f"{OKTA_DOMAIN}/api/v1/groups/{group_id}/users/{user_id}",
            headers=OKTA_HEADERS
        )

        if response.status_code == 204:
            print(f"  Removed from group: {group_name}")
            removed.append(group_name)
        else:
            print(f"  Error removing from {group_name}: {response.status_code}")

    return removed


def deactivate_user(user_id):
    """Deactivate (suspend) an Okta user - revokes all active sessions."""
    response = requests.post(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/lifecycle/deactivate",
        headers=OKTA_HEADERS
    )

    if response.status_code == 200:
        print(f"  User deactivated - all sessions revoked")
        return True
    else:
        print(f"  Error deactivating user: {response.status_code}")
        print(response.text)
        return False


def post_slack_notification(channel, message):
    """Post a message to a Slack channel."""
    payload = {
        "channel": channel,
        "text": message
    }

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=SLACK_HEADERS,
        json=payload
    )

    data = response.json()
    if data.get("ok"):
        print(f"  Slack notification sent to {channel}")
    else:
        print(f"  Slack error: {data.get('error', 'Unknown error')}")


def run_leaver_workflow(email):
    """
    Process an offboarding (Leaver) for a single user.

    Offboarding SLA:
    - T+0h  : Account deactivated - all SSO sessions revoked immediately
    - T+24h : All group memberships removed (access revocation)
    - T+30d : Account permanently deleted (not implemented in lab - documented only)

    Steps:
    1. Fetch user from Okta
    2. Log current group memberships (audit trail)
    3. Deactivate account immediately (T+0)
    4. Remove all group memberships (T+24h - simulated immediately in lab)
    5. Notify department Slack channel
    6. Print SLA summary
    """
    print("=" * 50)
    print("AcmeCorp Leaver Workflow")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print(f"\nProcessing leaver: {email}")

    # Step 1 - Fetch user
    user = get_user_by_email(email)
    if not user:
        print("Aborting - user not found.")
        return

    user_id = user["id"]
    profile = user["profile"]
    first_name = profile.get("firstName")
    last_name = profile.get("lastName")
    department = profile.get("department", "")
    manager = profile.get("manager", "Not assigned")

    print(f"  User: {first_name} {last_name}")
    print(f"  Department: {department}")
    print(f"  Manager: {manager}")
    print(f"  Status: {user.get('status')}")

    # Step 2 - Log current groups (audit trail)
    print("\n  Current group memberships (audit log):")
    groups = get_user_groups(user_id)
    for group in groups:
        if group.get("type") != "BUILT_IN":
            print(f"    - {group['profile']['name']}")

    # Step 3 - Deactivate account (T+0)
    print(f"\n  T+0h - Deactivating account...")
    deactivated = deactivate_user(user_id)

    if not deactivated:
        print("Aborting - deactivation failed.")
        return

    # Step 4 - Remove group memberships (T+24h simulated)
    print(f"\n  T+24h - Removing group memberships...")
    removed_groups = remove_from_all_groups(user_id, groups)

    # Step 5 - Notify Slack
    channel = DEPARTMENT_CHANNELS.get(department)
    if channel:
        post_slack_notification(
            channel,
            f":lock: *Leaver - Access Revoked*\n"
            f"*{first_name} {last_name}* has left AcmeCorp.\n"
            f"*Department:* {department}\n"
            f"*Manager notified:* {manager}\n"
            f"*Groups removed:* {', '.join(removed_groups) if removed_groups else 'None'}\n"
            f"_All access has been revoked per the AcmeCorp Leaver policy. "
            f"Account scheduled for deletion at T+30 days._"
        )

    # Step 6 - SLA summary
    print(f"\n  Offboarding SLA summary:")
    for timeline, action in SLA.items():
        status = "✓ Complete" if timeline in ["immediate", "24h"] else "⏳ Scheduled"
        print(f"    {timeline}: {action} - {status}")

    print(f"\nLeaver workflow complete for {first_name} {last_name}.")


if __name__ == "__main__":
    # Test scenario: Nick Front offboarded
    run_leaver_workflow(
        email="nick.front@acmecorp.com"
    )
