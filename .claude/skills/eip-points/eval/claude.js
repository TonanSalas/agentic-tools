#!/usr/bin/env node
// Promptfoo custom provider that shells out to the already-authenticated
// Claude Code CLI instead of the Anthropic API, so no ANTHROPIC_API_KEY
// is needed to run this eval.

const { spawnSync } = require('child_process');

const prompt = process.argv[2];
const options = process.argv[3];

let model = 'sonnet';
if (options && options !== '{}') {
  try {
    const optionsObj = JSON.parse(options);
    if (optionsObj.config && optionsObj.config.model) {
      model = optionsObj.config.model;
    }
  } catch (e) {
    // fall through to default model
  }
}

const result = spawnSync('claude', ['-p', prompt, '--model', model], {
  encoding: 'utf8',
  stdio: ['pipe', 'pipe', 'pipe'],
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

if (result.status !== 0) {
  console.error(result.stdout || result.stderr);
  process.exit(result.status || 1);
}

console.log(result.stdout);
