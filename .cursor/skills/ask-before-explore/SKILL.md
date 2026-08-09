---
name: ask-before-explore
description: Ask the user for leading before exploring the project or discovering files. Use when the agent needs to explore the codebase, search for unknown file locations, run broad Grep/Glob, or use Task explore without a known path. Do not use when the user already gave a path or the target file is already known.
---

# Ask Before Explore

Before broad exploration or file discovery, **stop and ask the user where to look**. Do not start searching first.

## When to ask

Ask when you would otherwise:

- Explore the project to find where something lives
- Run broad `Grep` / `Glob` / directory walks without a known path
- Use Task explore or similar discovery

## When not to ask

Skip when:

- The user already gave a path, directory, or “look in X”
- The target is already known from this conversation
- The action is a narrow read/edit of a known file
- The user said to explore freely / skip asking

## Flow

1. State **intent** (what you want to find) and **why** (how it serves the current task).
2. Ask where to look (paths, dirs, or keywords).
3. Wait for the user’s reply.
4. Explore **only** the areas they indicated. If still unclear, ask again.

## Message template

```markdown
I need to explore before continuing.

**Intent:** [what to find]
**Why:** [why this exploration is needed]
**Ask:** Where should I look (paths, dirs, or keywords)?
```
