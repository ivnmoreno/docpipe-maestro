"""Phase 2 outbound PII egress guard and locality enforcement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import overload

from docpipe_maestro.types import DocpipeError, PiiBlockedError, PiiPolicy

__all__ = ["guard_egress"]


def _normalize_chat_sequence(payload: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Validate and shallow-copy role-separated chat messages."""
    if isinstance(payload, (str, bytes, bytearray)):
        raise DocpipeError("Invalid payload: expected a sequence of role/content message mappings.")
    if not payload:
        raise DocpipeError("Invalid payload: message sequence must not be empty.")
    copied: list[dict[str, str]] = []
    for idx, entry in enumerate(payload):
        if not isinstance(entry, Mapping):
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: expected a dict with 'role' and 'content'."
            )
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(role, str) or not role.strip():
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: 'role' must be a non-empty string."
            )
        if not isinstance(content, str):
            raise DocpipeError(
                f"Invalid prompt message at index {idx}: 'content' must be a string."
            )
        copied.append({"role": role, "content": content})
    return copied


@overload
def guard_egress(
    payload: str,
    *,
    model: str,
    api_base: str | None = None,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> str: ...


@overload
def guard_egress(
    payload: Sequence[Mapping[str, str]],
    *,
    model: str,
    api_base: str | None = None,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> list[dict[str, str]]: ...


def guard_egress(
    payload: str | Sequence[Mapping[str, str]],
    *,
    model: str,
    api_base: str | None = None,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> str | list[dict[str, str]]:
    """Enforce ``local_only`` endpoint checks and egress PII scrubbing on outbound prompts.

    Supports both plain prompt strings and role-separated ChatML sequences without
    mutating caller containers or altering non-text role metadata.
    """
    normalized_msgs = None if isinstance(payload, str) else _normalize_chat_sequence(payload)

    if local_only:
        from docpipe_maestro.embedder import enforce_local_only

        enforce_local_only(model, api_base, operation="generation")

    if pii_policy is None:
        return payload if isinstance(payload, str) else list(normalized_msgs or [])

    from docpipe_maestro._pii import evaluate_pii_text, validate_pii_policy
    from docpipe_maestro.embedder import is_local_target

    validated = validate_pii_policy(pii_policy)
    if is_local_target(model, api_base) or validated.egress == "allow":
        return payload if isinstance(payload, str) else list(normalized_msgs or [])

    if isinstance(payload, str):
        transformed, _, _, _ = evaluate_pii_text(
            payload,
            validated,
            phase="egress",
            egress_mode=True,
            raise_on_block=True,
        )
        return transformed

    if normalized_msgs is None:
        return []
    guarded_msgs: list[dict[str, str]] = []
    agg_counts: dict[str, int] = {}
    agg_actions: dict[str, str] = {}
    agg_blocked: set[str] = set()

    for msg in normalized_msgs:
        new_content, counts, actions, blocked = evaluate_pii_text(
            msg["content"],
            validated,
            phase="egress",
            egress_mode=True,
            raise_on_block=False,
        )
        for entity, count in counts.items():
            agg_counts[entity] = agg_counts.get(entity, 0) + count
        for entity, action in actions.items():
            if agg_actions.get(entity) != "block":
                agg_actions[entity] = action
        agg_blocked.update(blocked)
        guarded_msgs.append({"role": msg["role"], "content": new_content})

    if agg_blocked:
        blocked_sorted = tuple(sorted(agg_blocked))
        raise PiiBlockedError(
            f"Blocked PII entity type(s) {list(blocked_sorted)!r} during outbound egress.",
            entity_counts=dict(sorted(agg_counts.items())),
            actions=dict(sorted(agg_actions.items())),
            blocked_entities=blocked_sorted,
            source="",
            phase="egress",
        )

    return guarded_msgs
