import requests
import json
import csv
import os

# Configuration
OKTA_DOMAIN = "https://integrator-1186065.okta.com"
API_TOKEN = "your-api-token-here"
CSV_FILE = "acmecorp-hr-users.csv"

headers = {
    "Authorization": f"SSWS {API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Department to group mapping
DEPARTMENT_GROUPS = {
    "Engineering": "Engineering-Staff",
    "Finance": "Finance-Staff",
    "HR": "HR-Staff"
}


def get_group_id(group_name):
    """Look up Okta group ID by name."""
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/groups?q={group_name}",
        headers=headers
    )
    if response.status_code == 200:
        groups = response.json()
        for group in groups:
            if group["profile"]["name"] == group_name:
                return group["id"]
    print(f"  Warning: Group '{group_name}' not found")
    return None


def create_user(row):
    """Create a single Okta user from a CSV row."""
    payload = {
        "profile": {
            "firstName": row["firstName"],
            "lastName": row["lastName"],
            "email": row["email"],
            "login": row["email"],
            "department": row["department"],
            "manager": row["manager"],
            "startDate": row.get("startDate", ""),
            "userType": "Employee"
        },
        "credentials": {
            "password": {
                "value": "TempPass123!"
            }
        }
    }

    response = requests.post(
        f"{OKTA_DOMAIN}/api/v1/users?activate=true",
        headers=headers,
        json=payload
    )

    if response.status_code == 200:
        user = response.json()
        print(f"  Created: {row['firstName']} {row['lastName']} ({row['email']})")
        return user["id"]
    elif response.status_code == 400:
        error = response.json()
        print(f"  Skipped: {row['email']} - {error.get('errorSummary', 'Unknown error')}")
        return None
    else:
        print(f"  Error: {response.status_code} for {row['email']}")
        print(f"  {response.text}")
        return None


def assign_to_group(user_id, group_name):
    """Assign a user to an Okta group."""
    group_id = get_group_id(group_name)
    if not group_id:
        return

    response = requests.put(
        f"{OKTA_DOMAIN}/api/v1/groups/{group_id}/users/{user_id}",
        headers=headers
    )

    if response.status_code == 204:
        print(f"  Assigned to group: {group_name}")
    else:
        print(f"  Group assignment failed: {response.status_code}")


def main():
    print(f"Reading users from {CSV_FILE}...\n")

    created = 0
    skipped = 0

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Skip inactive users
            if row.get("status", "active").lower() != "active":
                print(f"  Skipping inactive user: {row['email']}")
                skipped += 1
                continue

            print(f"Processing: {row['firstName']} {row['lastName']}")

            # Create user
            user_id = create_user(row)

            # Assign to department group
            if user_id:
                department = row.get("department", "")
                group_name = DEPARTMENT_GROUPS.get(department)
                if group_name:
                    assign_to_group(user_id, group_name)
                created += 1

            print()

    print(f"Done - {created} users created, {skipped} skipped")


if __name__ == "__main__":
    main()
