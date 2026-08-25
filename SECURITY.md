# Security Design

## Threat model summary

- Reject malicious CSV formulas and control characters in ingested text
- Never trust narration as instruction; LLM only sees sanitized, schema-bounded payloads
- Store all uploaded files under a UUID-based path with path assertions
- Enforce request limits and file-size caps before parsing
- Use Decimal for money arithmetic to avoid float precision errors
- Keep secrets in environment variables, not source code
- Use append-only audit logging with a hash chain to detect tampering
- Return opaque errors for production failures; logs retain details

## Immediate safeguards in the scaffold

- `.env` is gitignored
- `requirements.txt` pins dependencies
- `core` is the home of deterministic, non-float logic
- `backend/main.py` exposes the `/healthz` endpoint for liveness checks
