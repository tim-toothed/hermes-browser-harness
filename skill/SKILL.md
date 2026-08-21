---
name: browser-harness
description: Use browser_exec for all interactive browser work on this Linux VPS.
---

# Linux Browser Harness

Use the `browser_exec` tool for navigation, interaction, screenshots and CDP. Do not use Computer Use/cua-driver and do not launch another browser backend.

## Browser work

- First navigation: `new_tab(url)`.
- Use accessibility/CDP inspection first; use screenshots when visual state matters.
- Stop at login, password, MFA or consent unless the user explicitly handles it.

## Managed profiles

The registry is `browser-profiles.json` beside this `SKILL.md`. It contains only `default` and agent-owned `profiles`; each profile has `label`, `description` and an absolute POSIX `user_data_dir` under `/var/lib/procvetaev-browser`.

Before every browser operation:

1. Read and parse the sibling registry. Never infer profile IDs, labels or descriptions from the hostname, Hermes config, Chrome's `Default` directory or conversational memory.
2. If the user did not name a profile, select the registry `default` without asking. If the user named one, match `id`, `label` and `description`; require one unambiguous match. Zero or several matches require clarification and no browser mutation.
3. Determine the active profile with `/usr/local/libexec/procvetaev-browser-harness/browser-profile status`. Active state comes from the actual Chrome command line owning loopback CDP `9222`, not from the registry default.
4. If the selected profile is not active, run `/usr/local/libexec/procvetaev-browser-harness/browser-profile select <id>`. The helper exclusively owns systemd stop/start, port release, selected path and daemon reload. Never launch Chrome directly, edit `/run` state or call `systemctl` for profile switching.
5. Complete browser work through `browser_exec`. Never fall back to Browser Use, Computer Use/CUA, ordinary Chrome or an anonymous profile.

For an inventory request, read the sibling JSON and the helper status, show only registry profiles with ID/label/description plus default and active, and do not create or select anything.

Create a profile only after an explicit natural-language request. Generate an ASCII ID matching `[a-z0-9][a-z0-9-]{0,47}` and run:

```text
/usr/local/libexec/procvetaev-browser-harness/browser-profile create <id> --label <label> --description <description>
```

When the user assigns a clearer purpose to an existing profile, update only its metadata through `browser-profile update`; preserve its ID and `user_data_dir`. Change the default only after an explicit request through `browser-profile set-default <id>`. Never copy an employee Chrome profile or store credentials, ports or active state in the registry.

After profile creation, warn once that only one managed profile may be active and tasks requiring different profiles must not overlap. Different managed profiles cannot run simultaneously; same-profile tasks may run concurrently in separate `browser_exec` session/tab namespaces.

## Scheduling warning

When the user creates a scheduled task that names a managed profile, include one warning in the final response after creating it: only one managed profile can be active at a time, so scheduled tasks using different profiles must not overlap. Same-profile browser tasks may overlap in separate `browser_exec` session/tab namespaces. If the scheduled task does not name a managed profile, do not add browser-specific warnings or speculate about its implementation.

## CAPTCHA

Configured extensions are loaded and verified by plugin code, not by the model.

When a CAPTCHA is visible, preserve the same page and target, wait 80 seconds without interacting, then inspect a screenshot. If still visibly unsolved, wait one additional 80-second interval and inspect once more. Do not use `/json/list` as a completion signal and do not switch browser, profile, target or backend.

## Temporary Remote Access

Create access only when the user explicitly requests to see/control the browser or human authorization is required:

```bash
curl -fsS -X POST http://127.0.0.1:8790/v1/shares \
  -H 'Content-Type: application/json' \
  --data '{"kind":"remote_access","target_url":"https://target.example/","ttl_seconds":1800}'
```

Return only the resulting public URL and OTP. Never place the OTP in the URL or logs. Remote Access exposes the same managed Chrome/display used by `browser_exec`; it must not start another Chrome profile.

Revoke when requested:

```bash
curl -fsS -X POST http://127.0.0.1:8790/v1/shares/<share_id>/revoke
```

Each share owns one Chrome target opened at `target_url`. Revocation, expiry, or a replacement share closes only that owned target. Other Browser Harness and manually opened tabs remain untouched; browser automation and the managed Chrome lifecycle stay active.
