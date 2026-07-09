---
name: eip-points-invite
description: Generates a shareable EIP Points activity link on the Improving Engage portal and sends it to a Microsoft Teams chat so attendees can self-register their points. Use when the user asks to share/send an EIP points link for a meeting, invite people to register EIP points, or post the EIP link to Teams.
user-invocable: true
allowed-tools: Bash, Skill, Read, Write
arguments:
  - name: activity
    description: "Free-text description of the meeting/activity, e.g. 'AIR for non developers' or 'Personal Coaching session about career growth'."
    required: true
  - name: target
    description: "Teams chat or channel to send the link to (e.g. 'AIR for non developers' meeting chat, or 'Team > Channel'). Defaults to a chat/meeting matching the activity name."
    required: false
---

# EIP Points Invite

You generate a shareable EIP Points "Add Activity" link on Engage for a given activity/meeting, then send that link to a Microsoft Teams chat so attendees can self-register their own points. This chains two existing skills' automation: the Engage form-filling flow (from `eip-points`) stopped at "Copy Link" instead of submitting, and the `teams-messenger` send flow.

## Phase 1: Generate the EIP Link (Engage, session `-s=engage`)

Reuse the same form-fill logic as the `eip-points` skill (see `.claude/skills/eip-points/SKILL.md` for the category/type reference tables), but **never click "Add N points"** — this flow only produces a shareable link, it does not register an activity on your own account.

1. Open Engage and log in:
   ```bash
   npx @playwright/cli@latest -s=engage open "https://engage.improving.com/account/login" --persistent --headed
   ```
   Snapshot to confirm login (redirects to `/app/main/dashboard/employee-home`). If SSO needs manual auth, ask the user to complete it and wait for confirmation.

2. Navigate directly to the activity form:
   ```bash
   npx @playwright/cli@latest -s=engage goto "https://engage.improving.com/app/main/involvement/activity"
   ```
   Snapshot (re-snapshot once if it renders blank right after navigation — SPA render delay).

3. Map the user's `activity` description to the best-matching **Activity Category** (see the known category list in `eip-points/SKILL.md`), select it, then re-snapshot to read the dynamically-populated **Activity Type** options and select the closest match.

4. Fill **Notes** with the activity description (this is what attendees will see was pre-filled). Leave **Date** as today and **Quantity** as 1 unless the user specifies otherwise.

5. Snapshot to confirm the "Copy Link" and "Add N points" buttons are both enabled (this means the form is valid).

6. **Present a preview** to the user (category, type, date, quantity, notes, computed points) and ask for confirmation before generating/sending the link — same gate as `eip-points` Phase 4.

7. Once confirmed, click **Copy Link** (do not click "Add N points"). Read the generated URL back from the system clipboard rather than assuming it landed only visually:
   ```bash
   npx @playwright/cli@latest -s=engage eval "() => navigator.clipboard.readText()"
   ```
   This returns a URL like `https://engage.improving.com/app/main/involvement/activity?guid=<uuid>`.

## Phase 2: Send the Link to Teams

Invoke the `teams-messenger` skill via the Skill tool with the generated link and the resolved target:

```
skill: "teams-messenger", args: 'Send to the "<target>" Teams chat this message: "Regístrate y llévate tus puntos de EIP: <link>"'
```

If `target` wasn't provided, default to the Teams chat/meeting-chat whose name matches the `activity` text (e.g. activity "AIR for non developers" → look for `treeitem "Meeting chat AIR for non developers..."` per the `teams-messenger` chat-list lookup). If no clear match exists, ask the user which chat/channel to use before invoking `teams-messenger`.

## Phase 3: Final Summary

Report to the user:
- The generated EIP link
- The category/type/points it will award to whoever fills it in
- Which Teams chat/channel it was sent to, and confirmation it was delivered (from `teams-messenger`'s own confirmation)

Leave both browser sessions (`-s=engage`, `-s=teams`) open — do not close them — in case the user wants to send the link elsewhere too or make further edits.

## Error Handling

- **Category/Type ambiguous**: pick the closest match and flag it clearly in the preview so the user can correct it before confirming.
- **Clipboard read returns empty/stale value**: re-click "Copy Link" and re-read; the button can be clicked more than once safely.
- **No matching Teams chat found for the activity name**: list a few visible chat names (from a `teams-messenger` snapshot) and ask the user to pick the right target.
- **Engage or Teams session expired**: re-open the respective login URL and re-authenticate, then resume from where the session dropped.
