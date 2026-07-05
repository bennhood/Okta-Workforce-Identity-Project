import requests
import json
import os
from datetime import datetime, timezone
import entra_sync

# Configuration - credentials come from environment variables, never hardcoded
OKTA_DOMAIN = os.environ.get("OKTA_DOMAIN", "https://integrator-1186065.okta.com")
OKTA_API_TOKEN = os.environ.get("OKTA_API_TOKEN", "place_token_here")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "place_token_here")

# Department to Slack channel mapping
DEPARTMENT_CHANNELS = {
    "Engineering": "#engineering-staff",
    "Finance": "#finance-staff",
    "HR": "#hr-staff"
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
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"  Error fetching user {email}: {response.status_code}")
        return None


def get_group_id(group_name):
    """Look up Okta group ID by name."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/groups?q={group_name}",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 200:
        groups = response.json()
        for group in groups:
            if group["profile"]["name"] == group_name:
                return group["id"]
    print(f"  Warning: Group '{group_name}' not found")
    return None


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


def add_to_group(user_id, group_id, group_name):
    """Add a user to an Okta group."""
    response = requests.put(
        f"{OKTA_DOMAIN}/api/v1/groups/{group_id}/users/{user_id}",
        headers=OKTA_HEADERS, timeout=30
    )

    if response.status_code == 204:
        print(f"  Added to group: {group_name}")
    else:
        print(f"  Error adding to group {group_name}: {response.status_code}")


def update_okta_department(user_id, new_department):
    """Update the department attribute on an Okta user profile."""
    payload = {
        "profile": {
            "department": new_department
        }
    }

    response = requests.post(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}",
        headers=OKTA_HEADERS,
        json=payload, timeout=30
    )

    if response.status_code == 200:
        print(f"  Okta profile updated: department → {new_department}")
    else:
        print(f"  Error updating Okta profile: {response.status_code}")
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


def run_mover_workflow(email, old_department, new_department):
    """
    Process a department change (Mover) for a single user.

    Steps:
    1. Fetch user from Okta
    2. Remove from old department group (SoD: old access removed before new granted)
    3. Add to new department group
    4. Update department attribute in Okta
    5. Sync department change to Entra ID
    6. Notify old and new department Slack channels
    """
    print("=" * 50)
    print("AcmeCorp Mover Workflow")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print(f"\nProcessing mover: {email}")
    print(f"  {old_department} → {new_department}")

    # Step 1 - Fetch user
    user = get_user_by_email(email)
    if not user:
        print("Aborting - user not found.")
        return

    user_id = user["id"]
    profile = user["profile"]
    first_name = profile.get("firstName")
    last_name = profile.get("lastName")

    print(f"  User ID: {user_id}")

    # Step 2 - Remove from old department group
    old_group_name = f"{old_department}-Staff"
    old_group_id = get_group_id(old_group_name)
    if old_group_id:
        remove_from_group(user_id, old_group_id, old_group_name)

    # Step 3 - Add to new department group
    new_group_name = f"{new_department}-Staff"
    new_group_id = get_group_id(new_group_name)
    if new_group_id:
        add_to_group(user_id, new_group_id, new_group_name)

    # Step 4 - Update Okta profile
    update_okta_department(user_id, new_department)

    # Step 5 - Sync department change and group swap to Entra ID
    entra_sync.update_department(email, new_department)
    entra_sync.remove_from_group(email, f"{old_department}-Staff")
    entra_sync.assign_to_group(email, f"{new_department}-Staff")

    # Step 6 - Notify Slack channels
    old_channel = DEPARTMENT_CHANNELS.get(old_department)
    new_channel = DEPARTMENT_CHANNELS.get(new_department)

    if old_channel:
        post_slack_notification(
            old_channel,
            f":arrow_right: *Mover - Departure*\n"
            f"*{first_name} {last_name}* has transferred from *{old_department}* "
            f"to *{new_department}*.\n"
            f"_Access has been updated per the AcmeCorp Mover policy._"
        )

    if new_channel:
        post_slack_notification(
            new_channel,
            f":wave: *Mover - Arrival*\n"
            f"*{first_name} {last_name}* has transferred from *{old_department}* "
            f"to *{new_department}*.\n"
            f"_Access has been updated per the AcmeCorp Mover policy._"
        )

    print(f"\nMover workflow complete for {first_name} {last_name}.")
    print(f"Groups updated: {old_group_name} → {new_group_name}")
    print(f"Profile updated: Okta + Entra ID department → {new_department}")


if __name__ == "__main__":
    # Test scenario: Robert Fisher moves from Finance to Engineering
    run_mover_workflow(
        email="robert.fisher@acmecorp.com",
        old_department="Finance",
        new_department="Engineering"
    )