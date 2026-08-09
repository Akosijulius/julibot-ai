# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | ✅ Active           |
| < 0.2   | ❌ Not supported    |

## Reporting a Vulnerability

We take security seriously. Please **do not** open a public issue for security
vulnerabilities — report privately instead.

1. Email: open a private vulnerability report on GitHub
   (Repository → **Security** → **Report a vulnerability**).
2. Include as much detail as possible:
   - Affected endpoint / file / feature
   - Steps to reproduce (minimal example preferred)
   - Expected vs. actual behavior
   - Environment (Python version, OS, deployment target)

We aim to acknowledge reports within **48 hours** and will keep you updated on
the fix and release timeline. Please give us a reasonable window (default **90
days**) before disclosing publicly.

## Security Design

This project follows these practices by default:

- **Secrets never committed** — `SECRET_KEY`, API keys, and `DATABASE_URL`
  live only in environment variables; `.env` is gitignored. `.env.example`
  contains placeholders only.
- **Production config validation** — `ENVIRONMENT=production` fails startup if
  `SECRET_KEY` is the default value.
- **Password hashing** — bcrypt via passlib; passwords are never stored or
  logged in plaintext.
- **JWT auth** — short-lived access tokens (30 min), scoped data access (users
  can only read/write their own conversations).
- **Rate limiting** — per-endpoint limits on chat and auth routes to mitigate
  abuse and API-quota exhaustion.
- **Secret redaction** — structured logging scrubs sensitive values.
- **Input validation** — all request bodies validated by Pydantic schemas.

## Deployment

When deploying (especially serverless / Vercel):

1. Use **PostgreSQL**, not SQLite — SQLite is a local file and does not persist
   on serverless platforms.
2. Set a strong `SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Set `ALLOWED_ORIGINS` to your exact deployment origin.
4. Keep `DEBUG=false` and `ENVIRONMENT=production`.
5. Do **not** reuse development API keys in production.

## Data

- Stored data: user accounts (hashed passwords), conversations, messages.
- The local SQLite database (`julibot.db`) is gitignored and never shipped.
- Users can delete their own conversations via the API; there is currently no
  account-deletion endpoint (data is removed by deleting the database / user
  row directly).
- Guest-mode chats are not persisted.
