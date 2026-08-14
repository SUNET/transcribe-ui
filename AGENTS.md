# Agent Guidelines — transcribe-ui

## Project overview

NiceGUI-based web frontend for Sunet Scribe (transcription service). Requires Python ≥ 3.13. Package manager: `uv` (see `uv.lock`).

## Architecture

- **Framework**: NiceGUI (Python-based web UI built on Quasar/Vue)
- **Entry point**: `main.py` — registers `@ui.page("/")` and `/logout`, handles OIDC auth callback and encryption-password bootstrap
- **Pages**: `pages/` — `home.py`, `admin.py`, `srt.py`, `user.py`, `status.py`. Each exports a `create()` function called from `main.py`
- **Utilities**: `utils/` — split by concern:
  - `helpers.py` — `storage_encrypt`/`storage_decrypt` (AES-256-GCM), filename sanitisation, encryption-password set/verify/reset, customer/realm CRUD
  - `token.py` — `get_auth_header`, `token_refresh`, `get_user_info`, `get_admin_status`, `get_bofh_status`
  - `common.py` — `page_init()` and shared UI scaffolding
  - `settings.py` — pydantic `BaseSettings` loaded from `.env` via `get_settings()` (lru-cached)
  - `caption.py` (`SRTCaption`), `srt.py` (`SRTEditor`), `video.py`, `undo_redo.py`, `customer.py`, `group.py`, `crypto.py`, `styles.py`
- **DB / analytics**: `db/analytics.py` — async `httpx` calls to backend API
- **Static assets**: `static/` — logos, favicon
- **Tests**: `tests/` — pytest with `nicegui.testing.user_plugin`; run with `.venv/bin/python -m pytest` (not system python)
- **Container**: `Dockerfile` at repo root

## Key conventions

- All authenticated page handlers must call `page_init()` before accessing secret storage keys. `page_init` redirects to `/` when `_scribe_bk` missing in browser storage and refreshes the OIDC token.
- All API calls MUST be async — use `httpx.AsyncClient` (see `db/analytics.py`). Do not introduce blocking `requests` or sync `httpx` calls in new code; legacy sync calls in `utils/helpers.py` should be migrated when touched.
- API calls use `get_auth_header()` from `utils/token.py` for bearer-token auth.
- NiceGUI `ui.table` uses Quasar slot templates with `$parent.$emit('event_name', props.row)` for per-row actions.
- Dialog close on validation failure uses short-circuit pattern: `result and (dialog.close(), navigate)`.
- Use `match/case` statements (Python 3.13+).

## Security

This app holds session tokens, user PII, and an encryption password that gates backend-side data encryption. Treat security as a first-class concern in every change.

### Authentication & session

- Authentication is OIDC. The flow lives in `main.py` (`@ui.page("/")` and `/logout`).
- Every authenticated page handler MUST call `utils.common.page_init()` first. It:
  - redirects to `/` if `app.storage.browser["_scribe_bk"]` (browser key) is missing,
  - schedules `token_refresh()` on each page load and logs out on refresh failure by clearing `token`, `refresh_token`, and `encryption_password` from `app.storage.user`, then navigating to `OIDC_APP_LOGOUT_ROUTE`.
- Never read `app.storage.user["token"]` / `["encryption_password"]` without going through `page_init()` first.
- Authorization checks: `get_admin_status()`, `get_bofh_status()`, `get_user_status()` in `utils/token.py`. Admin pages must gate on these — do not infer privilege from UI state.

### Secret handling

- Browser-bound encryption: `storage_encrypt` / `storage_decrypt` in `utils/helpers.py` wrap `utils/crypto.py` (`AESGCM` + `HKDF` from `cryptography.hazmat`, base64-encoded ciphertext, random 12-byte nonce, AAD `b"scribe-secret"`).
- Key material = `app.storage.browser["_scribe_bk"]` ++ `settings.STORAGE_SECRET`. Salt = `get_browser_id()`. Never log, print, or echo any of these into UI text, error messages, or exceptions.
- Decryption failure intentionally clears `encryption_password` and redirects to `/` — preserve this fail-closed behavior; do not catch and continue.
- Any new value stored in `app.storage.user` that contains tokens, passwords, keys, or PII MUST go through `storage_encrypt`.
- `STORAGE_SECRET` default in `utils/settings.py` is a placeholder. Production deployments must override via `.env`. Never commit a real secret.

### Input handling

- Filenames coming from users or the API: pass through `sanitize_filename()` (strips `/ \ \x00 < > : " | ? *` and control chars, trims `. ` ).
- Any text rendered into NiceGUI: prefer `ui.label`/`ui.markdown` — avoid `ui.html` with untrusted input. If raw HTML is unavoidable, sanitise with a library like Bleach (`bleach.clean`) rather than ad-hoc regex.
- Validate at boundaries: API responses and form input. Internal helpers can trust their callers.
- Logs must use `user_id`, never usernames, email addresses, or other PII.

### Crypto rules

- Use the existing `utils/crypto.py` helpers. Do not roll new AES/HKDF code; do not switch to ECB, CBC-without-MAC, or PyCryptodome.
- Prefer the secure-by-default `cryptography` package (already a dep). For new crypto needs, evaluate Google Tink before bespoke code.
- Never hard-code keys, IVs, or salts. Nonces must be `os.urandom(12)` per encrypt call (already done by `encrypt_string`).

### Transport & external calls

- All outbound HTTP MUST use `httpx.AsyncClient` (see `db/analytics.py`). Set explicit timeouts. Do not disable TLS verification.
- Backend base URL comes from `settings.API_URL`. Do not concatenate user input into URLs; pass via `params=` so `httpx` quotes them.
- SSRF: if a feature ever fetches a user-supplied URL, block private/loopback ranges before connecting (e.g., an SSRF filter library) — there is no such code path today; flag any addition for review.

### Container & deps

- `Dockerfile` should not run as root in production; pin base image and pip-installed versions.
- Dependencies are tracked in `pyproject.toml` / `uv.lock`. Run `uv lock --upgrade` deliberately, review the diff, and prefer libraries from the "secure-by-default" list (Bleach, defusedxml, Tink) over hand-rolled equivalents.

## Word timings (`utils/srt.py`)

`SRTEditor.load_words()` takes the optional payload from `GET /api/v1/transcriber/{uuid}/words`:

```json
{"version": 1, "words": [{"t": "Hej", "s": 0.12, "e": 0.34, "c": 0.98}]}
```

- Anything with a different `version`, or an unparseable payload, is discarded — the editor must open normally without word data. Jobs transcribed before word timings existed have none.
- Words are flat and time-ordered, not tied to segments. `caption_words()` maps them onto a caption by time range (bisect on precomputed midpoints), so they survive splits, merges and renumbering. Never key word data by caption index.
- `split_caption(caption, cursor_position=..., text=...)` cuts at the caret and picks the timestamp from the silence between the two adjacent words. Without word data a caret split falls back to proportional; **a split with no caret must keep halving the caption**, which is what results predating this feature rely on.
- `c` is absent when the worker ran with `WORD_CONFIDENCE=false`. Gate any confidence UI on `editor.has_confidence`, not on the presence of `words`.
- Confidence markup goes through `get_confidence_html()`, which HTML-escapes every token. Do not build caption markup inline.

## Settings

`utils/settings.py` `Settings` (pydantic `BaseSettings`, loaded from `.env`):

- `API_URL`, `OIDC_APP_LOGIN_ROUTE`, `OIDC_APP_LOGOUT_ROUTE`, `OIDC_APP_REFRESH_ROUTE`
- `STORAGE_SECRET` — keys AES-256-GCM encryption for browser storage
- Branding: `LOGO_*`, `FAVICON`, `TAB_TITLE`, `TOPBAR_TEXT`, `LANDING_TEXT`, `MANUAL_URL`
- `WHISPER_MODELS`, `WHISPER_LANGUAGES` (includes "Northern Sámi (Experimental)")
- Editor: `CHARACTER_LIMIT` (must match `SUBTITLE_LINE_LENGTH` in transcribe-worker — the worker wraps at it, the editor flags lines that exceed it), `CHARACTER_LIMIT_EXCEEDED_COLOR`, `CONFIDENCE_LOW`, `CONFIDENCE_MEDIUM`

Tunables belong here; wire-format constants do not. `WORDS_FORMAT_VERSION` in `utils/srt.py` stays in code — a deployment claiming a version the code does not implement would only mis-parse silently.

Access via `get_settings()` (cached).

## Admin hierarchy

- **BOFH** (`bofh=True`): sees everything, manages all realms and onboarding attributes
- **Realm Admin** (`admin=True`): scoped to own realm + `admin_domains`. Can manage rules for their realms
- **Regular User**: no admin access

## Onboarding rules (pages/admin.py)

- Rules page at `/admin/rules` — table with create/edit/delete dialogs and per-row test/delete actions
- Realm field is a multi-select dropdown filtered to real domains (containing a dot/TLD)
- Rules scoped by realm — admins within the same organisation see the same rules
- BOFH users see all rules across all realms
- Onboarding attributes section hidden for non-BOFH users
- Help dialog explains rule matching, actions, scoping, and manual override
- "Attributes" terminology used throughout (not "JWT claims")

## Testing

```bash
# All tests
.venv/bin/python -m pytest
```

`pytest.ini` configures `asyncio_mode = auto`, `main_file = main.py`, and loads `nicegui.testing.user_plugin`. Current test files: `tests/test_srt.py`, `tests/test_storage.py`, `tests/conftest.py`.
