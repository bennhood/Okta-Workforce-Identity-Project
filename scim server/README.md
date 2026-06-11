# AcmeCorp SCIM 2.0 Server

A minimal SCIM 2.0 service provider that receives provisioning calls from Okta.
This demonstrates the SCIM **protocol** (RFC 7644), distinct from the Graph API
and Slack Bot integrations which use vendor-specific REST APIs.

## What it proves

When Okta provisions users to the SCIM app, it emits standard SCIM 2.0 calls
to this server. Every call is logged and shown live at the root URL. Those
logged JSON payloads are the evidence that this is genuine SCIM protocol
traffic, captured from both sides of the exchange.

| Okta action      | SCIM call this server receives                          |
|------------------|---------------------------------------------------------|
| Test credentials | `GET /ServiceProviderConfig`, `GET /Users?count=1`      |
| Assign user      | `GET /Users?filter=userName eq "..."` then `POST /Users`|
| Update attribute | `PUT /Users/{id}`                                       |
| Deactivate user  | `PATCH /Users/{id}` with `active: false`                |

## Run locally + ngrok (fastest for a demo)

```
pip install -r requirements.txt
set SCIM_TOKEN=<a-long-random-token>           # PowerShell: $env:SCIM_TOKEN="..."
uvicorn scim_server:app --host 0.0.0.0 --port 8000
```

In a second terminal:

```
ngrok http 8000
```

Use the ngrok https URL as the SCIM Base URL in Okta:
`https://<random>.ngrok-free.app/scim/v2`

## Deploy free on Render (persistent URL, better for documentation)

1. Push this folder to a GitHub repo.
2. Render -> New -> Web Service -> connect the repo.
3. Build command:  `pip install -r requirements.txt`
4. Start command:  `uvicorn scim_server:app --host 0.0.0.0 --port $PORT`
5. Add environment variable `SCIM_TOKEN` = your random token.
6. Base URL in Okta: `https://<your-service>.onrender.com/scim/v2`

(Render free tier sleeps when idle; the first Okta call after a pause may
take a few seconds to wake it. Fine for a demo.)

## Wire up in Okta

1. Applications -> Browse App Catalog -> search "SCIM" ->
   **SCIM 2.0 Test App (OAuth Bearer Token)** -> Add Integration.
2. General Settings -> name it (e.g. "AcmeCorp SCIM Target") -> Next -> Done.
3. Provisioning tab -> Configure API Integration -> Enable API integration.
   - SCIM 2.0 Base URL: your URL ending in `/scim/v2`
   - OAuth Bearer Token: the same value as `SCIM_TOKEN`
   - Test API Credentials -> should succeed.
4. Provisioning -> To App -> Edit -> enable Create Users, Update User
   Attributes, Deactivate Users -> Save.
5. Assignments -> assign a user or group. Watch the calls appear at the
   server's root URL, and in Okta under Reports / System Log.

## Documentation capture

- Screenshot the server root URL showing the live SCIM call feed.
- Screenshot the Okta "Test API Credentials" success.
- Screenshot the Okta System Log entries for the provisioning events.
- The matched pair (Okta sent it, the server received it) is the proof.
