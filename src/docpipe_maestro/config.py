"""Static configuration constants and immutable chunking profiles.

Per Library Purity rules, no library module reads external config files;
profiles are defined strictly as immutable Python constants and resolved either
by registered name or by passing a custom ``ChunkingProfile`` instance.
"""

from __future__ import annotations

from docpipe_maestro.types import ChunkingProfile, DocpipeError

DEFAULT_COLLECTION = "default"
DEFAULT_PERSIST_DIR = ".docpipe"
DEFAULT_EMBED_MODEL = "ollama/nomic-embed-text"
DEFAULT_GENERATION_MODEL = "ollama/llama3.2"
DEFAULT_TOP_K = 5

DEFAULT = ChunkingProfile(
    name="DEFAULT",
    chunk_size=512,
    overlap=64,
    clause_preserving=False,
    parent_child=True,
    resolve_crossrefs=False,
)

POLICY = ChunkingProfile(
    name="POLICY",
    chunk_size=1000,
    overlap=80,
    clause_preserving=True,
    parent_child=True,
    resolve_crossrefs=True,
)

PROFILES: dict[str, ChunkingProfile] = {
    DEFAULT.name: DEFAULT,
    POLICY.name: POLICY,
}


def resolve_profile(profile: str | ChunkingProfile) -> ChunkingProfile:
    """Resolve a profile name or return a ``ChunkingProfile`` instance directly.

    Args:
        profile: Registered profile name (case-insensitive, e.g., ``"DEFAULT"``
            or ``"POLICY"``) or a custom ``ChunkingProfile`` instance.

    Returns:
        The resolved ``ChunkingProfile`` configuration.

    Raises:
        DocpipeError: If a string name does not match any registered profile.
    """
    if isinstance(profile, ChunkingProfile):
        return profile
    key = profile.strip().upper()
    if key not in PROFILES:
        valid = ", ".join(sorted(PROFILES))
        raise DocpipeError(f"Unknown chunking profile {profile!r}. Available profiles: {valid}")
    return PROFILES[key]
