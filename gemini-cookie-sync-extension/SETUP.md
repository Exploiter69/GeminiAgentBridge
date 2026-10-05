# Gemini Cookie Sync Setup

This extension exports the current Gemini browser session to a local `gemini-auth.json` file so the bridge can use an authenticated Gemini Web session without manually copying credentials into chat or source files.

## What it exports

Depending on the active Gemini page/session, the extension can collect:

- Gemini/Google session cookies;
- `SAPISID` and related session material;
- `SNlM0e` (`xsrf_token`) when present;
- `cfb2h` (`gemini_bl`) when available;
- `auth_user` when the page identifies an account index.

## Install

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the repository's `gemini-cookie-sync-extension` directory.
5. Open `https://gemini.google.com/app` in the same browser profile.
6. Sign in and refresh Gemini.
7. Open the extension.
8. Click **Inspect session**.
9. Confirm the session is reported as ready.
10. Click **Export gemini-auth.json**.

The extension writes the file locally. It is not a hosted credential service.

## Apply it to gemini-web2api

Copy the file to a private location and restrict permissions:

```bash
chmod 600 /path/to/gemini-auth.json
```

Then start the bridge with:

```bash
source .venv/bin/activate
python -m gemini_web2api \
  --cookie-file /path/to/gemini-auth.json
```

Or set:

```json
{
  "cookie_file": "/path/to/gemini-auth.json",
  "upstream_backend": "modern"
}
```

in the operator's private `config.json`.

## Verify without printing secrets

Check only the path and permissions:

```bash
stat -c '%A %U:%G %n' /path/to/gemini-auth.json
```

Do **not** use `cat`, `jq .`, or any command that prints the credential values when collecting diagnostics. Do not share or commit the exported session file.

A healthy-looking file is not proof that Gemini accepts the session. The upstream client must report an authenticated account and a real generation request must succeed.

## Refreshing an expired session

If the bridge logs an upstream state such as:

```text
Account status: UNAUTHENTICATED
Session is not authenticated or cookies have expired
```

return to Gemini in the browser, refresh/sign in, export a new file, and restart the bridge.

## Security

`gemini-auth.json` contains real authentication material.

- Never commit it.
- Never paste it into a bug report or chat.
- Never print it to a recorded terminal.
- Never put it into a Docker image layer.
- Never share it as an attachment.
- Rotate/re-export it if exposed.

The repository `.gitignore` excludes common session/config files, but verify `git status` before committing changes.