Gemini Cookie Sync

Purpose:
- Read the currently signed-in Gemini browser session.
- Collect the session/auth metadata required by the bridge's authenticated Gemini Web path.
- Export `gemini-auth.json` locally only.

This extension is an operator convenience tool, not a remote authentication service. The generated file is a live Google/Gemini session credential.

Installation:
1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click **Load unpacked**.
4. Select this directory.
5. Open `https://gemini.google.com/app` in the same browser profile.
6. Sign in and refresh the page.
7. Open the extension and choose **Inspect session**.
8. Confirm the session is ready.
9. Choose **Export gemini-auth.json**.

Use with the bridge:

```bash
python -m gemini_web2api --cookie-file /path/to/gemini-auth.json
```

or configure `cookie_file` in `config.json`.

Security:
The generated file represents a real Google session. Treat it like a password/session token.

- Do not send it to anyone.
- Do not print its contents.
- Do not paste it into ChatGPT, GitHub issues, logs, or terminals that are being recorded.
- Do not commit it to Git.
- Use restrictive permissions such as `chmod 600`.
- Re-export/rotate the session if it is exposed.

The extension does not make the bridge immune to Gemini Web session expiry, account restrictions, throttling, or upstream protocol changes.