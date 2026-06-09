# Okta Workforce Identity Lab - WIP - SCIM/EntraID phase.

A hands-on enterprise IAM lab environment demonstrating real-world identity and access management across SSO federation, adaptive MFA, and automated identity lifecycle management using **Okta Workforce Identity**.

---

## Overview

This project simulates an enterprise identity environment for a fictitious organisation, **AcmeCorp**, across three departments: Engineering, Finance, and HR. It was built to demonstrate practical IAM skills directly mapped to enterprise requirements - from protocol-level SSO configuration and risk-based MFA policy design, through to programmatic identity lifecycle automation via the Okta REST API and Slack Bot API.

Designed to expand on and implement my Identity Access Management conceptual understanding in real-world sceanario's post securing the SC-300 certification, in efforts towards targeting Identity Access Management roles.

---

## Architecture

<img width="1347" height="1145" alt="scrnli_78dX0IR0KK8Vvh" src="https://github.com/user-attachments/assets/121ac404-7add-439b-993c-b676aa312b96" />

---

## Environment

| Component | Platform | Role |
|---|---|---|
| Identity Provider | Okta Integrator Free Plan | Core IAM platform |
| SAML SP | Salesforce Developer Edition | SAML 2.0 federation target |
| OIDC Relying Party | Node.js Express (local) | OIDC authorization code flow |
| Provisioning Target | Slack (free tier) | JML notification target |
| HR Source | Google Sheets CSV | Mock HR system / source of truth |
| Version Control | GitHub | This repository |

---

## What Was Built

### 1 - SSO Federation

Configured Okta as an Identity Provider for two SSO protocols:

**SAML 2.0** - Salesforce Developer Edition as the Service Provider. Both SP-initiated and IdP-initiated flows configured and tested. SAML assertion attributes mapped and verified via the Okta System Log and Salesforce Login History.

**OIDC (Authorization Code Flow)** - locally hosted Node.js Express application as the Relying Party. Full token exchange flow demonstrated, with the authorization code visible in DevTools and claims rendered on the application profile page.

→ Documentation: [`SSO Federation`](<docs/1. SSO Federation>)

---

### 2 - Adaptive MFA & Risk-Based Access

Designed and implemented a tiered, risk-based authentication policy using Okta Authentication Policies and Network Zones, replicating a corporate conditional access model.

**Two-tier policy enforced:**

| Condition | Authentication Requirement |
|---|---|
| IP in AcmeCorp Office zone | Password only (1FA) |
| IP outside trusted zone | Password + possession factor (2FA) |

Three authenticator types enrolled: Okta Verify (TOTP), Google Authenticator, and Windows Hello (FIDO2/WebAuthn). Policy behaviour verified via live testing and Okta System Log comparison between both scenarios.

Policy configuration exported as JSON via the Okta REST API - committed to [`configs/`](configs) as policy-as-code.

→ Documentation: [`docs/adaptive-mfa/`](<docs/2. Adaptive MFA>)

---

### 3 - Identity Lifecycle Automation (JML)

Built a complete Joiner/Mover/Leaver automation suite using Python and the Okta REST API, with Slack Bot API for provisioning notifications.

**HR source:** Google Sheets CSV simulating a Workday/SAP SuccessFactors feed - 7 users across Engineering, Finance, and HR.

**Automation scripts:**

| Script | Trigger | Actions |
|---|---|---|
| [`create_users_from_csv.py`](scripts/create_users_from_csv.py) | Manual / HR import | Create Okta users, assign to department groups |
| [`joiner_workflow.py`](/scripts/joiner_workflow.py) | New active user detected | Post provisioning notification to department Slack channel |
| [`mover_workflow.py`](/scripts/mover_workflow.py) | Department change | Remove old group, add new group, update profile, notify both channels |
| [`leaver_workflow.py`](/scripts/leaver_workflow.py) | User offboarded | Deactivate account (T+0), remove all groups (T+24h), notify channel, log SLA |

**SCIM note:** Slack SCIM provisioning requires Business+ or Enterprise Grid. The Python + Slack Bot API implementation replicates the provisioning notification layer. In production, SCIM would handle account creation alongside the notification workflow.

→ Scripts: [`scripts/`](scripts)
→ Documentation: [`docs/identity-lifecycle/`](<docs/3. Identity Lifecycle Automation>)

---

### 4 - API Automation & Access Reporting

Python scripts using the Okta REST API for access reporting and stale account detection.

| Script | Purpose | Output |
|---|---|---|
| [`access_report.py`](/scripts/access_report.py) | Full user access report - groups, apps, last login | `okta-access-report.csv` |
| [`stale_accounts.py`](/scripts/stale_accounts.py) | Flag accounts inactive 90+ days or never logged in | `stale-accounts-report.csv` |
| [`policy_export.py`](/scripts/policy_export.py) | Export authentication policies as JSON | `configs/auth-policies.json` |

All scripts handle Okta API pagination via the `Link` response header.

→ Scripts: [`scripts/`](/scripts/)
→ Documentation: [`docs/api-automation/`](<docs/4. API Automation>)

---

## Key Learnings

- SP-initiated SAML fails with a 400 error if the ACS URL in Okta doesn't exactly match the SP's registered endpoint - a trailing path difference (`/callback` vs `/authorization-code/callback`) is enough to break it
- The OIDC authorization code flow keeps the ID token entirely server-side - the browser receives only a session cookie, visible in DevTools as a `302` redirect with no token in the response body
- Okta's two-layer policy model (Global Session Policy + App Authentication Policy) means app-level trusted network rules won't suppress MFA unless both layers are considered together
- `UNSATISFIABLE` errors in Okta policy evaluation indicate a mismatch between what the authentication policy requires and what the enrollment policy permits - not an authentication failure
- Okta's System Log distinguishes IdP-layer failures from SP-layer failures, enabling SSO triage without SP log access

---

## If I Were Scaling This

- **Terraform** - manage all Okta config as version-controlled HCL using the Okta Terraform Provider
- **HR connector** - replace CSV import with a native Okta HR Sourcing connector (Workday, SAP SuccessFactors)
- **SCIM provisioning** - replace Slack Bot API with SCIM 2.0 on Business+ for full account lifecycle management
- **Device Trust** - integrate Okta with Intune or Jamf for genuine managed vs unmanaged device differentiation in MFA policy
- **OAuth 2.0 service app** - replace SSWS token auth with OAuth 2.0 client credentials for scoped, rotatable API access
- **SIEM integration** - pipe Okta System Log to Splunk or Sentinel for real-time alerting and SLA breach detection
- **Scheduled reporting** - run access and stale account reports on a weekly cron schedule with manager alerting

---

## Repository Structure

```
okta-iam-lab/
├── README.md
├── docs/
│   ├── architecture.png
│   ├── protocol-decision-guide.md
│   ├── sso-federation/
│   │   ├── saml-salesforce-config.md
│   │   ├── oidc-token-anatomy.md
│   │   └── sso-troubleshooting.md
│   ├── adaptive-mfa/
│   │   ├── network-zones.md
│   │   ├── authenticator-comparison.md
│   │   └── auth-policy-design.md
│   ├── identity-lifecycle/
│   │   ├── attribute-mapping.md
│   │   ├── scim-provisioning.md
│   │   └── jml-sla.md
│   └── api-automation/
│       └── api-scripts.md
├── configs/
│   ├── auth-policies.json
│   └── acmecorp-policy-rules.json
└── scripts/
    ├── create_users_from_csv.py
    ├── policy_export.py
    ├── joiner_workflow.py
    ├── mover_workflow.py
    ├── leaver_workflow.py
    ├── access_report.py
    └── stale_accounts.py
```

---

## Tools & Platforms

- [Okta Workforce Identity](https://developer.okta.com) - Integrator Free Plan
- [Salesforce Developer Edition](https://developer.salesforce.com)
- [Slack](https://slack.com) - Free tier + Bot API
- Python 3.11 - `requests`, `csv`, `json`
- Node.js / Express - Okta OIDC sample app
- [draw.io](https://app.diagrams.net) - Architecture diagram
