import requests
import json
import os
from datetime import datetime, timezone, timedelta
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


def _get_paginated(url):
    """
    Fetch an Okta collection following Link-header (RFC 5988) pagination.
    Okta returns at most 200 users per page by default - without this,
    any run against a tenant of more than one page silently truncates.
    """
    results = []
    while url:
        response = requests.get(url, headers=OKTA_HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching users: {response.status_code}")
            print(response.text)
            return results
        results.extend(response.json())
        # requests parses the Link header into response.links
        url = response.links.get("next", {}).get("url")
    return results


def get_recent_joiners(hours=24):
    """Fetch users created in Okta within the last N hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    return _get_paginated(
        f"{OKTA_DOMAIN}/api/v1/users"
        f"?search=status eq \"ACTIVE\" and created gt \"{since}\"&limit=200"
    )


def get_all_active_users():
    """Fetch all active users from Okta - used for full provisioning audit."""
    return _get_paginated(
        f"{OKTA_DOMAIN}/api/v1/users?filter=status eq \"ACTIVE\"&limit=200"
    )


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


def process_joiner(user):
    """
    Process a single joiner:
    1. Post provisioning notification to department Slack channel
    2. Provision user to Entra ID via Microsoft Graph
    """
    profile = user.get("profile", {})
    first_name = profile.get("firstName", "Unknown")
    last_name = profile.get("lastName", "Unknown")
    email = profile.get("email", "Unknown")
    department = profile.get("department", "")
    manager = profile.get("manager", "Not assigned")
    created = user.get("created", "Unknown")

    print(f"\nProcessing joiner: {first_name} {last_name} ({email})")
    print(f"  Department: {department}")
    print(f"  Manager: {manager}")
    print(f"  Created: {created}")

    # Slack notification
    channel = DEPARTMENT_CHANNELS.get(department)

    if not channel:
        print(f"  Warning: No channel mapped for department '{department}'")
    else:
        message = (
            f":wave: *New joiner provisioned*\n"
            f"*Name:* {first_name} {last_name}\n"
            f"*Email:* {email}\n"
            f"*Department:* {department}\n"
            f"*Manager:* {manager}\n"
            f"*Provisioned:* {created}\n"
            f"_Access has been provisioned per the AcmeCorp Joiner policy._"
        )
        post_slack_notification(channel, message)

    # Entra ID provisioning + group assignment
    success, upn = entra_sync.provision_user(first_name, last_name, email, department, manager)
    if success:
        group_name = f"{department}-Staff"
        entra_sync.assign_to_group(email, group_name)

        # Manager is a directory relationship in Graph, not a create-payload
        # field - it is assigned separately via $ref. Okta's manager field
        # is free text, so only attempt assignment when it holds a
        # resolvable email address.
        if manager and "@" in manager:
            entra_sync.set_manager(email, manager)
        elif manager and manager != "Not assigned":
            print(f"  [Entra] Manager '{manager}' is not an email - "
                  f"skipping relationship assignment")


def run_joiner_workflow(mode="recent", hours=24):
    """
    Run the Joiner workflow.
    mode='recent'  process users created in the last N hours (production use)
    mode='all'     process all active users (lab demo / bulk run)
    """
    print("=" * 50)
    print("AcmeCorp Joiner Workflow")
    print(f"Mode: {mode} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if mode == "all":
        users = get_all_active_users()
        # Exclude the admin account
        users = [u for u in users if u["profile"].get("department")]
    else:
        users = get_recent_joiners(hours=hours)

    if not users:
        print("\nNo new joiners found.")
        return

    print(f"\nFound {len(users)} user(s) to process...")

    for user in users:
        process_joiner(user)

    print(f"\nJoiner workflow complete - {len(users)} user(s) processed.")


if __name__ == "__main__":
    # Use mode="all" to run against all current active users (lab demo)
    # Use mode="recent" in production to catch only new joiners
    run_joiner_workflow(mode="all")
