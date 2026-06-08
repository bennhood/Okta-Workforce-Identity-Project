# Authenticator Comparison

This document covers the authenticator types configured in the AcmeCorp lab environment and their relative security properties, mapped to real-world enterprise deployment considerations.

---

## Authenticators Enrolled

Three authenticator types were configured and enrolled on the lab admin account:

| Authenticator | Type | Phishing Resistant | Device Bound | Enrolled Via |
|---|---|---|---|---|
| Okta Verify (TOTP) | Possession | No | Yes | Okta Verify mobile app |
| Google Authenticator | Knowledge/Possession | No | No | Google Authenticator mobile app |
| Passkey / Windows Hello | Possession | Yes | Yes | WebAuthn platform authenticator |

<img width="1372" height="963" alt="Authenticators" src="https://github.com/user-attachments/assets/2ece0b0d-bde2-476e-a138-8be9ecc23537" />

<img width="810" height="933" alt="Security Methods" src="https://github.com/user-attachments/assets/13d60a7d-e96d-423b-afa9-82a428344105" />

---

## Authenticator Detail

### Okta Verify (TOTP)
Okta's native authenticator app supporting both push notifications and TOTP codes. Enrolled as part of the initial Okta org setup.

- **Push notification:** User receives a prompt on their enrolled device and approves with a tap
- **TOTP mode:** Generates a time-based 6-digit code refreshing every 30 seconds
- **Device binding:** The credential is tied to the enrolled device
- **Phishing resistance:** None - a TOTP code can be intercepted and replayed in a real-time phishing attack

### Google Authenticator
A TOTP-based authenticator providing a time-based 6-digit code. Enrolled via QR code scan.

- **No push capability** - code entry only
- **Not device bound** - the seed can theoretically be extracted or re-enrolled on another device
- **Phishing resistance:** None - same real-time phishing vulnerability as Okta Verify TOTP
- **Use case:** Legacy environments or users without access to Okta Verify

### Passkey / Windows Hello (FIDO2 / WebAuthn)
A platform authenticator using the WebAuthn standard. Enrolled via the browser's WebAuthn API, authenticated using Windows Hello (PIN, fingerprint, or face recognition).

- **Hardware protected:** The private key never leaves the device's TPM chip
- **Device bound:** Cannot be used from any other device
- **Phishing resistant:** The credential is scoped to the exact origin (domain) - a phishing site with a different domain cannot trigger the authenticator
- **Replaces password:** In passwordless configurations, the passkey is the sole authenticator

---

## Security Assurance Comparison

| Factor | Interceptable | Replayable | Phishing Resistant | MFA Fatigue Risk |
|---|---|---|---|---|
| Password | Yes | Yes | No | N/A |
| TOTP (Google Auth / Okta Verify) | Yes (real-time) | Yes (60s window) | No | No |
| Okta Verify Push | No | No | No | Yes |
| Passkey / FIDO2 | No | No | Yes | No |

---

## Enrollment Policy

Authenticators were set to **Optional** in the Okta Authenticator Enrollment Policy, allowing users to enrol but not forcing mandatory enrolment at login. In a production environment:

- **Okta Verify** would be set to **Required** for all users
- **Passkey** would be set to **Required** for privileged users and those accessing sensitive applications
- **Google Authenticator** would be set to **Optional** as a legacy fallback only

<img width="1358" height="1164" alt="EnrollPolicy" src="https://github.com/user-attachments/assets/dc5f291b-e61b-439d-9ec4-97d0fbfdbb5c" />

---

## Production Considerations

In a real enterprise deployment, authenticator strategy would align with the organisation's phishing risk profile:

- Financial services or high-value targets: mandate FIDO2 for all users accessing sensitive systems
- General workforce: Okta Verify push as default, with FIDO2 for privileged accounts
- Phase out TOTP for new enrolments - it is not phishing-resistant and provides a false sense of security compared to FIDO2
