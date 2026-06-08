# JML SLA Framework: AcmeCorp

This document defines the Joiner, Mover, and Leaver Service Level Agreement (SLA) framework implemented in the AcmeCorp lab environment, with reference to production standards.

---

## Why JML SLA Matters

Identity lifecycle SLAs directly impact an organisation's security posture and compliance standing:

- **Joiner delays** - a new employee without access on day one is a productivity failure; access provisioned too broadly is a security failure
- **Mover failures** - a user who retains access from a previous role creates a Segregation of Duties (SoD) violation and a potential insider threat vector
- **Leaver gaps** - access not revoked promptly after termination is one of the most common audit findings across ISO 27001, SOC 2, and Cyber Essentials

---

## AcmeCorp JML SLA Definitions

### Joiner SLA

| Step | Action | SLA Target | Implementation |
|---|---|---|---|
| HR record created | User provisioned in Okta | Same day | Python script (manual trigger in lab; automated via HR connector in production) |
| Okta user active | Department group assigned | Immediate | Script assigns group at creation time |
| Group assigned | Slack provisioning notification sent | Immediate | joiner_workflow.py posts to department channel |
| Day 1 | User has correct access, no excess entitlements | T+0 | Group-based access ensures least privilege from creation |

---

### Mover SLA

| Step | Action | SLA Target | Implementation |
|---|---|---|---|
| HR department change | IAM team notified | Same day | In production: HR connector triggers event automatically |
| Notification received | Old group access removed | Within 4 hours | mover_workflow.py removes old group immediately |
| Old access removed | New group access granted | Immediate | mover_workflow.py adds new group in same run |
| Access updated | Slack notifications sent | Immediate | Departure + arrival messages posted to both channels |
| Completion | Okta profile updated | Immediate | department attribute updated via API |

**SoD consideration:** The Mover workflow removes old access before granting new access, ensuring no overlap period where a user simultaneously holds entitlements from two roles. This prevents the most common Mover-related SoD violation.

---

### Leaver SLA

| Step | Action | SLA Target | Implementation |
|---|---|---|---|
| Termination confirmed | Account deactivated | T+0 (immediate) | leaver_workflow.py calls /lifecycle/deactivate |
| Account deactivated | All active sessions revoked | Immediate (on deactivation) | Okta invalidates all sessions on deactivation |
| T+24h | All group memberships removed | Within 24 hours | Simulated immediately in lab; in production would be a scheduled job |
| T+30d | Account permanently deleted | 30 days post-termination | Documented SLA - not automated in lab |
| Throughout | Audit log maintained | Real-time | Terminal output + Okta System Log |

---

## Risk Classification

Different user types warrant different SLA stringency:

| User Type | Joiner SLA | Leaver SLA |
|---|---|---|
| Standard Employee | Same day provisioning | T+24h deactivation |
| Contractor | Same day, time-limited access | T+0 deactivation (immediate) |
| Privileged / Admin | Pre-approved, JIT access preferred | T+0 deactivation + PAM session termination |
| Third Party / Vendor | Scoped access only, expiry date set | T+0 on contract end |

---

## SoD Policy: Mover Scenario

A key governance requirement in the Mover workflow is preventing simultaneous access to incompatible roles. In the AcmeCorp environment, the following SoD conflict was identified and mitigated:

**Conflict:** Finance-Staff + Engineering-Staff held simultaneously

**Risk:** A user moving from Engineering to Finance could temporarily retain Engineering system access, creating a cross-department data access risk.

**Mitigation:** The Mover script removes the user from the old group before adding them to the new group. There is no window where both memberships are active.

---

## Evidence of Implementation

<img width="1116" height="593" alt="MoverEngFinRobertExecutable" src="https://github.com/user-attachments/assets/eaa2d801-b992-476e-8f2b-8c68167e6fdd" />

<img width="1163" height="923" alt="LeaverOffboardNick" src="https://github.com/user-attachments/assets/9341b89c-3fb4-4644-8f8a-c63aa4c6b6c6" />

---

## Production Considerations

- Implement SLA monitoring via Okta System Log events feeding into Splunk or Sentinel - alert if a leaver account remains active beyond SLA threshold
- Automate T+30d deletion via a scheduled Python script querying for deactivated accounts older than 30 days
- Add manager approval gate to Joiner workflow for privileged role assignments
- Integrate with ServiceNow to generate offboarding tickets with SLA tracking
- Implement access certification campaign triggered automatically 90 days after a Mover event - to verify the entitlement change was appropriate
