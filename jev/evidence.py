#!/usr/bin/env python3
"""urai/jev/evidence.py — Evidence ledger for Urai agents (stdlib only).

Inspired by Odysseus's evidence-first discipline, originally implemented in
odysseus-dev/odysseus src/agent_evidence.py.

The core idea: every tool call an agent makes is a piece of *evidence*.
Before accepting an agent's final answer, we audit it — do the factual claims
in the answer trace back to recorded evidence, or are they fabricated?

Key concepts
------------
MUTATION_TOOLS      Tools that change state (write, edit, run code that mutates).
VALIDATION_TOOLS    Tools that verify outcomes (test runners, linters, checkers).
OBSERVATION_TOOLS   Tools that only read (read_file, list_dir, grep, etc.).

EvidenceLedger      Accumulates evidence entries during a single agent run and
                    exposes helpers for auditing claims against that evidence.

wrap_agent_run      Thin decorator that wires a ledger around any agent function,
                    automatically flagging unsupported claims in the final answer.

Typical usage
-------------
    ledger = EvidenceLedger()
    ledger.add("read_file", {"path": "foo.py"}, "def hello(): ...")
    ledger.add("run_code", {"code": "pytest tests/"}, "5 passed")
    report = ledger.verify("All tests pass")
    # → {"supported": True, "evidence_ids": ["ev_2"], "confidence": 0.9}

    result = wrap_agent_run("Write a function", my_agent_fn)
    # → result dict with "flagged_claims" key added
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tool classification sets
# ---------------------------------------------------------------------------

#: Tools that modify persistent state — must appear in evidence before a
#: mutation claim is accepted as supported.
MUTATION_TOOLS: set[str] = {
    "write_file",
    "edit_file",
    "patch_file",
    "delete_file",
    "run_code",
    "execute_bash",
    "apply_patch",
    "create_file",
    "overwrite_file",
    "insert_lines",
    "replace_lines",
    "move_file",
    "rename_file",
}

#: Tools that validate or verify outcomes.
VALIDATION_TOOLS: set[str] = {
    "run_code",          # dual-purpose: mutation AND validation when running tests
    "run_tests",
    "lint",
    "typecheck",
    "format_check",
    "diff",
    "verify",
    "assert_file_contains",
    "check_output",
}

#: Tools that purely observe — reading, listing, searching.
OBSERVATION_TOOLS: set[str] = {
    "read_file",
    "list_directory",
    "glob",
    "grep_search",
    "file_search",
    "search_codebase",
    "get_document_symbols",
    "hover",
    "diagnostics",
    "find_references",
    "web_fetch",
    "remote_web_search",
}

# ---------------------------------------------------------------------------
# Evidence entry
# ---------------------------------------------------------------------------


@dataclass
class EvidenceEntry:
    """A single recorded tool execution."""
    id: str
    tool_name: str
    args: dict
    result: Any
    timestamp: float = field(default_factory=time.time)
    is_mutation: bool = False
    is_validation: bool = False
    is_observation: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "args": self.args,
            "result_preview": str(self.result)[:200],
            "timestamp": self.timestamp,
            "is_mutation": self.is_mutation,
            "is_validation": self.is_validation,
            "is_observation": self.is_observation,
        }


# ---------------------------------------------------------------------------
# Claim extraction helpers
# ---------------------------------------------------------------------------

# Patterns that suggest a factual claim requiring evidence.
_CLAIM_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(the file|file)\s+\S+\s+(was|is|has been)\s+(written|created|updated|deleted|saved)", re.I),
    re.compile(r"\b(all|the)\s+tests?\s+(pass(ed)?|succeed(ed)?|ran successfully)", re.I),
    re.compile(r"\b(the code|it)\s+(runs?|executed?|compiled?|works?)\s+(successfully|correctly|without error)", re.I),
    re.compile(r"\b(no errors?|no warnings?|no issues?)\s+(found|detected|reported)", re.I),
    re.compile(r"\b(the function|method|class)\s+\S+\s+(exists?|is defined|was found)", re.I),
    re.compile(r"\b(I (wrote|created|edited|updated|deleted|saved|modified))\b", re.I),
    re.compile(r"\b(successfully (wrote|created|edited|updated|deleted|ran|executed))\b", re.I),
    re.compile(r"\b(the output (is|was|shows?|contains?))\b", re.I),
    re.compile(r"\b\d+\s+(tests?|specs?|examples?)\s+(passed|failed|skipped)", re.I),
]


def _extract_claims(text: str) -> list[str]:
    """Return a list of sentence fragments that look like factual claims."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    claims = []
    for sentence in sentences:
        for pattern in _CLAIM_PATTERNS:
            if pattern.search(sentence):
                claims.append(sentence.strip())
                break
    return claims


# ---------------------------------------------------------------------------
# EvidenceLedger
# ---------------------------------------------------------------------------


class EvidenceLedger:
    """Accumulates tool-call evidence during an agent run and audits claims.

    Evidence entries are keyed by auto-generated IDs (ev_<uuid4[:8]>).
    The ledger is intentionally simple and in-memory; it is scoped to a
    single agent invocation.
    """

    def __init__(self) -> None:
        self._entries: list[EvidenceEntry] = []
        self._index: dict[str, EvidenceEntry] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def add(self, tool_name: str, args: dict, result: Any) -> str:
        """Record a tool execution as an evidence entry.

        Args:
            tool_name: Name of the tool that was called.
            args:      Arguments passed to the tool.
            result:    The tool's return value / output.

        Returns:
            The evidence entry ID (e.g. "ev_3a7f1b2c").
        """
        eid = f"ev_{uuid.uuid4().hex[:8]}"
        entry = EvidenceEntry(
            id=eid,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {"raw": args},
            result=result,
            is_mutation=self.has_mutation(tool_name),
            is_validation=self.has_validation(tool_name),
            is_observation=tool_name in OBSERVATION_TOOLS,
        )
        self._entries.append(entry)
        self._index[eid] = entry
        return eid

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def has_mutation(tool_name: str) -> bool:
        """Return True if *tool_name* is classified as a mutation tool."""
        return tool_name in MUTATION_TOOLS

    @staticmethod
    def has_validation(tool_name: str) -> bool:
        """Return True if *tool_name* is classified as a validation tool."""
        return tool_name in VALIDATION_TOOLS

    # ------------------------------------------------------------------
    # Claim verification
    # ------------------------------------------------------------------

    def verify(self, claim: str) -> dict:
        """Check whether *claim* is supported by recorded evidence.

        Heuristic approach:
        1. Extract key tokens from the claim (file names, tool outcomes, numbers).
        2. Search entry results and args for matching tokens.
        3. Score confidence as (matching_entries / max(1, relevant_entries)).

        Returns:
            {
                "supported": bool,
                "evidence_ids": list[str],   # entries that back the claim
                "confidence": float,          # 0.0 – 1.0
                "claim": str,
            }
        """
        claim_lower = claim.lower()
        # Tokenise: words ≥3 chars, file-like paths, numbers
        tokens = set(re.findall(r"[\w./\\-]{3,}", claim_lower))
        tokens -= {"the", "was", "has", "been", "that", "this", "with", "from",
                   "are", "all", "and", "for", "its", "not", "but", "any"}

        supporting: list[str] = []
        for entry in self._entries:
            result_text = str(entry.result).lower()
            args_text = " ".join(str(v).lower() for v in entry.args.values())
            combined = result_text + " " + args_text

            match_count = sum(1 for t in tokens if t in combined)
            if match_count >= max(1, len(tokens) // 2):
                supporting.append(entry.id)

        # Boost confidence if a validation tool is among supporters
        has_val = any(
            self._index[eid].is_validation for eid in supporting
            if eid in self._index
        )
        base_conf = min(1.0, len(supporting) / max(1, len(self._entries)))
        confidence = min(1.0, base_conf + (0.2 if has_val else 0.0))

        return {
            "supported": bool(supporting),
            "evidence_ids": supporting,
            "confidence": round(confidence, 2),
            "claim": claim,
        }

    # ------------------------------------------------------------------
    # Unsupported claim scanning
    # ------------------------------------------------------------------

    def unsupported_claims(self, text: str) -> list[dict]:
        """Scan *text* for factual claims not backed by evidence.

        Returns a list of verify() result dicts for each detected claim
        that is NOT supported (supported=False).
        """
        claims = _extract_claims(text)
        unsupported = []
        for claim in claims:
            result = self.verify(claim)
            if not result["supported"]:
                unsupported.append(result)
        return unsupported

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of all evidence entries.

        This string is suitable for injection into an agent's context window
        so it can reference its own prior actions.
        """
        if not self._entries:
            return "No evidence recorded."

        lines = [f"Evidence ledger ({len(self._entries)} entries):"]
        for entry in self._entries:
            tags = []
            if entry.is_mutation:
                tags.append("MUTATION")
            if entry.is_validation:
                tags.append("VALIDATION")
            if entry.is_observation:
                tags.append("OBSERVATION")
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            result_preview = str(entry.result)[:120].replace("\n", " ")
            args_preview = ", ".join(
                f"{k}={str(v)[:40]}" for k, v in list(entry.args.items())[:3]
            )
            lines.append(
                f"  {entry.id}{tag_str} | {entry.tool_name}({args_preview}) "
                f"→ {result_preview}"
            )
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"EvidenceLedger(entries={len(self._entries)})"


# ---------------------------------------------------------------------------
# wrap_agent_run
# ---------------------------------------------------------------------------


def wrap_agent_run(
    task: str,
    run_fn: Callable[..., dict],
    *args: Any,
    **kwargs: Any,
) -> dict:
    """Run *run_fn* with evidence tracking and post-process its answer.

    Creates a fresh EvidenceLedger, passes it into *run_fn* via the keyword
    argument ``ledger`` (the function must accept it), then audits the returned
    answer for unsupported claims.

    If *run_fn* does not accept a ``ledger`` keyword argument, the ledger is
    still created and the answer is still audited — but the function won't
    be able to record evidence dynamically (evidence will be empty, so all
    claims will be flagged).

    Args:
        task:   Human-readable description of the task (used in the audit report).
        run_fn: Callable that returns a dict with at least an "answer" key.
        *args:  Positional arguments forwarded to *run_fn*.
        **kwargs: Keyword arguments forwarded to *run_fn*.

    Returns:
        The dict returned by *run_fn*, augmented with:
            "ledger_summary":   str  — full evidence ledger text
            "flagged_claims":   list — unsupported claims found in the answer
            "evidence_count":   int  — number of evidence entries recorded
    """
    ledger = EvidenceLedger()

    # Attempt to inject the ledger; gracefully degrade if not accepted
    try:
        import inspect
        sig = inspect.signature(run_fn)
        if "ledger" in sig.parameters:
            kwargs["ledger"] = ledger
    except Exception:
        pass

    result = run_fn(*args, **kwargs)

    if not isinstance(result, dict):
        result = {"answer": str(result)}

    answer = result.get("answer", "")
    flagged = ledger.unsupported_claims(answer)

    result["ledger_summary"] = ledger.summary()
    result["flagged_claims"] = flagged
    result["evidence_count"] = len(ledger)

    if flagged:
        claim_texts = "; ".join(f["claim"][:60] for f in flagged[:3])
        result.setdefault("warnings", []).append(
            f"Unsupported claims detected ({len(flagged)}): {claim_texts}"
        )

    return result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def new_ledger() -> EvidenceLedger:
    """Return a fresh EvidenceLedger instance."""
    return EvidenceLedger()
