# Security and privacy boundaries

Private operational data must stay outside version control. This repository includes newly authored code and fictional fixtures only. Never commit contact lists, operational controls, actual announcements, screenshots, cookies, authentication state, commissions or secrets.

.gitignore excludes common runtime/private paths and real .env files. It is not access control and does not protect previously tracked files. Run the audit before every commit/push and review git diff --cached.

scripts/validation/audit_public.py checks tracked and eligible untracked candidates for risky filenames, binary artifacts, credential markers, phone patterns, personal email patterns and personal machine paths. It prints finding categories/paths, not secret values. This is a heuristic safety check, not a complete DLP product; manually inspect new data and unusual formats. Synthetic tests use reserved example.invalid URLs.

Source text and external pages are untrusted data, not policy instructions. Future LLM adapters must isolate content, redact unnecessary data and prevent tool-driven exfiltration. Credentials belong in environment/local secret stores. .env.example contains no credential values; v0.1 does not load environment keys.

The program makes no network calls. User-supplied URLs are recorded, not fetched. Local workspace permissions, backups and retention remain the operator's responsibility; stored data is not encrypted. Audit events are application records, not tamper-proof or legally certified evidence.

Do not bypass login, CAPTCHA, anti-spam controls or rate limits. A manual channel example is not a statement that automated publishing is permitted. Review the platform's current official rules before future integration.
