# SCIM Provisioning & Slack Integration

This document covers the attempted SCIM configuration between Okta and Slack, the free-tier limitation encountered, and the Python-based alternative implemented for the lab.

---

## SCIM Overview

SCIM (System for Cross-domain Identity Management) is an open standard protocol (RFC 7643/7644) that enables automated user provisioning between an Identity Provider and downstream applications. Okta acts as the SCIM client, and the target application (Slack, in this case) acts as the SCIM server.

A SCIM integration automates:
- **User creation** - when a user is assigned to an app in Okta, Okta POSTs to the app's SCIM endpoint to create the account
- **Attribute sync** - profile changes in Okta are PATCHed to the downstream app
- **Deprovisioning** - when a user is unassigned or deactivated in Okta, Okta sends a PATCH to set `active: false` on the SCIM user

---

## Slack SCIM - Free Tier Limitation

Slack's SCIM API is available on **Business+ and Enterprise Grid plans only**. The free workspace used in this lab does not provide a SCIM Bearer Token, which is required to configure the Okta SCIM integration.

<img width="1365" height="1262" alt="SlackIntegrationLimitations" src="https://github.com/user-attachments/assets/d447f8f2-eaea-4edd-b8ac-4ca1a63423bc" />

This is a real-world constraint - SCIM provisioning to Slack requires a paid Slack licence in production environments. The lab documents this limitation and implements an equivalent Python-based provisioning notification layer as the alternative.

---

## Alternative: Python API + Slack Bot

In place of SCIM, a Python script using the Okta REST API and Slack Bot API was implemented to demonstrate the equivalent provisioning event chain.

### Slack App Configuration

A Slack Bot (`AcmeCorp IAM Bot`) was created via api.slack.com with the following OAuth scopes:

| Scope | Purpose |
|---|---|
| `chat:write` | Post provisioning notifications to channels |
| `channels:read` | Read channel list for routing logic |

The bot was added to each department channel manually.

### Department Channel Mapping

| Department | Slack Channel |
|---|---|
| Engineering | #engineering-staff |
| Finance | #finance-staff |
| HR | #hr-staff |

<img width="561" height="236" alt="SlackChannels" src="https://github.com/user-attachments/assets/28eb0a26-e155-41af-acea-3b3ac5bec6f2" />

---

## Joiner Workflow

**Script:** `scripts/joiner_workflow.py`

**Trigger:** Run against all active Okta users (lab demo) or users created in the last 24 hours (production mode)

**Logic:**
1. Fetch active users from Okta API
2. Filter users with a department attribute
3. Map department to Slack channel
4. Post a formatted provisioning notification to the correct channel

<img width="1151" height="1680" alt="JoinerSlackMessageExecutable" src="https://github.com/user-attachments/assets/08bb3b47-ff39-46b4-bc5e-3eeb6d29ed8d" />

<img width="2504" height="1466" alt="JoinerSlackMessagePostScriptProofs1" src="https://github.com/user-attachments/assets/36e7cf02-b79a-41c3-886c-b57d1772c978" />

<img width="2506" height="1456" alt="JoinerSlackMessagePostScriptProofs2" src="https://github.com/user-attachments/assets/6dcca6a5-efdb-4245-a321-806ce619aa50" />

<img width="2493" height="1463" alt="JoinerSlackMessagePostScriptProofs3" src="https://github.com/user-attachments/assets/92a4e09b-604e-45ea-b0f4-c42fc48dd43e" />

---

## Mover Workflow

**Script:** `scripts/mover_workflow.py`

**Test scenario:** Robert Fisher transferred from Engineering → Finance

**Logic:**
1. Fetch user by email from Okta
2. Remove from old department group (Engineering-Staff)
3. Add to new department group (Finance-Staff)
4. Update department attribute on Okta user profile
5. Post departure notification to old channel (#engineering-staff)
6. Post arrival notification to new channel (#finance-staff)

<img width="1116" height="593" alt="MoverEngFinRobertExecutable" src="https://github.com/user-attachments/assets/ccbd3f28-9ceb-4e70-89e8-f18062371d75" />

<img width="1349" height="897" alt="FinancenNew" src="https://github.com/user-attachments/assets/8e35975e-0a43-477d-87ab-3be5e931f69e" />

<img width="1450" height="1394" alt="MoverSlackMessagePostScriptProofs1" src="https://github.com/user-attachments/assets/203875ea-4a35-4488-aef8-a16937d4db2e" />

<img width="1435" height="1400" alt="MoverSlackMessagePostScriptProofs2" src="https://github.com/user-attachments/assets/05693c56-11a6-4407-89b4-a78b2108db81" />


---

## Leaver Workflow

**Script:** `scripts/leaver_workflow.py`

**Test scenario:** Nick Front offboarded

**Offboarding SLA:**

| Timeline | Action | Status |
|---|---|---|
| T+0h | Account deactivated - all SSO sessions revoked | ✓ Implemented |
| T+24h | All group memberships removed | ✓ Simulated immediately in lab |
| T+30d | Account permanently deleted | Documented - not automated in lab |

**Logic:**
1. Fetch user by email from Okta
2. Log all current group memberships (audit trail)
3. Deactivate account via `/lifecycle/deactivate` - immediately revokes all active sessions
4. Remove user from all non-system groups
5. Post offboarding notification to department Slack channel
6. Print SLA summary to terminal

<img width="1163" height="923" alt="LeaverOffboardNick" src="https://github.com/user-attachments/assets/5e040729-3016-4f22-a9f2-b8f1689f1aaf" />

<img width="1355" height="586" alt="Deactivated" src="https://github.com/user-attachments/assets/76b370ee-8b7f-41d6-b810-29ceb79287b2" />*

<img width="1857" height="1393" alt="LeaverOffboardNickSlackMessageProofs" src="https://github.com/user-attachments/assets/bad7519c-2d29-4a3d-840f-b23c1942b081" />

---

## Production Considerations

- Replace Python script with native Okta SCIM provisioning on Business+ Slack plan
- Implement T+30d deletion via a scheduled script or Okta Lifecycle Management rule rather than manual execution
- Add manager notification email to the Leaver workflow using Okta's email action
- Integrate with an ITSM tool (ServiceNow, Jira) to auto-create offboarding tickets and track SLA compliance
- Store the audit log to a SIEM (Splunk, Sentinel) rather than terminal output for long-term retention
