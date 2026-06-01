# agentic-tools

A Claude Code workspace with skills for automating weekly workflows — time logging, activity reporting, and browser automation via Playwright.

This README doubles as a **replication guide**: if you're Claude Code running on a *different* machine, the [Replicating these skills](#replicating-these-skills) section tells you how to build your own versions of the two hardest skills here — **browser automation against an SSO web app (the Workday pattern)** and **sending rich messages in Microsoft Teams**. The patterns generalize to other targets; the specifics below are the parts that took trial and error to get right, so start from them rather than rediscovering them.

## Skills in this repo

| Skill | What it does |
|-------|--------------|
| `/workday-timelogger` | Gathers GitHub activity, builds an entry plan, then fills the Workday timesheet via browser automation. |
| `/weekly-activity` | Auto-discovers active `dragonflyic` repos and reports commits/PRs/issues for a date range (Python + `gh`). |
| `/weekly-report` | Reorganizes activity by project into a status report and optionally posts it to Teams. |
| `/teams-messenger` | Sends a (rich-text) message to a Teams chat or channel via browser automation. |

Each skill lives in `.claude/skills/<name>/SKILL.md`. Read those files — they are the authoritative, battle-tested versions. This README explains the *reusable patterns* behind them.

**Usage examples:**
```
/workday-timelogger "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"
/weekly-activity 2026-04-07..2026-04-11
/teams-messenger "Standup done ✅" "Dragonfly Team"
```

---

## Replicating these skills

### Skill anatomy

A skill is a single `SKILL.md` file under `.claude/skills/<name>/`, with YAML frontmatter followed by an instruction body written *to the model* (you), in the second person. Supporting scripts/assets go in subfolders (`scripts/`, `cache/`, etc.).

```markdown
---
name: my-skill
description: One sentence. Lead with what it does, end with "Use when the user asks to …".
              This is the ONLY thing the model sees when deciding whether to trigger — make it specific.
user-invocable: true          # exposes it as /my-skill
allowed-tools: Bash, Read, Write, Edit, Skill   # least privilege; only what the body actually uses
arguments:
  - name: target
    description: "What it is, with concrete examples in the text."
    required: false
---

# My Skill

You <do X for the user>. <One-paragraph framing of the job.>

## Phase 1: …
## Phase 2: …
```

Principles that make these skills reliable:
- **Write the body as a procedure, not prose.** Numbered phases, explicit "do this / never do that". The model follows it like a runbook.
- **The `description` is the trigger.** It's matched against the user's request. Put the verbs and nouns a user would actually say ("log time", "send a Teams message").
- **Encode the failures you hit.** Most of the value in these two skills is the "this silently fails, do this instead" notes. Capture them inline the first time you discover them.
- **Confirm before irreversible/outward-facing actions.** Workday submits a timesheet; Teams sends a message to other people. Both skills show the user a plan and wait for approval before the committing step.

### Shared foundation: Playwright CLI browser automation

Both the Workday and Teams skills drive a real Chromium browser through the **Playwright CLI** — *not* an MCP browser tool. Every action is one `Bash` call to `npx @playwright/cli@latest`. This is the substrate for **any** "automate a website" skill.

The core loop is **snapshot → act by ref → snapshot**:

```bash
# 1. Open a persistent, headed, named session (login cookies survive across runs)
npx @playwright/cli@latest -s=<session> open "https://example.com" --persistent --headed

# 2. Read the page's accessibility tree — this prints element refs like e5, e12
npx @playwright/cli@latest -s=<session> snapshot

# 3. Act on a ref from the snapshot
npx @playwright/cli@latest -s=<session> click e12
npx @playwright/cli@latest -s=<session> fill e7 "some text"
npx @playwright/cli@latest -s=<session> select e9 "Option label"
npx @playwright/cli@latest -s=<session> press "Meta+v"        # keyboard shortcut: NO ref
```

Key facts that apply to every browser skill:

- **`-s=<name>` isolates a session.** Use a distinct name per skill (`workday`, `teams`) so their cookies/windows don't collide.
- **`--persistent --headed`** keeps the profile on disk (so SSO login is a one-time manual step) and keeps the window visible (so the user can complete auth and watch).
- **Refs come from `snapshot` and go stale.** Any action that mutates the DOM (selecting a dropdown option, opening a dialog) invalidates the refs you read before it. Re-snapshot after a mutation; reuse refs only while the page is static.
- **You can also click by accessible role+name** (e.g. `click 'button "Send"'`) — more stable than positional refs when the name is unique. Prefer this when you know the name; fall back to a ref from the snapshot otherwise.
- **SSO is interactive.** On first run the snapshot shows a login page. Tell the user to complete SSO in the Chrome window, then wait for their confirmation before continuing. The persistent profile means later runs are already authenticated.
- **`eval`** runs JS in the page (used in Workday to read element geometry). **`mousemove`/`mousedown`/`mouseup`** issue *real* mouse events at coordinates — needed when an element isn't in the accessibility tree (see Workday recipe).
- **Run `npx` plain.** Only prefix with `source ~/.nvm/nvm.sh &&` if a bare `npx` fails because Node isn't on `PATH`.

To adapt to a new site: open it, snapshot, read the refs/roles, and script the click/fill sequence. The art is handling the site-specific quirks below.

---

### Recipe A — automating an SSO web app (the Workday pattern)

Full implementation: [`.claude/skills/workday-timelogger/SKILL.md`](.claude/skills/workday-timelogger/SKILL.md). Use this when the target is a complex enterprise SPA (Workday, ServiceNow, SAP, Salesforce, etc.) behind corporate SSO.

**Shape of the skill:** gather inputs → build a plan → show the plan and get approval → log in → navigate → make changes → final review → submit. Generalize each phase:

1. **Gather / plan (no browser yet).** Do all the data work and arithmetic *before* opening the browser, and present it as tables the user confirms. The browser session is the expensive, fragile part — keep it short and pre-decided. (Workday calls the `weekly-activity` skill via the `Skill` tool to get its data, then builds the entry plan.)

2. **Log in via the *home* URL, never a deep link.** Deep-linking into an authenticated task while logged out often yields a broken error page instead of a redirect to login. Always open the app's home URL first; let it redirect to SSO cleanly, then navigate *within* the app to the task.

3. **Navigate via the app's own search/menu, and verify each step with a snapshot.** Don't assume a click worked — snapshot and confirm the expected heading/title appeared before the next action. Enterprise SPAs frequently render menu items outside the viewport where clicks silently fail; an in-app search box is usually more reliable.

4. **Clicking things the accessibility tree can't name.** This is the hardest part of these apps. Workday's empty timesheet day-cells aren't named elements, so you can't `click` them by ref. The solution generalizes:
   - Use `eval` once to read the bounding boxes of elements you *can* find (e.g. column headers), compute target coordinates, and reuse them.
   - Then synthesize a **real mouse click** at those coordinates — `mousemove x y && mousedown && mouseup`. A DOM `el.click()` is often swallowed by the app's own handlers; real mouse events are not.

5. **Re-snapshot after every state mutation.** Selecting a dropdown value reflows the form and changes the refs for the fields below it. Read the new refs before filling them.

6. **Two-step review before committing.** Enter all the data, screenshot the result, present a summary table, and ask the user to review in the browser and reply "approved". Only then click the app's Submit/Confirm. Never auto-submit.

7. **Handle the app's silent rewrites.** Document the cases where the app changes your input after submit (Workday reclassifies holiday entries) so the model doesn't mistake an expected relabel for a failure.

**Tool-call economy** (matters because each browser action is a round-trip): chain idempotent actions that don't change refs into one `Bash` call with `&&` (e.g. `mousemove x y && mousedown && mouseup`, or `fill <hours> "8" && fill <comment> "…" && click <ok>`), click by stable role+name to skip exploratory snapshots, and snapshot once per dialog *state* rather than once per click.

**To retarget:** the structure (plan → confirm → login-via-home → navigate-and-verify → mutate → review → submit) is identical for any SSO SPA. What you re-derive per app is: the home URL, how its search/nav works, which elements need real-mouse-event clicks, and where refs go stale.

---

### Recipe B — sending rich messages in Microsoft Teams

Full implementation: [`.claude/skills/teams-messenger/SKILL.md`](.claude/skills/teams-messenger/SKILL.md). Use this when a skill needs to post a notification or report to a chat/channel.

**Shape:** launch & log in → find the target conversation → compose & send → confirm. The non-obvious parts:

1. **Open `https://teams.microsoft.com` with a persistent session** (`-s=teams`). Same SSO-is-manual-on-first-run rule as Recipe A.

2. **Find the conversation by its accessibility role.** Teams' sidebar lists conversations as `treeitem`s with predictable name prefixes:
   - 1:1 chat → `treeitem "Chat <Name>"`
   - group chat → `treeitem "Group chat <Name>"`
   - meeting chat → `treeitem "Meeting chat <Name>"`
   - channel → expand `treeitem "Team <TeamName>"` then click `treeitem "Channel <ChannelName>"`

   Snapshot, find the matching treeitem, click it. If it's not visible, use the `combobox "Search"` at the top.

3. **Send rich text via the clipboard, not `fill`.** `fill` produces flat, unformatted text. To get Teams to render **bold**, bullets, and spacing, paste HTML through the OS clipboard:
   - Convert the message (markdown or HTML) to simple HTML: `**x**`/headings → `<b>`, bullet runs → `<ul><li>…</li></ul>`, blank lines → `<br>`, plain lines → `<p>`.
   - Put that HTML on the clipboard **with the `text/html` MIME type**. On macOS the *only* reliable way found is **Swift / `NSPasteboard`** — `osascript` and Python `AppKit` set the wrong type:
     ```bash
     swift -e '
     import AppKit
     let html = try! String(contentsOfFile: "/tmp/teams-msg.html", encoding: .utf8)
     let pb = NSPasteboard.general
     pb.clearContents()
     pb.setString(html, forType: .html)
     '
     ```
     > **Other platforms:** this Swift step is macOS-specific. On Linux use `xclip -selection clipboard -t text/html`; on Windows use a PowerShell `Set-Clipboard` / `System.Windows.Forms.Clipboard.SetText(..., Html)` equivalent. The rest of the recipe is unchanged.
   - Click the `textbox "Type a message"` to focus it, then paste: `press "Meta+v"` (Ctrl+V off macOS). `press` for a shortcut takes **no** element ref.

4. **Verify against the compose box specifically.** After pasting, snapshot and grep *within* the `textbox "Type a message"` block (e.g. `grep -A 30 'textbox "Type a message"'`) for a unique phrase from this message — the chat history above contains old reports and will give false positives if you grep the whole page.

5. **Send and confirm.** Click `button "Send (⌘ Return)"`, snapshot once, and confirm the unique phrase now appears in a *sent message bubble* (outside the compose box). Leave the browser open so the user can keep working. A `"Not a member"` warning is usually harmless — sending still works.

6. **Fallback:** if rich paste doesn't render, `fill` the plain text and tell the user formatting was lost.

**Run it cheaply as a sub-skill.** This skill is a deterministic recipe with no reasoning. When another skill (e.g. `weekly-report`) calls it non-interactively, launch it via the **`Agent` tool with `model: "claude-haiku-4-5-20251001"`** to save tokens. (Note: `model:` frontmatter on a skill is *not* honored by the current loader — skills run in the parent's context — so the Agent route is the only way to actually downshift.)

---

### Cross-cutting tips

- **Cache expensive data** so a chain of skills fetches once. `weekly-activity` caches GitHub results to a gitignored `cache/` folder (closed weeks cached forever, current week for 1 hour).
- **Permissions live in `.claude/settings.json`.** Pre-allow the commands your skills run (`Bash(npx:*)`, `Bash(gh:*)`, `Skill(...)`) so the user isn't prompted on every call.
- **Save screenshots to `.playwright-mcp/`**, not the repo root, and keep `.playwright-cli/` and `.playwright-mcp/` gitignored — they fill with per-action snapshot/console artifacts.

### `CLAUDE.md` setup

`CLAUDE.md` is auto-loaded into context for every Claude Code session in the repo, so it's where the always-on browser-automation conventions belong. Drop this into the repo's `./CLAUDE.md` (merge the Browser Automation block if one already exists); add other sections later if the repo needs them.

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Browser Automation

All browser automation uses Playwright CLI (`npx @playwright/cli@latest`) via Bash — no MCP browser tools. Key patterns:

- Named sessions: `-s=<name>` isolates the browser session
- `--persistent --headed` flags: preserves login cookies and keeps the browser visible
- Element refs (e.g., `e5`, `e12`) come from `snapshot` output and are used in `click`, `fill`, `select` commands
- SSO login is interactive — the user completes auth manually in the Chrome window

### CDP attach to Edge (workday-edge-login)

The `workday-edge-login` skill drives a real **Microsoft Edge** instead of Playwright's Chromium. Edge is launched with `--remote-debugging-port` on a dedicated `--user-data-dir` (`~/.edge-cdp-debug`) because Edge/Chromium 136+ block remote debugging on the *default* profile dir. The dedicated dir is seeded once from the real Edge profile (carries the Improving tenant), and lets the debug Edge coexist with the user's normal browsers. Playwright attaches with `attach --cdp=http://localhost:9333`. Use `detach` (not `close`) to release the session while leaving Edge open.
```

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| [Claude Code](#1-claude-code) | Runs the skills |
| [GitHub CLI (`gh`)](#2-github-cli-gh) | Queries GitHub activity |
| [Node.js via nvm](#3-nodejs-via-nvm) | Runs Playwright CLI via `npx` |
| [Python via pyenv](#4-python-via-pyenv) | Runs `gather_activity.py` |
| [uv](#5-uv) | Preferred Python script runner |

The browser skills (`workday-timelogger`, `teams-messenger`) need only Claude Code + Node.js (for `npx`). The activity skills add `gh` + Python. The Teams rich-text step additionally needs a `text/html` clipboard tool — `swift` on macOS (preinstalled with Xcode CLT), `xclip` on Linux, PowerShell on Windows.

---

### 1. Claude Code

Requires a paid Claude plan (Pro, Max, Team, Enterprise, or Console).

**macOS / Linux:**
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://claude.ai/install.ps1 | iex
```

Run `claude` after install to authenticate.

---

### 2. GitHub CLI (`gh`)

**macOS:**
```bash
brew install gh
gh auth login
```

**Windows:**
```powershell
winget install --id GitHub.cli --source winget
gh auth login
```

---

### 3. Node.js via nvm

**macOS / Linux:**
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash
nvm install --lts
```

**Windows:** Download and run the installer from the [nvm-windows releases page](https://github.com/coreybutler/nvm-windows/releases). Uninstall any existing Node.js first, then open an Admin terminal:
```powershell
nvm install lts
nvm use lts
```

---

### 4. Python via pyenv

**macOS:**
```bash
brew install pyenv
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init - zsh)"' >> ~/.zshrc
exec "$SHELL"
pyenv install 3.13
pyenv global 3.13
```

**Windows (PowerShell):**
```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/pyenv-win/pyenv-win/master/pyenv-win/install-pyenv-win.ps1" -OutFile "./install-pyenv-win.ps1"; &"./install-pyenv-win.ps1"
```
Reopen PowerShell, then:
```powershell
pyenv install 3.13.0
pyenv global 3.13.0
```

---

### 5. uv

Preferred runner for Python scripts (`uv run gather_activity.py`).

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

---

### 6. Playwright / Chromium

No install needed — Playwright CLI is fetched on demand via `npx`. Chromium downloads automatically on first run. To pre-install:
```bash
npx @playwright/cli@latest install chromium
```
