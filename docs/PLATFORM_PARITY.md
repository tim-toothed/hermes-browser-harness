# Linux 1.4.10 ↔ Windows 1.4.11 Browser Harness parity inventory

Дата фиксации: 2026-08-24. Источники: принятый Linux pilot, Windows D2 pilot и фактический source обоих пакетов.

## Общий контракт

| Контракт | Linux 1.4.10 | Windows 1.4.11 | Действие |
|---|---|---|---|
| Model-facing browser surface | Plugin-owned `browser_exec` в canonical toolset `browser`; granular built-ins подавлены plugin overrides | Только plugin-owned `browser_exec` в `browser`; `computer_use` отключён для CLI/Telegram | Parity |
| Browser runtime | Bundled Browser Harness `0.1.9` | Bundled Browser Harness `0.1.9` | Parity |
| CDP owner | Один Chrome на loopback `127.0.0.1:9222` | Один managed Chrome на loopback `127.0.0.1:9222` | Parity |
| Managed profiles | Persistent registry; одновременно active только один profile; switch заменяет Chrome process | Registry/skill есть; одновременно active только один profile | Parity contract, platform lifecycle разный |
| Same-profile concurrency | PASS: реальные cron-задачи одновременно работали в отдельных session/tab namespaces | PASS: два одновременных real Hermes chat в Session 1; короткая owned-вкладка очистилась, пока длинная оставалась активной | Parity |
| Different-profile concurrency | Не поддерживается: один endpoint и один active profile | Не поддерживается: один endpoint и один active profile | Оставить A8 warning; не ставить задачи разных profiles с пересечением |
| Popup/tab ownership | Invocation-local in-memory target set; current/created/switched targets plus recursive `openerId` descendants | Same runtime contract | B3 checks owned cleanup without touching concurrent/manual targets |
| Discovery/page routing | `web_search` для discovery; официальный URL/DOM — `browser_exec`; granular browser tools отсутствуют | Toolset boundary совпадает; отдельный B6 discovery scenario в Windows pilot не запускался | Не объявлять Windows B6 PASS без отдельного trace |
| Computer Use | Не устанавливается; disabled для CLI/Telegram на target | Disabled на принятых Windows-нодах | Parity policy |

## Общие исправления, выявленные Linux pilot

1. **Canonical toolset.** Plugin переопределяет `browser_exec` внутри штатного `browser`, а granular built-ins делает недоступными name-scoped overrides. Это устраняет unknown-toolset drift без возврата competing browser routes.
2. **Live extension reconciliation.** Config/payload недостаточны: required contract — `config → browser-level getExtensions → loadUnpacked if missing → exact read-back → browser DSL`.
3. **Extension acceptance.** Для пользовательских расширений проверяются exact ID, version, path и `enabled=true`; default extension не поставляется.
4. **Chrome recovery.** Active lifecycle container/target сам по себе не доказывает живой Chrome. Перед Browser Harness или Remote Access требуется CDP readiness.
5. **Same-profile concurrency semantics.** Отдельные Browser Harness session/tab namespaces могут одновременно использовать один Chrome. B2 проверяет результат и изоляцию вкладок, а не наличие очереди.
6. **Different-profile constraint.** Profile switch — глобальная lifecycle-операция для единственного Chrome; задачи разных profiles не должны пересекаться.
7. **Tool provenance acceptance.** Корректный текст ответа не доказывает routing; B4–B6 сохраняют fresh tool trace и process/profile baseline.
8. **No hidden fallback.** Browser Use, global Harness CLI, terminal page automation, ordinary Chrome и CUA не являются допустимым fallback.

## Linux-specific additions

- Debian/Ubuntu amd64 installer/uninstaller и ownership manifest.
- Service account и persistent profile/state под `/var/lib/procvetaev-browser`.
- Xvfb → Openbox → Chrome systemd lifecycle; loopback CDP.
- Shared activity lock и idle shutdown без остановки во время `browser_exec`/Remote Access.
- X11VNC, noVNC/websockify, Caddy и local broker для временного доступа к тому же display/profile.
- Remote Access сначала восстанавливает Chrome/CDP и только затем выдаёт ссылку; пустой X display не считается recovery.
- Managed profile selector и Chrome launcher, совместимые с systemd и одним endpoint.
- Linux ownership/permissions normalization для unpacked extensions.
- Node-local Chrome args, egress, credentials, TLS keys, profile data и share state сохраняются при update и не входят в package.

## Windows-specific behavior/debt

- Windows cold-start запускает Chrome через интерактивную Limited/IgnoreNew logon task или plugin-owned detached process в пользовательской Session 1, без systemd/X11/Remote Access stack.
- Windows Preferences/download path используют Windows filesystem semantics.
- D2 обновлён с pinned plugin `1.3.0` и отдельного `browser-harness 0.1.9` uv tool на внешний runtime `1.4.10`; профиль и registry сохранены. Windows installer выпускается как plugin `1.4.11`.
- Windows installer восстанавливает inherited ACL для plugin, extension и skill trees после SSH/elevated install; без этого Limited Chrome/Gateway не читает manifest/plugin.
- B2 same-profile concurrent real-agent behavior и B3 exception cleanup на D2 подтверждены browser target read-back.
- Старые Windows installer artifacts не являются источником для новых установок; source of truth — `install-windows.py` и `windows/skill/` в plugin.

## Acceptance B1–B6 после ревизии

| Test | Назначение | Linux | Windows |
|---|---|---|---|
| B1 | Последовательное переключение разных profiles | PASS | Historical PASS |
| B2 | Одновременные задачи одного profile, отдельные session/tab namespaces | PASS | PASS на D2: два real Hermes chat, mid-run и final CDP target read-back |
| B3 | Popup принадлежит создающей операции и не ломает другие sessions | Требует отдельного сохранённого evidence при следующем regression | PASS на D2: intentional exception закрыл owned target и сохранил внешний target |
| B4 | Известный URL идёт через внешний plugin-owned `browser_exec` | PASS | PASS на D2: `example.com`, real Hermes tool trace, exact acceptance marker |
| B5 | Обычный поиск не вызывает browser plugin | SKIP до принятого `web_search + web_extract` contract | SKIP по той же причине |
| B6 | Discovery и page interaction разделены | PASS | NOT RUN в D2 pilot |

## Явно не включено в release

- Credentials, tokens, OTP, private keys, exact node hosts/ports и proxy routes.
- Central AUTH deployment, Docker Compose и публичный SOCKS listener.
- Node-local egress configuration.
- Неработающий bundled/unpacked NopeCHA artifact.
- CAPTCHA0–2 как PASS: они остаются deferred SKIP.
- Удалённый download acceptance scenario и E013.
