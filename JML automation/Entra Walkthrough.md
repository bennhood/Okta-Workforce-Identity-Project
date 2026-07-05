# Entra ID JML Walkthrough - Run Sequence & Evidence

This document walks the full joiner/mover/leaver lifecycle across Okta and
Microsoft Entra ID as executed against live tenants (July 2026), with the
expected output at each stage and the screenshot evidence that accompanies
each step. Terminal excerpts are from the actual runs.

**Baseline:** 7 Okta users across Engineering (3), Finance (3), HR (1), each
with `department` and `manager` profile attributes populated (manager as an
email address - the joiner only attempts the Entra manager relationship when
the value is resolvable). Entra ID starts empty of lab users. Setup:
`cp .env.example .env`, fill in credentials; the app registration requires
`User.ReadWrite.All` and `Group.ReadWrite.All` (Application, admin
consented).

---

## Step 0 - Connectivity test

```
python entra_sync.py
```

Proves the three permission tiers independently before any workflow runs:
token acquisition (credentials + tenant), user provisioning
(`User.ReadWrite.All`), group creation and assignment
(`Group.ReadWrite.All`). Provisions one test user (nick.front) as a side
effect.

Expected output includes the eventual-consistency handling working live -
Graph returns 201 on create, but the object is not immediately readable:

```
[3] Verifying user in Entra ID...
    Not yet indexed - retrying in 3s (attempt 1/4)...
    Not yet indexed - retrying in 3s (attempt 2/4)...
    OK - Nick Front (nick.front@benhood98aol.onmicrosoft.com)
```

<img width="1046" height="1012" alt="Entra_sync 1" src="https://github.com/user-attachments/assets/0f86c6d5-bee7-4954-b51b-fc5f036a63c6" />
<img width="1911" height="626" alt="Entra_sync 2" src="https://github.com/user-attachments/assets/3c5f507d-01dc-4c70-96af-e6974e43a620" />


## Step 1 - Joiner (bulk provisioning)

```
python joiner_workflow.py
```

For each active departmental Okta user: Slack notification to the department
channel, Entra user creation, security-group assignment via `$ref` member
write, and manager assignment via the `manager/$ref` relationship (a
directory relationship in Graph, not a create-payload field).

```
Processing joiner: Jenny Gump (jenny.gump@acmecorp.com)
  Slack notification sent to #engineering-staff
  [Entra] Provisioned → jenny.gump@benhood98aol.onmicrosoft.com
  [Entra] Waiting for user to be indexed (1/5)...
  [Entra] Assigned to group: Engineering-Staff
  [Entra] Manager set → ben.hood@acmecorp.com
```

<img width="1189" height="1680" alt="Joiner 1" src="https://github.com/user-attachments/assets/88ca8ee6-fe6e-4a8c-9702-f4dca4b644e0" />
<img width="1934" height="607" alt="Joiner 1 portal" src="https://github.com/user-attachments/assets/557eeaac-7bfa-4d67-bec2-377c144fba56" />
<img width="1827" height="326" alt="Joiner 1 portal2" src="https://github.com/user-attachments/assets/271d08ac-6ab3-4399-ba75-7e20fe3d38bf" />
<img width="1846" height="1053" alt="Joiner 1 portal3" src="https://github.com/user-attachments/assets/5b109efc-c56a-4e2c-9c1c-782e12697ea5" />
<img width="1254" height="813" alt="SlackNotifs" src="https://github.com/user-attachments/assets/5b53a1b6-7dd3-4328-a42b-949642eb6e92" />

### Idempotency proof - the same command, re-run

A second run makes no changes and creates no duplicates: every user reports
`Already exists`, every membership `Already in group`. The re-run is a test
case, not a formality - it exposed a real bug on first execution (the
`requests` truthiness defect documented in DESIGN-DECISIONS.md, with the
before/after terminal pair as evidence).

<img width="1194" height="1680" alt="Joiner 2 - Manager Assigned 400 Code FIXED" src="https://github.com/user-attachments/assets/d2bb2297-8e7e-4efd-9bdf-eb3f693420c0" />

## Step 2 - Mover (department transfer)

```
python mover_workflow.py
```

Robert Fisher, Finance to Engineering, with separation-of-duties ordering:
old access removed before new access granted, on both platforms, then the
department attribute patched in Okta and Entra and both department channels
notified.

```
  Removed from group: Finance-Staff
  Added to group: Engineering-Staff
  Okta profile updated: department → Engineering
  [Entra] Department updated → Engineering (robert.fisher@...)
  [Entra] Removed from group: Finance-Staff
  [Entra] Assigned to group: Engineering-Staff
```

Note the absence of retry lines: the mover operates on long-settled objects,
so no eventual-consistency window applies - the contrast with the joiner's
create-then-reference pattern is itself demonstrative.

<img width="1440" height="773" alt="Movers" src="https://github.com/user-attachments/assets/2fb3ed9e-b6a3-4908-8289-e7131a9cb935" />
<img width="1728" height="1059" alt="Movers PORTALs" src="https://github.com/user-attachments/assets/3564b0f1-fee0-4358-b638-76b812c348aa" />
<img width="931" height="176" alt="Movers SlackNotif" src="https://github.com/user-attachments/assets/dcd12613-b882-4dbf-afb1-8ba682159232" />

## Step 3 - Leaver (T+0 offboarding)

```
python leaver_workflow.py
```

The T+0 kill chain for nick.front: Okta deactivation (terminates SSO
sessions), Entra `accountEnabled: false` (blocks new sign-ins), and
`revokeSignInSessions` (invalidates tokens already issued - without this, a
leaver retains Microsoft 365 access until token expiry, up to an hour after
"offboarding"). T+24h group cleanup and T+30d deletion are documented SLA
stages, deliberately not automated.

```
--- T+0 Immediate Actions ---
  Okta account deactivated - all active sessions terminated
  [Entra] Account disabled → nick.front@benhood98aol.onmicrosoft.com
  [Entra] Sessions and refresh tokens revoked → nick.front@...
  Slack notification sent to #hr-staff
```

<img width="1423" height="780" alt="Leavers" src="https://github.com/user-attachments/assets/6e786dc9-7d16-4140-a3a4-fae1666761e8" />
<img width="1902" height="1483" alt="Leavers PORTALs" src="https://github.com/user-attachments/assets/768b7340-b55b-4480-9bcd-00cb29781147" />
<img width="1155" height="549" alt="Leavers SlackNotifs" src="https://github.com/user-attachments/assets/bd8cce95-afac-4067-9b47-8d28446ef06c" />

## Step 4 - Reconciliation audit (dry run)

```
python entra_reconcile.py
```

The independent audit of everything above: reads all of Okta (desired
state), all of managed Entra (actual state), diffs, and prints the plan.
Dry run is the default; `--apply` is a deliberate second step taken only
after a human has read the plan.

The first dry run of the completed cycle demonstrated exactly why: it
proposed disabling two accounts outside Okta desired state - one of them
the tenant admin. The dry-run gate caught it; the fix (protected-account
scoping at the read layer) is documented in DESIGN-DECISIONS.md. After the
fix, the plan converges to empty:

```
[1/4] Reading desired state from Okta...
      6 lifecycle-managed user(s)
[2/4] Reading actual state from Entra ID...
      7 user(s), 7 membership(s)
[3/4] Diffing...
Reconciliation plan - 0 change(s):
  Entra ID matches Okta desired state. Nothing to do.
```

Reading the numbers: 6 desired (Nick's deactivation removed him from the
managed population), 7 actual (9 Entra users minus 2 protected), 0 changes
(joiner, mover, and leaver left both platforms in agreement). Memberships
still count Nick's Engineering-Staff entry: leavers fall outside desired
state, so their memberships are not diffed - a scope boundary that happens
to align with the T+24h SLA.

<img width="1137" height="626" alt="reconcile DRYRUN Wants to delete Tenant Owner big no no" src="https://github.com/user-attachments/assets/f1ec744e-90ea-4702-a1b6-6279c9a38d5a" />
<img width="1032" height="592" alt="reconcile Ammendments" src="https://github.com/user-attachments/assets/569f9b63-0ead-42aa-b66c-8953c9fc32bb" />

---

The empty reconciliation plan after a full lifecycle cycle is the closing
evidence: the pipeline does not just run - its end state is independently
auditable and provably consistent across both platforms.
