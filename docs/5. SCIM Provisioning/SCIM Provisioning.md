# SCIM 2.0 Provisioning

## Why this section exists

The Identity Lifecycle Automation section of this project automates Joiner,
Mover and Leaver events using the Okta API, with Slack as a notification
layer. What it could not demonstrate on the Okta Integrator Free plan was
provisioning through **SCIM** - the System for Cross-domain Identity
Management protocol (RFC 7643/7644) that enterprise Okta deployments use to
push identities into downstream applications.

Rather than leave SCIM as a documented limitation, this section closes the
gap from the other side: instead of provisioning *to* a SaaS app's SCIM
endpoint, I built the SCIM endpoint itself - a SCIM 2.0 service provider
that Okta provisions into. Okta acts as the SCIM client; my server is the
SCIM target. Every provisioning event Okta emits is received, processed and
logged by code I wrote, which means the protocol exchange is observable from
both sides.

## SCIM vs vendor APIs - the distinction that matters

It is easy to conflate "API-based provisioning" with SCIM. They are not the
same thing:

- A **vendor API** (the Okta REST API, Microsoft Graph, the Slack Bot API)
  is proprietary. Each has its own endpoints, schemas and auth quirks, and
  an integration written for one is useless against another.
- **SCIM** is a standard. Any compliant client can provision into any
  compliant service provider using the same `/Users` and `/Groups`
  endpoints, the same JSON schemas, and the same operations. It exists
  precisely so that identity teams do not have to write a bespoke
  integration for every application.

This project now demonstrates both patterns deliberately: vendor-API
automation in the lifecycle scripts, and the SCIM standard here.

## Architecture

```
                       SCIM 2.0 protocol over HTTPS
  ┌──────────┐   Authorization: Bearer <shared secret>   ┌──────────────────┐
  │   Okta   │ ─────────────────────────────────────────▶│  scim_server.py  │
  │  (SCIM   │      GET /scim/v2/Users?filter=...        │  (FastAPI - the  │
  │  client) │      POST /scim/v2/Users                  │  SCIM service    │
  │          │      PATCH /scim/v2/Users/{id}            │  provider)       │
  └──────────┘                                           └──────────────────┘
        │                                                          │
   App: SCIM 2.0 Test App                              ngrok HTTPS tunnel to
   (OAuth Bearer Token)                                localhost - public URL
```

The server is ~300 lines of Python (FastAPI). It implements the SCIM user
endpoints (list/filter, create, replace, patch, delete), a minimal Groups
resource, the `ServiceProviderConfig` discovery endpoint Okta probes during
setup, bearer-token authentication, and a live dashboard that displays every
inbound SCIM call with its full JSON payload.

For the demonstration the server runs locally and is exposed over HTTPS with
an ngrok tunnel. The store is in-memory by design - this is a protocol
demonstration, not a persistence exercise.

## What Okta actually sends

The value of owning the target side is that the protocol stops being
abstract. These are the calls observed during the demonstration:

**Credential test** - on saving the integration, Okta probes the endpoint:

```
GET /scim/v2/Users?startIndex=1&count=2
```

**Joiner (user assigned to the app)** - Okta always checks for an existing
account before creating one:

```
GET  /scim/v2/Users?filter=userName eq "john.smith@acmecorp.com"
POST /scim/v2/Users
{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
  "userName": "john.smith@acmecorp.com",
  "name": { "givenName": "John", "familyName": "Smith" },
  "emails": [{ "primary": true, "value": "john.smith@acmecorp.com", "type": "work" }],
  "active": true,
  ...
}
```

The filter-then-create sequence is SCIM's idempotency pattern: the client
queries by `userName` and only POSTs if no match exists, so re-assigning a
user never creates a duplicate.

**Leaver (user unassigned)** - deactivation, not deletion:

```
PATCH /scim/v2/Users/{id}
{
  "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
  "Operations": [{ "op": "replace", "value": { "active": false } }]
}
```

Okta deliberately sets `active: false` rather than sending DELETE - the
same revoke-access-but-retain-the-account principle implemented in the
T+0/T+30d leaver SLA elsewhere in this project, here expressed natively by
the protocol.

## Evidence

<!-- Screenshots -->
<img width="2520" height="1680" alt="SCIM Empty Call" src="https://github.com/user-attachments/assets/a397f89f-0f1d-43e4-952b-dd60233de9b4" />
<img width="2462" height="1264" alt="SCIMAssignFirstUser" src="https://github.com/user-attachments/assets/93b3467d-1bac-4679-86aa-3a1606c6a0b2" />
<img width="2427" height="1450" alt="SCIMMultipleUsers" src="https://github.com/user-attachments/assets/dc6ee1f5-3625-493c-b657-e450a3fe4260" />
<img width="1356" height="1375" alt="SCIMUserRemove1" src="https://github.com/user-attachments/assets/2a0af457-ea6b-42e5-94c4-3d1ab0c217d9" />
<img width="2413" height="609" alt="UnassignedUsers" src="https://github.com/user-attachments/assets/1b080bde-8794-4100-8004-552179afc39f" />
<img width="1348" height="1351" alt="SCIMUserProv1" src="https://github.com/user-attachments/assets/2e0cc70d-61b6-40d0-a0ba-a4afda1defa5" />
<img width="1368" height="1382" alt="Logs 2 SCIM evidence" src="https://github.com/user-attachments/assets/2db88aa1-d1e8-441e-b5d2-832070eb1842" />


The matched pair - Okta's System Log showing the event sent, the server's
feed showing the identical event received - is the end-to-end proof.

## Troubleshooting note: an auth-scheme mismatch

The integration initially failed Okta's credential test with a 401 despite
the bearer token being verified correct against the server directly. The
server console showed the pattern clearly: local test requests returning
200, Okta's requests (arriving from its AWS egress IP through the tunnel)
returning 401 seconds later - same server, same token, different result.

Capturing the inbound traffic identified the cause: the app added in Okta
was the **SCIM 2.0 Test App (Header Auth)** variant, which delivers the
token in a custom header format, while the server validates the standard
`Authorization: Bearer <token>` scheme. Replacing it with the
**SCIM 2.0 Test App (OAuth Bearer Token)** variant resolved it immediately.

The takeaway generalises: when authentication fails between two systems
that each look correct in isolation, inspect the actual request on the
wire rather than re-checking configuration screens. The mismatch is
usually visible in one captured header.

## Production considerations

This server is deliberately minimal. A production SCIM service provider
would additionally need:

- **Persistent storage** in place of the in-memory store
- **Full filter grammar** - the spec defines a rich filter language; this
  implementation supports the `userName eq` form Okta uses for its
  pre-create check
- **ETag/versioning support** for concurrent-update safety
- **Pagination hardening** and the `/Schemas` and `/ResourceTypes`
  discovery endpoints for full spec compliance
- **A stable HTTPS endpoint** with a real certificate rather than a tunnel

None of these change the protocol semantics demonstrated here - they harden
the implementation around it.
