---
name: summarize
description: Condense long text, conversations, logs, code or documents into accurate, decision-ready summaries. Use when the user asks for a summary, recap, TL;DR, briefing, executive digest, meeting notes, changelog digest, or context compression. Preserves facts, numbers, names and uncertainty; never invents content.
---

# Summarize

Produce a compact summary that a reader can act on without opening the source.

## Method
1. Identify the audience and the decision the summary must support. If unclear, state the assumption.
2. Extract: the main claim/outcome, supporting facts (numbers, dates, names, URLs), open items, and explicit uncertainties.
3. Drop examples, repetition and rhetorical framing. Keep exact figures and proper nouns verbatim.
4. Order by consequence, not by source order.

## Output shape
- **TL;DR** — 1–3 sentences: what happened / what was decided.
- **Key points** — at most 5 bullets, each one self-contained.
- **Open / unresolved** — bullets, or the single word `None`.
- **Sources** — filenames, message ids or URLs when available.

## Rules
- Never add facts that are not in the source. If something is unclear, write `not stated`.
- Preserve negation and magnitude (`no regression` ≠ `improved`; `p95 3s` ≠ `average 3s`).
- For code: summarise behaviour, changed interfaces and risk, not line-by-line diffs.
- For conversations: attribute decisions to speakers when identifiable; keep commitments and deadlines.
- For logs: lead with first error, count of repeats, and last known good state.
- Default length ≤ 250 words unless the user asks for a detailed brief.
- If the input is longer than the context window, summarise in chunks, then summarise the summaries; say that this was done.
