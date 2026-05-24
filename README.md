# agentic-tools

A Claude Code workspace with skills for automating weekly workflows — time logging, activity reporting, and browser automation via Playwright.

## Skills

### `/workday-timelogger`

Automates time entry into Workday. Gathers GitHub activity via the `weekly-activity` skill, builds an entry plan with two tables (Workday entries + referenced issues), then fills in the Workday timesheet using browser automation.

**Usage:**
```
/workday-timelogger "Mon 11, Tue 8, Wed 8, Thu 8, Fri 5"
```

### `/weekly-activity`

Gathers GitHub activity across all `dragonflyic` repos for a date range. Returns a day-by-day breakdown of commits, PRs, and issues.

**Usage:**
```
/weekly-activity 2026-04-07..2026-04-11
```

## Browser Automation

The `workday-timelogger` skill uses Playwright CLI (`npx @playwright/cli@latest`) for browser automation. Each action (navigate, click, fill, snapshot) is a separate Bash call with a named session (`-s=workday`). The `--persistent` flag preserves login sessions across runs.

## Prerequisites

| Tool | Purpose |
|------|---------|
| [Claude Code](#1-claude-code) | Runs the skills |
| [GitHub CLI (`gh`)](#2-github-cli-gh) | Queries GitHub activity |
| [Node.js via nvm](#3-nodejs-via-nvm) | Runs Playwright CLI via `npx` |
| [Python via pyenv](#4-python-via-pyenv) | Runs `gather_activity.py` |
| [uv](#5-uv) | Preferred Python script runner |

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
