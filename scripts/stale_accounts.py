import requests
import csv
from datetime import datetime, timezone, timedelta

# Configuration
OKTA_DOMAIN = "https://integrator-1186065.okta.com"
API_TOKEN = "your-okta-api-token-here"
OUTPUT_FILE = "stale-accounts-report.csv"

# Thresholds
STALE_DAYS = 90          # Flag users inactive for 90+ days
NEVER_LOGGED_IN = True   # Include users who have never logged in

HEADERS = {
    "Authorization": f"SSWS {API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}


def get_all_users():
    """Fetch all active users from Okta with pagination."""
    users = []
    url = f"{OKTA_DOMAIN}/api/v1/users?filter=status eq \"ACTIVE\"&limit=200"

    while url:
        response = requests.get(url, headers=HEADERS)

        if response.status_code != 200:
            print(f"Error fetching users: {response.status_code}")
            break

        page = response.json()
        users.extend(page)

        link_header = response.headers.get("Link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        url = next_url

    return users


def is_stale(user, threshold_days=90):
    """
    Determine if a user account is stale.
    Returns (is_stale: bool, reason: str, days_inactive: int or None)
    """
    last_login = user.get("lastLogin")

    if not last_login:
        if NEVER_LOGGED_IN:
            created = user.get("created", "")
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            days_since_created = (datetime.now(timezone.utc) - created_dt).days
            return True, "Never logged in", days_since_created
        return False, "", None

    last_login_dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
    days_inactive = (datetime.now(timezone.utc) - last_login_dt).days

    if days_inactive >= threshold_days:
        return True, f"Inactive for {days_inactive} days", days_inactive

    return False, "", None


def get_user_groups(user_id):
    """Fetch group names for a user."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/groups",
        headers=HEADERS
    )

    if response.status_code == 200:
        groups = response.json()
        return [g["profile"]["name"] for g in groups if g.get("type") != "BUILT_IN"]
    return []


def run_stale_accounts_report():
    """
    Identify and report stale Okta accounts.

    Stale criteria:
    - Active accounts with no login in 90+ days
    - Active accounts that have never logged in
    """
    print("=" * 50)
    print("AcmeCorp Stale Accounts Report")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Threshold: {STALE_DAYS} days inactive")
    print("=" * 50)

    print("\nFetching users...")
    users = get_all_users()
    print(f"Found {len(users)} active users\n")

    stale_accounts = []
    clean_accounts = 0

    for user in users:
        profile = user.get("profile", {})
        user_id = user["id"]

        first_name = profile.get("firstName", "")
        last_name = profile.get("lastName", "")
        email = profile.get("email", "")
        department = profile.get("department", "")
        manager = profile.get("manager", "")
        created = user.get("created", "")[:10]
        last_login = user.get("lastLogin", "Never")
        if last_login and last_login != "Never":
            last_login = last_login[:10]

        stale, reason, days = is_stale(user, STALE_DAYS)

        if stale:
            groups = get_user_groups(user_id)
            stale_accounts.append({
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "department": department,
                "manager": manager,
                "created": created,
                "lastLogin": last_login if last_login else "Never",
                "reason": reason,
                "daysInactive": days,
                "groups": " | ".join(groups) if groups else "None",
                "recommendedAction": "Review and disable if no longer required"
            })
            print(f"  STALE: {first_name} {last_name} - {reason}")
        else:
            clean_accounts += 1

    # Write CSV
    if stale_accounts:
        fieldnames = [
            "firstName", "lastName", "email", "department", "manager",
            "created", "lastLogin", "reason", "daysInactive", "groups",
            "recommendedAction"
        ]

        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(stale_accounts)

        print(f"\nStale accounts report exported to: {OUTPUT_FILE}")
    else:
        print("\nNo stale accounts found.")

    print(f"\nSummary:")
    print(f"  Total active users scanned: {len(users)}")
    print(f"  Clean accounts: {clean_accounts}")
    print(f"  Stale accounts flagged: {len(stale_accounts)}")

    if stale_accounts:
        print(f"\nStale accounts requiring review:")
        for account in stale_accounts:
            print(f"  - {account['firstName']} {account['lastName']}"
                  f" ({account['email']}) - {account['reason']}")


if __name__ == "__main__":
    run_stale_accounts_report()
