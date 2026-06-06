# OIDC Authorization Code Flow: AcmeCorp Internal Portal

This document covers the configuration and behaviour of the OIDC authorization code flow between Okta (Identity Provider) and a locally hosted Node.js Express application acting as the Relying Party.

---

## Overview

| Setting | Value |
|---|---|
| Protocol | OpenID Connect (OIDC) |
| Flow | Authorization Code |
| Identity Provider | Okta (`integrator-1186065.okta.com`) |
| Relying Party | AcmeCorp Internal Portal (Node.js / Express) |
| Sign-in Redirect URI | `http://localhost:3000/authorization-code/callback` |
| Sign-out Redirect URI | `http://localhost:3000` |
| Grant Type | Authorization Code |
| Scopes | `openid`, `profile`, `email` |

---

## Application Setup

The Relying Party is based on Okta's [okta-express-sample](https://github.com/okta-samples/okta-express-sample), a Node.js Express application that implements the OIDC authorization code flow using Okta's SDK.

Configuration is held in `.okta.env`:

```
ORG_URL="https://integrator-1186065.okta.com"
CLIENT_ID="[client id]"
CLIENT_SECRET="[client secret]"
```

The application runs on `http://localhost:3000` and starts with `npm start`.

---

## The Authorization Code Flow - Step by Step

### 1. Login Request
The user clicks **Login** on the Express app home page. The app redirects the browser to Okta's `/authorize` endpoint with the following parameters:

- `response_type=code`
- `client_id` - the app's Client ID
- `redirect_uri` - `http://localhost:3000/authorization-code/callback`
- `scope` - `openid profile email`
- `state` - a random value to prevent CSRF

### 2. Okta Authentication
The user authenticates at the Okta-hosted login page. Okta validates the credentials and checks the app assignment.

### 3. Authorization Code Returned
Okta redirects the browser back to the app's callback URL with a short-lived **authorization code**:

```
http://localhost:3000/authorization-code/callback?code=lTTdFO2zVT7eKMsG6fhMsEITBGSYaXT2REGJgqf6sog&state=15cAN...
```

<img width="2520" height="1139" alt="1 5 OKTAOIDC WEBSIDE" src="https://github.com/user-attachments/assets/12c8354b-62e9-4245-abbd-bdc943484aa1" />

This is a critical security boundary - the authorization code is short-lived (typically 60 seconds) and single-use.

### 4. Server-Side Token Exchange
The Express app makes a **back-channel** POST request directly to Okta's `/token` endpoint, exchanging the authorization code for:

- **ID Token** - a signed JWT containing the user's identity claims
- **Access Token** - used to call protected APIs (e.g. Okta's `/userinfo` endpoint)

This exchange happens entirely server-to-server. The tokens **never pass through the browser** - this is the key security advantage of the authorization code flow over the now-deprecated implicit flow.

### 5. Session Established
The Express app stores the tokens server-side and issues the browser a session cookie (`connect.sid`). All subsequent requests use this cookie to identify the session - the browser never holds a raw JWT.

### 6. Profile Page
The app calls Okta's `/userinfo` endpoint using the access token and renders the user's claims on the profile page.

<img width="2458" height="622" alt="1 5 OKTA OIDC Success redirect" src="https://github.com/user-attachments/assets/29db1575-c5cb-496d-b6d0-d47953c090a0" />

---

## ID Token Claims

The ID token returned by Okta is a JSON Web Token (JWT) with three base64-encoded sections: header, payload, and signature.

The payload contains the following claims for this user:

| Claim | Value | Meaning |
|---|---|---|
| `sub` | User's Okta ID | Subject - unique identifier for the user |
| `iss` | `https://integrator-1186065.okta.com` | Issuer - the IdP that issued the token |
| `aud` | Client ID | Audience - the app this token was issued for |
| `exp` | Unix timestamp | Expiry - token is invalid after this time |
| `iat` | Unix timestamp | Issued at time |
| `name` | Benjamin Hood | Display name from Okta profile |
| `email` | `benhoodlab@contractor.net` | Email from Okta profile |
| `preferred_username` | `benhoodlab@contractor.net` | Okta login username |

<!-- I could add jwt.io decoded ID token payload, acquire later. -->

---

## Why Authorization Code Flow

The authorization code flow was chosen over alternatives because:

- Tokens are never exposed to the browser or URL bar
- The client secret remains server-side only
- Short-lived authorization codes limit the window for interception
- Supports token refresh without re-authentication

This is the recommended flow for server-side web applications per the OAuth 2.0 Security Best Current Practice (RFC 9700).

---

## Evidence

### Okta System Log - Successful OIDC Authentication

<img width="1680" height="473" alt="Acme SSO Success log event" src="https://github.com/user-attachments/assets/737dd2f6-412c-4b75-9680-5ef672797b13" />

