# AI agents

<p class="lead">Ask your coding agent for a lane map ("Monaco, lane by lane, bus lanes in orange") and it can do it right the first time: lanestyle ships what an agent needs in one page.</p>

## The agent skill

The [skill](https://github.com/Khoshkhah/lanestyle/blob/master/skills/lanestyle/SKILL.md) is one
page for agents that write code (Claude Code, Codex, Cursor, …): the install, where lanes come
from, the lane table, the one call and its settings, the JavaScript API, and the traps (64-bit
ids, feature ids versus lane ids, lane 1 on the left, what needs the turns table).

**Claude Code**, as a plugin:

```text
/plugin marketplace add Khoshkhah/lanestyle
/plugin install lanestyle@lanestyle
```

or as a plain skill:

```bash
mkdir -p ~/.claude/skills/lanestyle && curl -fsSL -o ~/.claude/skills/lanestyle/SKILL.md \
  https://raw.githubusercontent.com/Khoshkhah/lanestyle/master/skills/lanestyle/SKILL.md
```

Other agents: point them at that file, or paste it into the project's agent instructions.

## The docs as text

The whole site is also published for language models, following the
[llms.txt](https://llmstxt.org) convention:

- [`llms.txt`](https://khoshkhah.github.io/lanestyle/llms.txt): a short index of the pages;
- [`llms-full.txt`](https://khoshkhah.github.io/lanestyle/llms-full.txt): every page as Markdown, in one file.

## Working on lanestyle

Coding agents that change lanestyle itself read
[`AGENTS.md`](https://github.com/Khoshkhah/lanestyle/blob/master/AGENTS.md): the layout, the
commands, and the project's rules (Claude Code reads it through `CLAUDE.md`).

## The rest of the stack

[roadstyle](https://khoshkhah.github.io/roadstyle/guides/agents/) has its own skill and an MCP
server for drawing road maps without code; [mapstyle](https://khoshkhah.github.io/mapstyle/guides/agents/)
and [duckOSM](https://github.com/Khoshkhah/duckOSM) have skills too. A lanestyle page is a
roadstyle page, so roadstyle's JavaScript API and host-page advice apply as they are.
