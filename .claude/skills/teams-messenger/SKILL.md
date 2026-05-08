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

All browser automation uses Playwright CLI via the Bash tool with session `-s=teams`. Use `snapshot` to read the page, then use `click`, `fill`, `type`, `press` with element refs from the snapshot output. There are no MCP browser tools.

**Node.js / npx**: Run `npx` plain. Only fall back to `source ~/.nvm/nvm.sh && npx ...` if a bare `npx` call fails because Node isn't on `PATH`.

## Input Parameters

- **message**: The text to send (required)
- **target**: Where to send it (optional, defaults to self-chat "Tonan Salas (You)")
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
3. Convert the message to HTML. The caller may pass the message as HTML already, or as markdown. If markdown, convert to simple HTML:
   - `# Heading` → `<b>Heading</b>`
   - `## Subheading` → `<b>Subheading</b>`
   - `**text**` → `<b>text</b>`
   - `* item` → wrap consecutive bullets in `<ul><li>item</li>...</ul>`
   - Blank lines → `<br>`
   - Plain text lines → `<p>text</p>`

4. Write the HTML to `/tmp/teams-msg-<slug>.html`.

5. Use **Swift** to set the macOS clipboard as HTML (this is the only approach that works — `osascript` and Python `AppKit` do NOT set the HTML MIME type correctly):
   ```bash
   swift -e '
   import AppKit
   let html = try! String(contentsOfFile: "/tmp/teams-msg.html", encoding: .utf8)
   let pb = NSPasteboard.general
   pb.clearContents()
   pb.setString(html, forType: .html)
   '
   ```

6. Paste into the Teams compose box:
   ```bash
   npx @playwright/cli@latest -s=teams press "Meta+v"
   ```
   Note: `press` for keyboard shortcuts does NOT take an element ref — just the key combo.

7. Snapshot to verify the formatted content landed. Grep the snapshot for a string that's **unique to this run** (today's date, a distinctive phrase from the message, or a freshly-quoted lead name). Don't grep generic markers like `strong` or `listitem` — the chat history above the compose box contains prior rich-text reports and will produce false positives.

8. Click the **Send** button (look for `button "Send (⌘ Return)"`).
9. Snapshot to verify the message appears in the chat with "Sent" status.

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
