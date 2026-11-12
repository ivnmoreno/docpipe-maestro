"""Phase 2 pure prompt builder with strict grounding and source attribution."""

from __future__ import annotations

from collections.abc import Sequence

from docpipe_maestro.types import RetrievedChunk

_SYSTEM_INSTRUCTIONS = (
    "You are a precise assistant. Answer the user's question using ONLY the provided "
    "context sections below. Cite the source document, section, and page (when present) "
    "for every claim. If the answer is not contained in the provided context, state "
    "explicitly that the answer is not present in the provided context."
)


def build_prompt(question: str, sections: Sequence[RetrievedChunk]) -> str:
    """Pure function: construct a grounded prompt string with source citations."""
    if not sections:
        context_block = "(No relevant context sections retrieved.)"
    else:
        formatted_sections: list[str] = []
        for idx, sec in enumerate(sections, start=1):
            meta = sec.metadata
            parts = [f"Source: {meta['source']}", f"Section: {meta['section']}"]
            if meta["clause"] is not None:
                parts.append(f"Clause: {meta['clause']}")
            if meta["page"] is not None:
                parts.append(f"Page: {meta['page']}")
            header = f"[{idx}] " + " | ".join(parts)
            formatted_sections.append(f"{header}\n{sec.text}")
        context_block = "\n\n---\n\n".join(formatted_sections)

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"## Context\n\n{context_block}\n\n"
        f"## Question\n\n{question}\n\n"
        "## Answer\n"
    )
