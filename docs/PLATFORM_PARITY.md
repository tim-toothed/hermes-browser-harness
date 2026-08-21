# Linux 1.4.5 ↔ Windows Browser Harness parity inventory

Дата фиксации: 2026-08-21. Источники: принятый Linux pilot, historical Windows acceptance и фактический source обоих пакетов.

## Общий контракт

| Контракт | Linux 1.4.5 | Windows current | Действие |
|---|---|---|---|
| Model-facing browser surface | Только plugin-owned `browser_exec` в toolset `browser_harness`; built-in `browser` отключён | Desktop deployment требует upgrade/read-back; public source `1.4.5` теперь содержит dedicated toolset fix | Развернуть `1.4.5` на Windows и повторить B4/B6 |
| Browser runtime | Bundled Browser Harness `0.1.9` | Bundled Browser Harness `0.1.9` | Parity |
| CDP owner | Один Chrome на loopback `127.0.0.1:9222` | Один managed Chrome на loopback `127.0.0.1:9222` | Parity |
| Managed profiles | Persistent registry; одновременно active только один profile; switch заменяет Chrome process | Registry/skill есть; одновременно active только один profile | Parity contract, platform lifecycle разный |
| Same-profile concurrency | PASS: реальные cron-задачи одновременно работали в отдельных session/tab namespaces | NOT RUN | Выполнить B2 на Windows; не предполагать очередь или конфликт заранее |
| Different-profile concurrency | Не поддерживается: один endpoint и один active profile | Не поддерживается: один endpoint и один active profile | Оставить A8 warning; не ставить задачи разных profiles с пересечением |
| Popup/tab ownership | Runtime namespaces и dedicated tabs | Runtime namespaces и dedicated tabs | B3 должен проверяться на каждой платформе |
| Discovery/page routing | `web_search` для discovery; официальный URL/DOM — `browser_exec`; granular browser tools отсутствуют | Checklist требует то же, но public plugin toolset boundary отстаёт | Перенести Linux toolset fix в Windows/public plugin |
| Computer Use | Не устанавливается; disabled для CLI/Telegram на target | Disabled на принятых Windows-нодах | Parity policy |

## Общие исправления, выявленные Linux pilot

1. **Dedicated toolset.** `browser_exec` вынесен из built-in `browser` в `browser_harness`; built-in granular browser tools отключаются. Это общий fix, а не Linux-specific behavior.
2. **Live extension reconciliation.** Config/payload недостаточны: required contract — `config → browser-level getExtensions → loadUnpacked if missing → exact read-back → browser DSL`.
3. **Extension acceptance.** Проверяются exact ID, version, path и `enabled=true`; функциональность uBlock подтверждается A/B effect, а не только listing.
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
- Удаление Chrome Web Store `_metadata` из unpacked uBlock payload; иначе Chrome не активирует extension корректно.
- Pinned uBlock Origin Lite `2026.812.1211`; browser-level activation и A/B blocking PASS.
- Node-local Chrome args, egress, credentials, TLS keys, profile data и share state сохраняются при update и не входят в package.

## Windows-specific behavior/debt

- Windows cold-start запускает Chrome непосредственно как detached process, без systemd/X11/Remote Access stack.
- Windows Preferences/download path используют Windows filesystem semantics.
- Historical public standalone plugin `1.3.1` регистрировал `browser_exec` в toolset `browser`. Public source `1.4.5` исправлен; Windows deployment и real-agent read-back ещё не выполнены.
- B2 same-profile concurrent cron behavior на Windows не проверен.
- Historical Windows NopeCHA state не переносится в Linux package. Linux package управляет только uBlock; CAPTCHA extension/configuration отложены.
- Старые Windows installer artifacts не являются источником для новых установок; новый Windows lifecycle должен адаптировать принятый Linux process по этапам.

## Acceptance B1–B6 после ревизии

| Test | Назначение | Linux | Windows |
|---|---|---|---|
| B1 | Последовательное переключение разных profiles | PASS | Historical PASS |
| B2 | Одновременные задачи одного profile, отдельные session/tab namespaces | PASS | NOT RUN |
| B3 | Popup принадлежит создающей операции и не ломает другие sessions | Требует отдельного сохранённого evidence при следующем regression | Требует rerun при Windows release |
| B4 | Известный URL идёт через внешний plugin-owned `browser_exec` | PASS | Historical PASS; повторить после dedicated-toolset port |
| B5 | Обычный поиск не вызывает browser plugin | SKIP до принятого `web_search + web_extract` contract | SKIP по той же причине |
| B6 | Discovery и page interaction разделены | PASS | Повторить после dedicated-toolset port |

## Явно не включено в release

- Credentials, tokens, OTP, private keys, exact node hosts/ports и proxy routes.
- Central AUTH deployment, Docker Compose и публичный SOCKS listener.
- Node-local egress configuration.
- Неработающий bundled/unpacked NopeCHA artifact.
- CAPTCHA0–2 как PASS: они остаются deferred SKIP.
- Удалённый download acceptance scenario и E013.
