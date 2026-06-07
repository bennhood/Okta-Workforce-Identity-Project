# API Automation: Okta REST API Scripts

This document covers the Python scripts written to interact with the Okta REST API programmatically, demonstrating automation capabilities beyond the Admin Console UI.

---

## Overview

All scripts use the Okta REST API with SSWS token authentication. The scripts are located in the `scripts/` directory and can be run independently.

**Base URL:** `https://integrator-1186065.okta.com/api/v1/`

**Authentication:** All requests include the header:
```
Authorization: SSWS {API_TOKEN}
```

---

## Scripts Summary

| Script | Purpose | Output |
|---|---|---|
| `create_users_from_csv.py` | Bulk provision users from HR CSV | Terminal + Okta user accounts |
| `policy_export.py` | Export all authentication policies | `auth-policies.json` + `acmecorp-policy-rules.json` |
| `joiner_workflow.py` | Joiner provisioning notifications | Terminal + Slack messages |
| `mover_workflow.py` | Mover group and profile updates | Terminal + Slack messages + Okta group changes |
| `leaver_workflow.py` | Leaver deactivation and offboarding | Terminal + Slack messages + Okta deactivation |
| `access_report.py` | Full user access report | `okta-access-report.csv` |
| `stale_accounts.py` | Stale account detection | `stale-accounts-report.csv` |

---

## access_report.py

Generates a complete access report across all active Okta users - groups, apps, and last login - exported as a CSV.

**API endpoints used:**
- `GET /api/v1/users?filter=status eq "ACTIVE"` - fetch all active users
- `GET /api/v1/users/{id}/groups` - fetch group memberships per user
- `GET /api/v1/users/{id}/appLinks` - fetch app assignments per user

**Key implementation detail - pagination:**
Okta limits API responses to 200 records per page. The script handles pagination by inspecting the `Link` response header for a `rel="next"` URL and following it until all pages are retrieved. Without this, the script would silently miss users in any org over 200 accounts.

**Output columns:**
`firstName`, `lastName`, `email`, `department`, `manager`, `status`, `lastLogin`, `created`, `groups`, `apps`, `groupCount`, `appCount`

<img width="1258" height="757" alt="Access_reportPromptPS" src="https://github.com/user-attachments/assets/69fec05e-6853-49e4-9be6-745ddb058a6d" />

<img width="2452" height="589" alt="access_report_CSV-Results" src="https://github.com/user-attachments/assets/fb6b92d4-61e4-48c0-8287-de30367780f6" />

---

## stale_accounts.py

Identifies active Okta accounts that have not logged in for 90+ days, or have never logged in. Exports flagged accounts with recommended actions.

**API endpoints used:**
- `GET /api/v1/users?filter=status eq "ACTIVE"` - fetch all active users
- `GET /api/v1/users/{id}/groups` - fetch groups for flagged users

**Stale criteria:**
- Last login more than 90 days ago
- Account active but never logged in

**Configurable thresholds:**
```python
STALE_DAYS = 90       # Adjust threshold
NEVER_LOGGED_IN = True  # Toggle never-logged-in detection
```

**Lab results:** 6 of 7 lab users flagged as stale - all created via script and never authenticated. This is expected in a lab environment and demonstrates the detection logic working correctly.

<img width="1260" height="1101" alt="stale_accounts_prompt-output" src="https://github.com/user-attachments/assets/0448b601-addc-4daa-b28f-8b54bd82e860" />

<img width="2387" height="584" alt="stale_accounts_CSV-Results" src="https://github.com/user-attachments/assets/e5daef7b-3a41-47ca-9956-6cf1a7459a8f" />

---

## policy_export.py

Exports all Okta authentication policies and the AcmeCorp Global Policy rules as JSON files.

**API endpoints used:**
- `GET /api/v1/policies?type=OKTA_SIGN_ON` - Global Session Policies
- `GET /api/v1/policies?type=ACCESS_POLICY` - App Sign-On Policies
- `GET /api/v1/policies/{id}/rules` - Rules for a specific policy

**Output files:**
- `configs/auth-policies.json` - all policies across both types
- `configs/acmecorp-policy-rules.json` - AcmeCorp Global Policy rules with full constraint config

This export serves as **policy-as-code** documentation - the JSON files can be used to recreate the policy configuration in another Okta tenant, or to track changes over time via Git diff.

<img width="1255" height="853" alt="Policy-export-Python-execution" src="https://github.com/user-attachments/assets/d31abf40-65e6-40a3-8aef-bf5b136d2ba6" />

---

## API Token Security

All scripts use an environment variable pattern for the API token. In production:

```python
import os
API_TOKEN = os.environ.get("OKTA_API_TOKEN")
```

This prevents the token from being hardcoded and accidentally committed to version control. For this lab, the token is set directly in the script - the scripts are committed to GitHub with the token value removed and replaced with `"your-okta-api-token-here"`.

**Token scope:** The API token inherits the permissions of the Okta admin user who created it. In production, a service account with the minimum required role (Read Only Admin for reporting scripts, Super Admin only where write access is needed) would be used instead.

---

## Production Considerations

- Replace SSWS token authentication with **OAuth 2.0 service app** authentication - more secure, token rotation built in, and scoped to specific API permissions
- Run reporting scripts on a scheduled basis via cron or a task scheduler, outputting to a shared drive or SIEM
- Add email alerting to the stale accounts script - automatically notify managers when their direct reports are flagged
- Parameterise all scripts with `argparse` to allow threshold and filter changes at runtime without editing source code
- Store output CSVs in a version-controlled location for audit trail comparison across report runs
