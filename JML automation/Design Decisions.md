# Design Decisions & Known Limitations

This lab automates the full joiner/mover/leaver (JML) lifecycle in Python,
provisioning users and groups across Okta and Microsoft Entra ID in a single
run via the Okta API and Microsoft Graph API. It is deliberately a **lab
substitute for managed provisioning** - the Okta-to-Entra path that a
production estate would run through a SCIM connector or an IGA platform
(SailPoint, Saviynt) rather than hand-rolled scripts.

The value of building it by hand is that every production concern below was
hit, understood, and either solved or consciously scoped out. This document
records those decisions so the simplifications read as choices, not oversights.

## What the lab implements

- **Joiner** - Okta users provisioned into Entra ID (Graph `POST /users`),
  assigned to their department security group via `$ref` member writes, and
  linked to their manager via the `manager/$ref` relationship (a directory
  relationship in Graph, not a create-payload field - a distinction that
  silently drops data if missed).
- **Mover** - separation-of-duties ordering: old department group removed
  before new group granted, department attribute patched in both Okta and
  Entra.
- **Leaver (T+0)** - Okta deactivation (kills SSO sessions), Entra
  `accountEnabled: false`, **and** `revokeSignInSessions`. Disabling alone
  only blocks *new* sign-ins; tokens already issued stay valid until expiry,
  so revocation is what actually terminates access at T+0. T+24h group
  cleanup and T+30d deletion are documented SLA stages, not automated.
- **Plumbing** - OAuth 2.0 client-credentials flow with token caching and
  mid-run 401 refresh; a single request handler enforcing timeouts,
  Retry-After-honouring 429 backoff, and exponential 5xx retry; Okta
  Link-header and Graph `@odata.nextLink` pagination; per-user random
  temporary passwords; conflict detection keyed on Graph error codes with a
  message fallback (user-create conflicts surface under the generic
  `Request_BadRequest` code); eventual-consistency retry loops on reads
  immediately after writes; idempotent re-runs (already-exists is success).

## Known limitations - and what production does instead

**1. "Absent from Okta" is not a reliable leaver signal.**
The scripts treat active-in-Okta-with-a-department as the managed population.
Real directories contain SUSPENDED/STAGED/PROVISIONED states, contractors,
service accounts, break-glass accounts, and attribute gaps - any of which
this heuristic would misread. Production engines map source lifecycle states
to target actions explicitly and wrap destructive operations in a circuit
breaker (cf. Entra provisioning's *accidental deletion prevention*): if a run
wants to deactivate more than a threshold of accounts, it halts for human
review. The bulk reconciler in this repo implements that breaker.

> **Observed live (July 2026), twice.** First: a reactivated user sat in
> Okta's PROVISIONED state ("pending user action") and was silently excluded
> from a joiner run - the ACTIVE-only filter misread an existing employee as
> out of scope, exactly as predicted. Second, and sharper: a reconciler dry
> run proposed disabling two Entra accounts absent from Okta desired state -
> one of which was the **tenant admin** (a guest `#EXT#` identity that passed
> the domain scoping check). The plan contained exactly 2 disables against a
> circuit-breaker threshold of 2 ("more than"), so the breaker alone would
> not have stopped `--apply`, and applying would have risked admin lockout.
> The dry-run-by-default design caught it. Fix: a protected-account scoping
> filter (`_is_protected`) excluding guests and an explicit `PROTECTED_UPNS`
> list at the *read* layer, so protected identities never enter the diff and
> no plan can ever contain them. Scoping was chosen over a lower threshold
> deliberately: thresholds bound blast radius, scoping removes the target
> entirely - which is why production provisioning defines the managed
> population with scoping filters before any logic runs, rather than vetoing
> actions afterwards.

**2. Email/UPN is used as the cross-tenant join key.**
Email is mutable and recyclable - people rename, leave, and have addresses
reissued. Production provisioning stamps an immutable anchor (the Okta user
ID written to an Entra attribute such as `employeeId` at create time) and
joins on that forever after. At this lab's scale the email join is safe; at
organisational scale it is a correctness bug waiting for the first rename.

**3. Department is treated as entitlement policy.**
`f"{department}-Staff"` collapses what should be a policy layer into string
interpolation. Production access models (birthright policies in IGA terms)
resolve attributes - department, employee type, location - through a policy
table to a *set* of entitlements, so access rules can change without code
changes.

**4. T+24h/T+30d offboarding stages are documented, not automated.**
T+0 access termination is fully automated (deactivate + disable + revoke).
Full offboarding additionally removes group memberships, reclaims licenses,
strips privileged role assignments, and eventually deletes - staged over
time to preserve data and mailbox access for handover. The lab documents
this SLA rather than automating it.

## Bugs found during live validation

The full JML cycle was executed end to end against live tenants (July 2026).
Beyond the scoping incident above, one further defect was found and fixed -
recorded here because the *mechanism of discovery* is the point.

**`requests.Response` truthiness made the conflict handler unreachable.**
In Python's `requests` library, a Response object's truthiness is
`status_code < 400`. Guards written as `if response and
response.status_code == 400:` can therefore never fire - a 400 response is
falsy, so the already-exists conflict branch in group assignment was dead
code. The first joiner run passed cleanly (every membership add returned
204); the *idempotent re-run* exposed it, with all seven already-member
adds burning through retries into false "assignment failed" reports while
the tenant state remained perfectly correct. Root cause fixed across the
module by replacing every truthiness guard with explicit `is not None`
checks. The unit tests had passed throughout because the stub Response
class did not replicate `__bool__` - the test doubles were rewritten to be
falsy on 4xx/5xx, and the live failure scenario now exists as a regression
test. Two lessons banked: idempotent re-runs are a test case, not a
formality, and a test double that does not replicate the real object's
semantics is a double that lies.

## If I scaled this (100s-1,000s of users)

The per-user scripts are the event-driven path: correct for single
joiners/movers/leavers, wrong shape for bulk. `entra_reconcile.py` is the
scale-pattern extension: read desired state (Okta, paginated), read actual
state (Entra users + group memberships), diff in memory, and apply only the
delta via Graph `$batch` (20 operations per call, with per-sub-request
retry - Graph does not auto-retry throttled requests inside a batch). A
clean tenant produces an empty plan and zero writes; a partial failure is
recovered by re-running.

Beyond that, the remaining production changes are input-feed swaps, not
structural ones: Graph delta queries and Okta event hooks replace the
full-scan read (polling and scanning collections is the pattern Microsoft's
throttling guidance explicitly warns against), structured logging and a
dead-letter queue replace stdout, and - the honest endgame - a managed SCIM
connector or IGA platform replaces the hand-rolled engine entirely, at which
point this codebase's value is that its author knows exactly what that
connector is doing and why.
