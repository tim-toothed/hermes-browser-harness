![Hermes Browser Harness](assets/banner.png)

# Hermes Browser Harness

Give Hermes Agent a persistent Google Chrome browser you can access remotely, even on a headless Linux server.

## Highlights

- **Hermes integration.** A single `browser_exec` tool with a bundled, version-locked Browser Harness runtime.
- **Google Chrome over CDP.** Persistent logins, browser settings, and your configured extensions.
- **Managed profiles.** Separate browser environments for different accounts.
- **Tab cleanup.** Close task-owned tabs and popups automatically while preserving unrelated tabs.
- **Remote access on Linux.** Open the agent’s browser through a temporary, OTP-protected HTTPS link.
- **On-demand lifecycle on Linux.** Start Chrome when needed and shut it down after inactivity.

## Installation

Requires Hermes Agent.

```bash
hermes plugins install tim-toothed/hermes-browser-harness
hermes plugins enable browser-harness --allow-tool-override
```

Then install the Chrome host package for your platform.

### Windows

Uses installed Google Chrome and a persistent agent-owned profile.

```powershell
cd "$env:LOCALAPPDATA\hermes\plugins\browser-harness"
& "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\python.exe" .\install-windows.py
```

### Linux

Supports Debian/Ubuntu amd64 with systemd.

```bash
cd ~/.hermes/plugins/browser-harness
sudo ./install-linux.sh
```

The host installers configure the browser toolset for CLI and Telegram. Restart the active Hermes process through your installation’s normal launcher after setup.

### First run

Ask Hermes:

```text
Use Browser Harness to open https://example.com
and report the page title and visible text.
```

## Remote access

On Linux, connect to the same Chrome session the agent is using. Open a temporary HTTPS link, authenticate with an OTP, and complete a login or another manual step. The agent can then continue in that session.

### Setup

The included installer configures **Caddy for HTTPS** and **Certbot for certificate issuance and automatic renewal**. It supports a public server IP or a domain. A domain is optional.

Requirements:
- Hermes installed at `/root/.hermes`, with its runtime and `uv` available.
- Inbound TCP **80** for certificate validation and renewal.
- Inbound TCP **443** for HTTPS.
- A public IP or domain pointing to this server.

Open the ports in both the host and hosting-provider firewalls. The installer does not configure external firewalls or DNS.

**If Caddy already serves other sites on this server, review its configuration first.** The installer stops the default `caddy.service` and runs Caddy through its own `remote-access-gateway.service`.

```bash
cd /root/.hermes/plugins/browser-harness

sudo ./install-remote-access-linux.sh install \
  --target-hostname "$(hostname)" \
  --public-host YOUR_PUBLIC_IP_OR_DOMAIN \
  --acme-email YOUR_EMAIL \
  --confirm-http01 \
  --confirm-install
```

Replace the public host and email placeholders. To register without a contact email, replace `--acme-email YOUR_EMAIL` with `--acme-without-email`.

### Verify

```bash
sudo ./install-remote-access-linux.sh check \
  --target-hostname "$(hostname)" \
  --public-host YOUR_PUBLIC_IP_OR_DOMAIN
```

Then ask Hermes:

```text
Open https://example.com and give me browser access for 10 minutes.
```

Open the returned link from another device, enter the OTP, and confirm that Chrome is visible and interactive.

## Platform support

| Capability | Windows | Linux |
|---|---|---|
| Chrome through CDP | Yes | Yes |
| Persistent profiles and profile switching | Yes | Yes |
| Configured Chrome extensions | Yes | Yes |
| Task-owned tab cleanup | Yes | Yes |
| Temporary remote access | — | Yes |
| On-demand startup and idle shutdown | — | Yes |

## Limitations

- Only one managed profile can be active per node. Tasks requiring different profiles must not overlap.
- Tasks using the same profile can run in separate session/tab namespaces.
- The default Linux idle timeout is 60 minutes.
- Extensions are user-configured; none are bundled.

## Credits and license

Uses Browser Use’s Browser Harness runtime, distributed under its upstream MIT license.

Hermes integration and host orchestration are MIT licensed. See `THIRD_PARTY_NOTICES.md`.
