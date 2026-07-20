# eip-points classification eval

Tests the free-text → Activity Category/Type classification rules in
`../references/classification.md` against a set of hand-written cases in
`tests.yaml`, using Promptfoo.

## Run

```bash
npx promptfoo@latest eval -c .claude/skills/eip-points/eval/promptfooconfig.yaml --no-cache
```

View results in the interactive viewer:

```bash
npx promptfoo@latest view
```

## Requirements

- The `claude` CLI installed and logged in (same auth as your Claude Code session).
  No `ANTHROPIC_API_KEY` needed — `claude.js` shells out to `claude -p ...` instead
  of calling the Anthropic API directly.
- `--no-cache` is recommended when iterating on `claude.js` or `prompt.txt`: Promptfoo's
  cache key is based on the provider id + prompt text, not the contents of files it
  shells out to, so edits to the script itself won't bust the cache on their own.

## Adding cases

Add a new entry to `tests.yaml` whenever a new recurring meeting format or
organizer mapping is added to `../references/classification.md`. Each case
needs `description` (the free text) and either:
- `expectedCategory` + `expectedType`, or
- `expectedCategory` only (when the type isn't fixed by the rules, e.g.
  organizer-based Come Together cases), or
- `expectedExcluded: true` (for routine meetings that shouldn't be logged).
ZZZ