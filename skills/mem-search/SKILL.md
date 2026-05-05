---
name: mem-search
description: Search kimi-mneme's persistent cross-session memory database. Use when user asks "did we already solve this?", "how did we do X last time?", "what did we do yesterday?", or needs work from previous sessions.
---

# Memory Search

Search past work across all sessions. Simple workflow: search → timeline → get.

## When to Use

Use when users ask about PREVIOUS sessions (not current conversation):

- "Did we already fix this?"
- "How did we solve X last time?"
- "What happened last week?"
- "What did we do yesterday?"
- "Remind me about the auth system"

## 3-Layer Workflow (ALWAYS Follow)

**NEVER fetch full details without filtering first. 10x token savings.**

### Step 1: Search — Get Index with IDs

Use the `mneme_search` plugin tool:

```
mneme_search(query="authentication", limit=20, project="my-project")
```

**Returns:** Table with IDs, timestamps, types, titles (~50-100 tokens/result)

```
| ID | Time | Type | Snippet |
|----|------|------|---------|
| #11131 | 3:48 PM | PostToolUse | Added JWT authentication... |
| #10942 | 2:15 PM | PostToolUse | Fixed auth token expiration... |
```

**Parameters:**

- `query` (string) — Search term (required)
- `limit` (number) — Max results, default 10, max 50
- `project` (string) — Project name filter
- `type` (string, optional) — "bugfix", "feature", "refactor", "docs", "test"
- `date_from` (string, optional) — YYYY-MM-DD
- `date_to` (string, optional) — YYYY-MM-DD

### Step 2: Timeline — Get Context Around Interesting Results

Use the `mneme_timeline` plugin tool:

```
mneme_timeline(observation_id=11131, radius=5)
```

**Returns:** `radius` items before + center + `radius` items after in chronological order.

**Parameters:**

- `observation_id` (number, required) — Observation ID to center around
- `radius` (number, optional) — Items before/after, default 5, max 20

### Step 3: Get — Fetch Full Details ONLY for Filtered IDs

Review titles from Step 1 and context from Step 2. Pick relevant IDs. Discard the rest.

Use the `mneme_get` plugin tool:

```
mneme_get(ids=[11131, 10942])
```

**ALWAYS use `mneme_get` for 2+ observations — single request vs N requests.**

**Parameters:**

- `ids` (array of numbers, required) — Observation IDs to fetch

**Returns:** Complete observation objects with tool_input, tool_output, error, prompt (~500-1000 tokens each)

## Examples

**Find recent bug fixes:**

```
mneme_search(query="bug", limit=20)
```

**Find what happened last week:**

```
mneme_search(query="", date_from="2026-04-28", limit=20)
```

**Understand context around a discovery:**

```
mneme_timeline(observation_id=11131, radius=5)
```

**Batch fetch details:**

```
mneme_get(ids=[11131, 10942, 10855])
```

## Why This Workflow?

- **Search index:** ~50-100 tokens per result
- **Full observation:** ~500-1000 tokens each
- **Batch fetch:** 1 request vs N requests
- **10x token savings** by filtering before fetching

## Auto-Injected Context

On session start, kimi-mneme automatically injects:
- Recent project activity summary
- Recurring patterns (errors, fixes)
- Structured observations from previous sessions

You can reference this context directly without searching.
