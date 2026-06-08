import requests
import json
from datetime import datetime, timezone, timedelta

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

OKTA_HEADERS = {
    "Authorization": f"SSWS {OKTA_API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

SLACK_HEADERS = {
    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
    "Content-Type": "application/json"
}


def get_recent_joiners(hours=24):
    """Fetch users created in Okta within the last N hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users?filter=status eq \"ACTIVE\""
        f"&search=created gt \"{since}\"",
        headers=OKTA_HEADERS
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching users: {response.status_code}")
        print(response.text)
        return []


def get_all_active_users():
    """Fetch all active users from Okta  used for full provisioning audit."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users?filter=status eq \"ACTIVE\"",
        headers=OKTA_HEADERS
    )

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching users: {response.status_code}")
        return []


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


def process_joiner(user):
    """Process a single joiner  check department and notify Slack channel."""
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

    # Look up the correct Slack channel
    channel = DEPARTMENT_CHANNELS.get(department)

    if not channel:
        print(f"  Warning: No channel mapped for department '{department}'")
        return

    # Build and send Slack notification
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

    print(f"\nJoiner workflow complete  {len(users)} user(s) processed.")


if __name__ == "__main__":
    # Use mode="all" to run against all current active users (lab demo)
    # Use mode="recent" in production to catch only new joiners
    run_joiner_workflow(mode="all")
