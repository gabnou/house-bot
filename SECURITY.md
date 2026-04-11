# Security

## Sensitive Files — Never Share or Commit

The following files contain private credentials and must be kept strictly local:

| File / Directory | Contents |
|---|---|
| `.env` | API keys, Ollama config, WhatsApp partner JIDs |
| `creds/client_google_api_calendar.json` | Google OAuth client credentials |
| `creds/token.json` | Google OAuth access/refresh token |
| `bridge/baileys_auth/` | WhatsApp session state |

These paths are already listed in `.gitignore` and will not be tracked by git.
**Do not override or remove these ignore rules.**

## What to Do If a Secret Is Exposed

If any of the above files are accidentally committed or shared:

1. **Revoke the compromised credentials immediately:**
   - OpenWeatherMap key → regenerate at [openweathermap.org](https://openweathermap.org/api)
   - Google OAuth credentials → delete and recreate in [Google Cloud Console](https://console.cloud.google.com)
   - WhatsApp session → delete `bridge/baileys_auth/` and re-scan the QR code
2. **Remove the secret from git history** using `git filter-repo` or contact GitHub support to purge cached views.
3. **Rotate all other secrets** in the same `.env` as a precaution.

## Reporting Vulnerabilities

This is a personal home automation project. If you discover a security issue, please open a private GitHub issue or contact the maintainer directly.
