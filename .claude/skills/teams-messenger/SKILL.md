---
name: teams-messenger
description: Send a message to a Microsoft Teams chat or channel via Playwright browser automation. Use when the user asks to send a Teams message, notify a channel, or post to Teams.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit
arguments:
  - name: message
    description: "The message text to send"
    required: true
  - name: target
    description: "Chat or channel name to send to (e.g. 'Tonan Salas (You)', 'Dragonfly Team', 'Improving > General', 'MX-AGS > General'). Defaults to self-chat."
    required: false
---

# Teams Messenger

You send messages to Microsoft Teams chats or channels via Playwright browser automation. You receive a message and a target (chat name or channel), navigate to it, type the message, and send it.

> **Performance note**: This skill is a deterministic Playwright recipe and needs no reasoning. When invoking it from another skill non-interactively, prefer launching it via the `Agent` tool with `model: "claude-haiku-4-5-20251001"` to save tokens. (The current Claude Code skill loader runs skills in the parent model's context — `model:` frontmatter on the skill itself is not honored, so the Agent route is the only way to actually downshift.)

All browser automation uses Playwright CLI via the Bash tool with session `-s=teams`. Use `snapshot` to read the page, then use `click`, `fill`, `type`, `press` with element refs from the snapshot output. There are no MCP browser tools.

**Node.js / npx**: Run `npx` plain. Only fall back to `source ~/.nvm/nvm.sh && npx ...` if a bare `npx` call fails because Node isn't on `PATH`.

## Input Parameters

- **message**: The text to send (required)
- **target**: Where to send it (optional, defaults to self-chat "Tonan Salas (You)")
- **--message-file FILE**: read the message from this file instead of inline text (markdown or HTML). The `weekly-log` harness always passes the message this way.
- **--dry-run**: do every step — navigate, convert, paste, verify the compose box — but do **not** click Send. Report `DRY RUN: message staged in <chat>, not sent`, then clear the compose box with `press "Meta+a"` followed by `press "Backspace"`.
  - Chat: Use the chat name as shown in the sidebar (e.g., "Isaura Parga Mora", "Dragonfly Team", "AI Coding Club")
  - Channel: Use "Team > Channel" format (e.g., "Improving > General", "MX-AGS > Estacionamiento")

## Phase 1: Launch Browser & Navigate to Teams

Open a persistent, headed browser session pointing to Teams:
```bash
npx @playwright/cli@latest -s=teams open "https://teams.microsoft.com" --persistent --headed
```

Snapshot the page to check login state. If redirected to a login/SSO page, tell the user to complete authentication in the Chrome window and wait for confirmation. Once logged in, verify the Teams UI is loaded (look for the Chat or Activity buttons in the sidebar).

## Phase 2: Navigate to Target

### For Chats (default)

1. Click the **Chat** button in the left sidebar (look for `button "Chat (⌃ ⇧ 2)"`).
2. Click the **Chats** tab (not Channels) if not already selected — look for `button "Chats"`.
3. Snapshot the chat list and look for a `treeitem` matching the target name.
   - Chat names appear as: `treeitem "Chat <Name> <Status>"` (e.g., `treeitem "Chat Tonan Salas (You)"`)
   - Group chats appear as: `treeitem "Group chat <Name>"` (e.g., `treeitem "Group chat Dragonfly Team"`)
   - Meeting chats appear as: `treeitem "Meeting chat <Name>"` (e.g., `treeitem "Meeting chat AIR MX Remote"`)
4. Click the matching treeitem to open the chat.
5. If the target is not visible, scroll down in the chat list or use the search bar (`combobox "Search"`) to find it.

### For Channels

1. Click the **Chat** button in the left sidebar.
2. Click the **Channels** button to switch to the channels view.
3. Snapshot the channel list. Channels are nested under teams:
   - `treeitem "Team <TeamName>"` → `treeitem "Channel <ChannelName>"`
4. If the team is collapsed, click it to expand.
5. Click the target channel's treeitem.
6. If the channel has a "See all channels" option and the target isn't visible, click it to see more.

## Phase 3: Send Message

Do NOT use `fill` — it produces plain, unformatted text. Instead, paste HTML via the macOS clipboard so Teams renders bold, bullets, and spacing correctly.

### Step-by-step procedure

1. Snapshot the page to find the message input — look for `textbox "Type a message"`.
2. Click the textbox to focus it.
3. Write the message (markdown or HTML, exactly as given) to `/tmp/teams-msg-<slug>.md`, or use the `--message-file` path directly.
4. Convert it and put it on the clipboard in one call. Never hand-convert markdown and never call Swift yourself — the script owns both (rules tested in `tests/test_to_teams_html.py`):
   ```bash
   python3 "<skill-directory>/scripts/to_teams_html.py" --in /tmp/teams-msg-<slug>.md --out /tmp/teams-msg-<slug>.html --clipboard
   ```
   It prints the HTML it produced; keep a distinctive phrase from it for the checks below.
5. Paste into the Teams compose box:
   ```bash
   npx @playwright/cli@latest -s=teams press "Meta+v"
   ```
   Note: `press` for keyboard shortcuts does NOT take an element ref — just the key combo.
6. Snapshot once and grep within the `textbox "Type a message"` block specifically — never grep the whole snapshot, since the chat history above the compose box contains prior rich-text reports and will produce false positives. Use a context-aware grep like `grep -A 30 'textbox "Type a message"'` and check that the distinctive phrase appears inside that block.
7. **Dry run?** If `--dry-run` was given, stop here: report `DRY RUN: message staged in <chat>, not sent`, clear the box (`press "Meta+a"` then `press "Backspace"`), and leave the browser open. Do not click Send.
8. Click the **Send** button by role name: `npx @playwright/cli@latest -s=teams click 'button "Send (⌘ Return)"'`. Always click Send by its role name, never by ref — the repo's sentinel hook recognises the committing click by its name. If the click is blocked by that hook, report the hook's message verbatim and stop; never retry with another selector or key combo.
9. Snapshot once after send and confirm the same phrase now appears in a message bubble (outside the compose textbox).

This whole flow should be ~6–7 tool calls total. Avoid extra snapshots between steps that already returned page state.

### HTML format reference

Here's the HTML structure that produces the correct Teams formatting:

```html
<b>Title Here</b><br>
<b>Label:</b> Value<br>
<b>Label:</b> Value<br>
<br>
<b>Section Header</b><br>
Paragraph text here.<br>
<br>
<b>Another Section</b>
<ul>
<li>Bullet item one</li>
<li>Bullet item two</li>
</ul>
```

### Fallback

If the clipboard paste fails (content doesn't render as rich text), fall back to `fill` with plain text and tell the user formatting was lost so they can copy-paste manually.

## Phase 4: Confirmation

After the message is sent:

1. Verify the message appears in the conversation (look for the message text in a heading or group element with "Sent" status).
2. Report to the user: which chat/channel received the message, the timestamp, and confirmation of delivery.
3. Leave the browser open (do NOT close it) so the user can continue interacting.

## Error Handling

- **Chat/Channel not found**: List visible chats/channels and ask the user to clarify the target name.
- **"Not a member" warning**: This sometimes appears but messages can still be sent — proceed with sending.
- **Textbox not found**: Snapshot and look for alternative input elements. The compose area may have a different ref after navigation.
- **Message not delivered**: Snapshot, check for error banners, and report to the user.
- **SSO timeout**: Navigate back to `https://teams.microsoft.com` and ask the user to re-authenticate.
- **Search needed**: If the target chat isn't in the visible list, use the search combobox at the top — type the person or group name, then select from results.
