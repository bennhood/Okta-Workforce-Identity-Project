import requests
import csv
import json
from datetime import datetime, timezone

# Configuration
OKTA_DOMAIN = "https://integrator-1186065.okta.com"
API_TOKEN = "your-okta-api-token-here"
OUTPUT_FILE = "okta-access-report.csv"

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

        # Handle pagination via Link header
        link_header = response.headers.get("Link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        url = next_url

    return users


def get_user_groups(user_id):
    """Fetch all groups a user belongs to."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/groups",
        headers=HEADERS
    )

    if response.status_code == 200:
        groups = response.json()
        return [g["profile"]["name"] for g in groups if g.get("type") != "BUILT_IN"]
    return []


def get_user_apps(user_id):
    """Fetch all app assignments for a user."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/users/{user_id}/appLinks",
        headers=HEADERS
    )

    if response.status_code == 200:
        apps = response.json()
        return [a["label"] for a in apps]
    return []


def format_last_login(last_login):
    """Format last login timestamp for the report."""
    if not last_login:
        return "Never"
    try:
        dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return last_login


def run_access_report():
    """Generate a full user access report and export to CSV."""
    print("=" * 50)
    print("AcmeCorp Okta Access Report")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print("\nFetching users...")
    users = get_all_users()
    print(f"Found {len(users)} active users\n")

    report_rows = []

    for user in users:
        profile = user.get("profile", {})
        user_id = user["id"]

        first_name = profile.get("firstName", "")
        last_name = profile.get("lastName", "")
        email = profile.get("email", "")
        department = profile.get("department", "")
        manager = profile.get("manager", "")
        status = user.get("status", "")
        last_login = format_last_login(user.get("lastLogin"))
        created = user.get("created", "")[:10]

        print(f"Processing: {first_name} {last_name} ({email})")

        groups = get_user_groups(user_id)
        apps = get_user_apps(user_id)

        report_rows.append({
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "department": department,
            "manager": manager,
            "status": status,
            "lastLogin": last_login,
            "created": created,
            "groups": " | ".join(groups) if groups else "None",
            "apps": " | ".join(apps) if apps else "None",
            "groupCount": len(groups),
            "appCount": len(apps)
        })

    # Write CSV
    fieldnames = [
        "firstName", "lastName", "email", "department", "manager",
        "status", "lastLogin", "created", "groups", "apps",
        "groupCount", "appCount"
    ]

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    print(f"\nReport exported to: {OUTPUT_FILE}")
    print(f"Total users: {len(report_rows)}")
    print(f"Total with group assignments: {sum(1 for r in report_rows if r['groupCount'] > 0)}")
    print(f"Total with app assignments: {sum(1 for r in report_rows if r['appCount'] > 0)}")


if __name__ == "__main__":
    run_access_report()
