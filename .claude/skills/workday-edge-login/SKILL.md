---
name: workday-edge-login
description: Opens Microsoft Edge with CDP remote debugging, attaches to it via Playwright over CDP, logs into Workday (interactive SSO), and lands on the Enter My Time page. Use when the user wants to open Workday time logging in an attachable Edge browser (rather than the default Playwright Chromium).
user-invocable: true
allowed-tools: Bash, Read
---

# Workday Edge Login (CDP)

You launch Microsoft **Edge** with remote debugging enabled, attach to it with
the Playwright CLI **over CDP**, log into Workday, and stop on the **Enter My
Time** page. This is the login/navigation front-end only — it does not enter any
time. (Time entry lives in the `workday-timelogger` skill.)

Unlike `workday-timelogger`, which uses Playwright's own headed Chromium, this
skill drives a real Edge instance you can also see and interact with yourself.

## Why Edge needs a dedicated profile

Edge/Chromium 136+ **refuse to enable `--remote-debugging-port` on the default
profile directory** (security hardening). So we launch Edge against a dedicated
`--user-data-dir` at `~/.edge-cdp-debug`, seeded once from the real Edge profile
so it inherits the **Improving tenant identity** for SSO. Because it's a separate
profile dir, this debug Edge **coexists with any normal Edge/Chrome** the user
already has open — nothing gets closed.

Workday's own session is short-lived, so **first login is interactive SSO**.
After that, the persistent `~/.edge-cdp-debug` profile keeps you signed in across
runs (until the session expires).

## Phase 1: Launch Edge + attach over CDP

1. Run the launch helper. It is idempotent — if a debugging Edge is already up on
   the port, it reuses it instead of opening a second window:

   ```bash
   bash .claude/skills/workday-edge-login/launch_edge_cdp.sh 9333
   ```

   Success prints `CDP_ENDPOINT=http://localhost:9333`. (On the very first run it
   seeds `~/.edge-cdp-debug` from the real Edge profile — that's expected.)

2. Attach the Playwright CLI to that endpoint under session `workday-edge`:

   ```bash
   npx @playwright/cli@latest -s=workday-edge attach --cdp=http://localhost:9333
   ```

   The attach output lists open tabs and the current page. From here, drive the
   page with `-s=workday-edge` plus `snapshot`, `click`, `fill`, `goto`, etc. —
   same command set as the other Workday skill. There are no MCP browser tools.

   If `attach` reports the current tab is `edge://new-tab-page` or similar, run
   `goto` to the Workday home URL (next phase) on the active tab.

## Phase 2: Log into Workday

**Always start at the home URL, never the Enter My Time URL directly** — hitting
the task URL while unauthenticated returns a confusing error page; the home URL
redirects cleanly to login.

```bash
npx @playwright/cli@latest -s=workday-edge goto "https://wd5.myworkday.com/improving/d/home.htmld"
```

Snapshot to check login state:

```bash
npx @playwright/cli@latest -s=workday-edge snapshot
```

- **If the page title is `Workday improving - Sign in to Workday`** (the
  "Sign In to Your Account" card with *Single Sign-on* / *Login with Workday
  ID/Password*): click the **Single Sign-on** link:

  ```bash
  npx @playwright/cli@latest -s=workday-edge click 'link "Single Sign-on Login Using SSO"'
  ```

  SSO then goes through the Improving IdP (Okta / Microsoft). If it requires
  manual auth or MFA, **tell the user to complete sign-in in the Edge window**
  and wait for their confirmation before continuing. Re-snapshot after they
  confirm.

- **If the page title is already `Workday improving`** with the home dashboard
  visible, you're logged in — skip straight to Phase 3.

## Phase 3: Navigate to Enter My Time

Once logged in (home dashboard visible), open Enter My Time via the **Search
Workday** combobox in the top banner — more reliable than the side Menu shortcut
(which is often outside the viewport and silently fails to click):

1. Click the "Search Workday" combobox in the banner.
2. Snapshot. If "Enter My Time" already appears under **Recent Searches** (it will
   after the first run, since the profile retains history), click it directly.
   Otherwise type `enter my time` to trigger the search dropdown.
3. Snapshot — the dropdown shows a clickable "Enter My Time" task result. Click
   it by ref.
4. Verify the **Enter My Time** heading is visible (page title becomes
   `Enter My Time - Workday`).

Take a screenshot and report success:

```bash
npx @playwright/cli@latest -s=workday-edge screenshot
```

(The CLI writes the PNG under `.playwright-cli/`; read that path to view it.)

Report to the user that Edge is open, attached over CDP on
`http://localhost:9333`, logged in, and sitting on the Enter My Time page. Leave
the browser open — do **not** close it.

## Detach vs. close

- `npx @playwright/cli@latest -s=workday-edge detach` — releases the Playwright
  session but **leaves Edge running** (so you can re-attach later). Prefer this.
- Do **not** run `close` / `close-all` / `kill-all` unless the user explicitly
  asks — that would kill their Edge window.

## Error handling

- **`CDP endpoint did not come up`**: another process may hold the port, or Edge
  failed to start. Check `/tmp/edge-cdp-9333.log`. Retry with a different port
  (e.g. `... launch_edge_cdp.sh 9334` then attach to `:9334`).
- **`attach` fails / "no browser"**: confirm the endpoint is live with
  `curl -s http://localhost:9333/json/version`; re-run the launch helper.
- **Stuck on the login page after SSO**: the IdP session likely expired — ask the
  user to complete the SSO + MFA prompts in the Edge window, then re-snapshot.
- **Session timeout mid-flow**: `goto` the home URL again to re-auth cleanly; never
  navigate directly to the Enter My Time task URL while logged out.
