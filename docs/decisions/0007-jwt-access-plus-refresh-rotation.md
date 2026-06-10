# ADR-0007 — JWT access token + refresh-token rotation

> **Context:** Expands overview.md §6. Driven by: `AUTH-2`, `AUTH-3`, `AUTH-4`, `NFR-6`, `NFR-11`.

**Status:** Accepted. Adopted in v1.0.

---

## Context

Authentication must work without a shared server-side session store so that adding
instances later (`NFR-6`) needs no sticky sessions, while still allowing a user to
be logged out and limiting the damage if a long-lived credential is stolen. A
single long-lived token cannot satisfy both "stateless and fast to verify" and
"revocable".

## Decision

Issue **two tokens**:

- **Access token** — a signed JWT, short-lived (~15 min), stateless, carrying
  `user_id` and `role`. Any instance verifies it by signature alone, no lookup.
- **Refresh token** — an opaque random value, long-lived (~days), stored only as a
  `sha256` hash. It is **single-use**: each refresh issues a new one and links the
  old via `replaced_by` (the rotation chain). Presenting an already-replaced token
  signals theft and revokes the whole chain.

Login issues both; `refresh` rotates the pair; `logout` revokes the refresh token.

## Consequences

**Positive.**

- Stateless access tokens verify without a database hit — they scale horizontally
  (`NFR-6`).
- Refresh tokens are revocable (logout) and rotation enables **theft detection**
  (`NFR-11`).
- Only hashes of refresh tokens are stored, so a database leak does not expose
  usable tokens.

**Negative.**

- A refresh-token store and rotation/reuse logic must be maintained.
- An access token cannot be revoked within its short lifetime without an extra
  `jti` denylist; accepted given the ~15-minute window.

## Alternatives considered

- **Server-side sessions.** Require a shared session store and make the app
  stateful — against the statelessness this architecture depends on.
- **One long-lived JWT, no refresh.** Cannot be revoked; a theft grants access for
  the token's full lifetime.
- **Access token only, no refresh.** Forces a trade-off between security (very short
  life, constant re-login) and convenience (long life, weak revocation).
