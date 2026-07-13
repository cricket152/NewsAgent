# Prompt Skills

## What is a prompt-skill?

A prompt-skill is a Markdown (`.md`) file containing system-prompt instructions
that the agent can prepend to the conversation context at runtime.  Each skill
encodes a reusable instruction template — for example, "summarise news in
bullet points" or "translate answers into English".

Skills are **not** function calls or tool invocations.  They are plain text
artifacts that extend or override the default `SYSTEM_PROMPT` defined in
`conversation.py`.

## File naming convention

- Use lowercase with underscores: `<skill_name>.md`
- Examples: `news_summarizer.md`, `english_translator.md`, `debug_helper.md`
- Avoid spaces, special characters, or uppercase letters in filenames.

## How skills are loaded (future)

A future `load_skill(name: str) -> str` helper will:

1. Look for `<name>.md` inside this `skills/` directory.
2. Read the file content and strip any leading/trailing whitespace.
3. Return the text so it can be prepended to the conversation's system prompt
   before each LLM call.

This helper is **not yet implemented**.  The `skills/` directory and convention
defined here serve as the scaffold for that feature.

## Writing a skill

Every skill file should contain **only the system-prompt content** — no YAML
front-matter, no metadata block.  Keep files short (5–20 lines) so they remain
easy to compose at runtime.

Example:

```markdown
You are a news summariser.  Follow these rules:

1. Output exactly 3 bullet points.
2. Each bullet must be a single sentence.
3. Prefer facts over opinions.
4. Include one relevant date in each bullet.
5. Keep the total output under 200 characters.
```

The agent will merge this text with the base `SYSTEM_PROMPT` and any ongoing
conversation history before sending the request to the LLM.

## Directory layout

```
agent/
  skills/
    README.md              <-- this file
    news_summarizer.md     <-- sample skill (news summarisation)
    # more skills go here
```
