"""Phase-neutral PII validation, deterministic recognizers, and HMAC tokenization.

Maintains zero imports from ``docpipe_maestro.ingest`` or ``docpipe_maestro.query`` so
both Phase 1 (``PiiEnricher``) and Phase 2 (``query.egress``) share one canonical
recognizer registry, policy validator, overlap resolver, and tokenization engine.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.util
import ipaddress
import logging
import math
import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from secrets import token_bytes
from typing import Any

from docpipe_maestro._registry import Registry
from docpipe_maestro.types import (
    DocpipeError,
    EgressAction,
    MissingExtraError,
    PiiAction,
    PiiBlockedError,
    PiiDetection,
    PiiErrorMode,
    PiiPolicy,
    PiiRecognizer,
)

logger = logging.getLogger(__name__)

_ALLOWED_POLICY_KEYS = frozenset(
    {
        "types",
        "min_confidence",
        "languages",
        "on_error",
        "egress",
        "ner",
        "token_salt",
        "token_salt_env",
    }
)
_VALID_ACTIONS: frozenset[str] = frozenset({"redact", "tokenize", "block"})
_VALID_EGRESS_ACTIONS: frozenset[str] = frozenset({"redact", "block", "allow"})
_VALID_ERROR_MODES: frozenset[str] = frozenset({"fail", "continue"})
_DEFAULT_LANGUAGES: tuple[str, ...] = ("en", "es")
_IMPLIED_NER_ENTITIES: frozenset[str] = frozenset({"PERSON", "LOCATION", "ORGANIZATION"})

_SALT_LOCK = threading.Lock()
_PROCESS_FALLBACK_SALT: bytes | None = None
_FALLBACK_SALT_WARNED = False

_DNI_CONTROL_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

# ISO 13616 country code -> exact IBAN length mapping for deterministic MOD-97 checks.
_IBAN_LENGTHS: dict[str, int] = {
    "AD": 24,
    "AE": 23,
    "AL": 28,
    "AT": 20,
    "AZ": 28,
    "BA": 20,
    "BE": 16,
    "BG": 22,
    "BH": 22,
    "BI": 27,
    "BR": 29,
    "BY": 28,
    "CH": 21,
    "CR": 22,
    "CY": 28,
    "CZ": 24,
    "DE": 22,
    "DJ": 27,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "EG": 29,
    "ES": 24,
    "FI": 18,
    "FO": 18,
    "FR": 27,
    "GB": 22,
    "GE": 22,
    "GI": 23,
    "GL": 18,
    "GR": 27,
    "GT": 28,
    "HN": 28,
    "HR": 21,
    "HU": 28,
    "IE": 22,
    "IL": 23,
    "IQ": 23,
    "IS": 26,
    "IT": 27,
    "JO": 30,
    "KW": 30,
    "KZ": 20,
    "LB": 28,
    "LC": 32,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "LY": 25,
    "MC": 27,
    "MD": 24,
    "ME": 22,
    "MK": 19,
    "MR": 27,
    "MT": 31,
    "MU": 30,
    "NI": 28,
    "NL": 18,
    "NO": 15,
    "OM": 23,
    "PK": 24,
    "PL": 28,
    "PS": 29,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "RS": 22,
    "SA": 24,
    "SC": 31,
    "SD": 18,
    "SE": 24,
    "SI": 19,
    "SK": 24,
    "SM": 27,
    "SO": 23,
    "ST": 25,
    "SV": 28,
    "TN": 24,
    "TR": 26,
    "UA": 29,
    "VA": 22,
    "VG": 24,
    "XK": 20,
    "YE": 30,
}

_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"
    r"[A-Za-z0-9](?:[A-Za-z0-9._%+\-]*[A-Za-z0-9])?"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,24}"
    r"(?![A-Za-z0-9_])"
)
_IBAN_START_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?=[ \-]?[A-Za-z0-9])")
_CARD_RE = re.compile(r"(?<![+\dA-Za-z.])\d(?:[ \-]\d|\d){12,18}(?![\dA-Za-z]|\.\d)")
_SSN_RE = re.compile(r"(?<![A-Za-z0-9.\-])(\d{3})([ \-])(\d{2})\2(\d{4})(?![A-Za-z0-9\-]|\.\d)")
_IPV4_RE = re.compile(r"(?<![A-Za-z0-9.\-])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9\-]|\.\d)")
_IPV6_RE = re.compile(
    r"(?<![A-Za-z0-9:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}"
    r"(?:%[A-Za-z0-9_.-]+)?(?![A-Za-z0-9:])"
)
_PHONE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\w)\+\d{1,3}(?:[ .\-()]?\d){6,14}(?!\w)"),
    re.compile(r"(?<!\w)\(\d{2,4}\)[ .\-]?\d{3,4}[ .\-]?\d{3,4}(?:[ .\-]?\d{2,4})?(?!\d)"),
    re.compile(
        r"(?<![\w.\-/+])(?:\d{3}[\- ]\d{3}[\- ]\d{4}"
        r"|\d{3}[\- ]\d{2}[\- ]\d{2}[\- ]\d{2})(?![\w\-/]|\.\d)"
    ),
)
_DNI_RE = re.compile(r"(?<![A-Za-z0-9])(\d{8})[\- ]?([A-Za-z])(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class ValidatedPiiPolicy:
    """Normalized and strictly validated PII policy configuration."""

    types: dict[str, PiiAction]
    min_confidence: float
    languages: tuple[str, ...]
    on_error: PiiErrorMode
    egress: EgressAction
    ner: bool
    token_salt: str
    token_salt_env: str


PII_RECOGNIZERS: Registry[PiiRecognizer] = Registry("pii_recognizer")
register_pii_recognizer = PII_RECOGNIZERS.register


def _language_matches(supported: tuple[str, ...], requested: tuple[str, ...]) -> bool:
    """Return ``True`` if recognizer scope covers at least one requested language."""
    if "*" in supported:
        return True
    norm_supported = {lang.strip().lower() for lang in supported}
    for lang in requested:
        low = lang.strip().lower()
        primary = low.split("-", 1)[0]
        if low in norm_supported or primary in norm_supported:
            return True
    return False


@PII_RECOGNIZERS.register("email_address")
class EmailAddressRecognizer:
    """Deterministic RFC-style email address recognizer."""

    name: str = "builtin:email_address"
    entity_type: str = "EMAIL_ADDRESS"
    supported_languages: tuple[str, ...] = ("*",)

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for valid email address spans."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        for match in _EMAIL_RE.finditer(text):
            cand = match.group(0)
            if ".." in cand:
                continue
            detections.append(
                {
                    "entity_type": self.entity_type,
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.95,
                    "recognizer": self.name,
                }
            )
        return detections


@PII_RECOGNIZERS.register("iban_code")
class IbanCodeRecognizer:
    """Deterministic ISO 13616 IBAN recognizer with MOD-97 verification."""

    name: str = "builtin:iban_code"
    entity_type: str = "IBAN_CODE"
    supported_languages: tuple[str, ...] = ("*",)

    @staticmethod
    def _is_valid_iban(raw: str) -> bool:
        compact = raw.replace(" ", "").replace("-", "").upper()
        expected_len = _IBAN_LENGTHS.get(compact[:2])
        if expected_len is None or len(compact) != expected_len:
            return False
        if not (compact[:2].isalpha() and compact[2:4].isdigit() and compact[4:].isalnum()):
            return False
        rearranged = compact[4:] + compact[:4]
        rem = 0
        for ch in rearranged:
            if ch.isdigit():
                rem = (rem * 10 + int(ch)) % 97
            else:
                val = ord(ch) - 55
                rem = (rem * 100 + val) % 97
        return rem == 1

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for MOD-97 verified IBAN candidates."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        pos = 0
        text_len = len(text)
        while pos < text_len:
            match = _IBAN_START_RE.search(text, pos)
            if match is None:
                break
            start = match.start()
            country = text[start : start + 2].upper()
            expected_len = _IBAN_LENGTHS.get(country)
            if expected_len is None:
                pos = match.end()
                continue

            idx = start
            alnum_count = 0
            last_was_sep = False
            while idx < text_len and alnum_count < expected_len:
                ch = text[idx]
                if ch.isalnum() and ch.isascii():
                    alnum_count += 1
                    last_was_sep = False
                    idx += 1
                elif ch in (" ", "-") and alnum_count >= 4 and not last_was_sep:
                    last_was_sep = True
                    idx += 1
                else:
                    break

            if (
                alnum_count == expected_len
                and (idx == text_len or not text[idx].isalnum())
                and self._is_valid_iban(text[start:idx])
            ):
                detections.append(
                    {
                        "entity_type": self.entity_type,
                        "start": start,
                        "end": idx,
                        "score": 0.95,
                        "recognizer": self.name,
                    }
                )
                pos = idx
            else:
                pos = match.end()
        return detections


@PII_RECOGNIZERS.register("credit_card")
class CreditCardRecognizer:
    """Deterministic payment card recognizer with Luhn mod-10 verification."""

    name: str = "builtin:credit_card"
    entity_type: str = "CREDIT_CARD"
    supported_languages: tuple[str, ...] = ("*",)

    @staticmethod
    def _passes_luhn(digits: str) -> bool:
        if not (13 <= len(digits) <= 19) or len(set(digits)) <= 1:
            return False
        total = 0
        for idx, ch in enumerate(reversed(digits)):
            val = int(ch)
            if idx % 2 == 1:
                val *= 2
                if val > 9:
                    val -= 9
            total += val
        return total % 10 == 0

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for Luhn-valid payment card numbers."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        for match in _CARD_RE.finditer(text):
            raw = match.group(0)
            if len({c for c in raw if c in " -"}) > 1:
                continue
            digits = raw.replace(" ", "").replace("-", "")
            if not self._passes_luhn(digits):
                continue
            detections.append(
                {
                    "entity_type": self.entity_type,
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.95,
                    "recognizer": self.name,
                }
            )
        return detections


@PII_RECOGNIZERS.register("us_ssn")
class UsSsnRecognizer:
    """Deterministic US Social Security Number recognizer with SSA band filtering."""

    name: str = "builtin:us_ssn"
    entity_type: str = "US_SSN"
    supported_languages: tuple[str, ...] = ("en", "*")

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for delimited US SSN values excluding invalid SSA bands."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        for match in _SSN_RE.finditer(text):
            area = int(match.group(1))
            group = int(match.group(3))
            serial = int(match.group(4))
            if area in (0, 666) or 900 <= area <= 999 or group == 0 or serial == 0:
                continue
            detections.append(
                {
                    "entity_type": self.entity_type,
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.90,
                    "recognizer": self.name,
                }
            )
        return detections


@PII_RECOGNIZERS.register("ip_address")
class IpAddressRecognizer:
    """Deterministic IPv4/IPv6 recognizer backed by stdlib ``ipaddress``."""

    name: str = "builtin:ip_address"
    entity_type: str = "IP_ADDRESS"
    supported_languages: tuple[str, ...] = ("*",)

    @staticmethod
    def _is_valid_ip(candidate: str) -> bool:
        host_part = candidate.split("%", 1)[0]
        try:
            ipaddress.ip_address(host_part)
            return True
        except ValueError:
            return False

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for valid IPv4/IPv6 spans skipping software versions."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        seen_spans: set[tuple[int, int]] = set()
        for pattern in (_IPV4_RE, _IPV6_RE):
            for match in pattern.finditer(text):
                cand = match.group(0)
                if not self._is_valid_ip(cand):
                    continue
                span = (match.start(), match.end())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                detections.append(
                    {
                        "entity_type": self.entity_type,
                        "start": match.start(),
                        "end": match.end(),
                        "score": 0.90,
                        "recognizer": self.name,
                    }
                )
        return detections


@PII_RECOGNIZERS.register("phone_number")
class PhoneNumberRecognizer:
    """Bounded international and regional phone number heuristic recognizer."""

    name: str = "builtin:phone_number"
    entity_type: str = "PHONE_NUMBER"
    supported_languages: tuple[str, ...] = ("*",)

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for delimited phone numbers (7-15 digits) avoiding dates."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        seen_spans: set[tuple[int, int]] = set()
        for pattern in _PHONE_PATTERNS:
            for match in pattern.finditer(text):
                cand = match.group(0)
                digit_count = sum(1 for ch in cand if ch.isdigit())
                if not (7 <= digit_count <= 15):
                    continue
                span = (match.start(), match.end())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                detections.append(
                    {
                        "entity_type": self.entity_type,
                        "start": match.start(),
                        "end": match.end(),
                        "score": 0.75,
                        "recognizer": self.name,
                    }
                )
        return detections


@PII_RECOGNIZERS.register("es_dni")
class EsDniRecognizer:
    """Deterministic Spanish DNI recognizer with MOD-23 control-letter verification."""

    name: str = "builtin:es_dni"
    entity_type: str = "ES_DNI"
    supported_languages: tuple[str, ...] = ("es",)

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
        """Scan ``text`` for MOD-23 validated Spanish 8-digit + letter DNI numbers."""
        if not _language_matches(self.supported_languages, languages):
            return []
        detections: list[PiiDetection] = []
        for match in _DNI_RE.finditer(text):
            digits, letter = match.group(1), match.group(2).upper()
            expected = _DNI_CONTROL_LETTERS[int(digits) % 23]
            if letter != expected:
                continue
            detections.append(
                {
                    "entity_type": self.entity_type,
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.95,
                    "recognizer": self.name,
                }
            )
        return detections


def validate_pii_policy(policy: PiiPolicy) -> ValidatedPiiPolicy:
    """Validate and normalize a structured ``PiiPolicy`` mapping."""
    if not isinstance(policy, Mapping):
        raise DocpipeError("Invalid pii_policy: expected a mapping object.")

    unknown_keys = sorted(set(policy) - _ALLOWED_POLICY_KEYS)
    if unknown_keys:
        raise DocpipeError(f"Unsupported pii_policy field(s): {unknown_keys}")

    raw_types = policy.get("types", {})
    if not isinstance(raw_types, Mapping):
        raise DocpipeError("Invalid pii_policy 'types': expected mapping of entity type to action.")

    normalized_types: dict[str, PiiAction] = {}
    for raw_entity, raw_action in raw_types.items():
        if not isinstance(raw_entity, str) or not raw_entity.strip():
            raise DocpipeError("Invalid pii_policy 'types' key: expected non-blank entity string.")
        entity = raw_entity.strip().upper()
        if not isinstance(raw_action, str) or raw_action not in _VALID_ACTIONS:
            raise DocpipeError(
                f"Invalid PII action for {entity!r}: expected one of {sorted(_VALID_ACTIONS)}."
            )
        if entity in normalized_types and normalized_types[entity] != raw_action:
            raise DocpipeError(f"Conflicting pii_policy actions configured for {entity!r}.")
        normalized_types[entity] = raw_action

    raw_conf = policy.get("min_confidence", 0.6)
    if (
        isinstance(raw_conf, bool)
        or not isinstance(raw_conf, (int, float))
        or not math.isfinite(float(raw_conf))
        or not (0.0 <= float(raw_conf) <= 1.0)
    ):
        raise DocpipeError(
            "Invalid pii_policy 'min_confidence': must be finite float/int in [0.0, 1.0]."
        )
    min_confidence = float(raw_conf)

    raw_langs = policy.get("languages", list(_DEFAULT_LANGUAGES))
    if (
        isinstance(raw_langs, (str, bytes))
        or not isinstance(raw_langs, Sequence)
        or len(raw_langs) == 0
    ):
        raise DocpipeError(
            "Invalid pii_policy 'languages': expected non-empty sequence of language codes."
        )
    languages_list: list[str] = []
    seen_langs: set[str] = set()
    for item in raw_langs:
        if not isinstance(item, str) or not item.strip():
            raise DocpipeError(
                "Invalid pii_policy 'languages' entry: expected non-blank ISO language string."
            )
        code = item.strip().lower()
        if code not in seen_langs:
            seen_langs.add(code)
            languages_list.append(code)

    raw_on_error = policy.get("on_error", "fail")
    if not isinstance(raw_on_error, str) or raw_on_error not in _VALID_ERROR_MODES:
        raise DocpipeError(
            f"Invalid pii_policy 'on_error': expected one of {sorted(_VALID_ERROR_MODES)}."
        )

    raw_egress = policy.get("egress", "redact")
    if not isinstance(raw_egress, str) or raw_egress not in _VALID_EGRESS_ACTIONS:
        raise DocpipeError(
            f"Invalid pii_policy 'egress': expected one of {sorted(_VALID_EGRESS_ACTIONS)}."
        )

    raw_ner = policy.get("ner", False)
    if not isinstance(raw_ner, bool):
        raise DocpipeError("Invalid pii_policy 'ner': expected boolean.")

    raw_salt = policy.get("token_salt", "")
    if not isinstance(raw_salt, str):
        raise DocpipeError("Invalid pii_policy 'token_salt': expected string.")

    raw_salt_env = policy.get("token_salt_env", "")
    if not isinstance(raw_salt_env, str):
        raise DocpipeError("Invalid pii_policy 'token_salt_env': expected string.")

    return ValidatedPiiPolicy(
        types=normalized_types,
        min_confidence=min_confidence,
        languages=tuple(languages_list),
        on_error=raw_on_error,
        egress=raw_egress,
        ner=raw_ner,
        token_salt=raw_salt,
        token_salt_env=raw_salt_env.strip(),
    )


def resolve_token_salt(policy: PiiPolicy | ValidatedPiiPolicy) -> bytes:
    """Resolve explicit ``token_salt`` -> env var -> cached 32-byte random salt."""
    if isinstance(policy, ValidatedPiiPolicy):
        explicit_salt = policy.token_salt
        salt_env = policy.token_salt_env
    else:
        validated = validate_pii_policy(policy)
        explicit_salt = validated.token_salt
        salt_env = validated.token_salt_env

    if explicit_salt:
        return explicit_salt.encode("utf-8")

    if salt_env:
        env_val = os.environ.get(salt_env, "")
        if env_val:
            return env_val.encode("utf-8")

    global _PROCESS_FALLBACK_SALT, _FALLBACK_SALT_WARNED
    with _SALT_LOCK:
        if _PROCESS_FALLBACK_SALT is None:
            _PROCESS_FALLBACK_SALT = token_bytes(32)
        if not _FALLBACK_SALT_WARNED:
            _FALLBACK_SALT_WARNED = True
            logger.warning(
                "No persistent PII token_salt or populated token_salt_env configured; "
                "using process-scoped random salt (cross-process deterministic correlation "
                "requires setting a persistent salt)."
            )
        return _PROCESS_FALLBACK_SALT


def tokenize_value(entity_type: str, value: str, *, salt: bytes) -> str:
    """Return ``'[{ENTITY}_{sha256_hmac[:8]}]'`` deterministically from ``value`` and ``salt``."""
    normalized = entity_type.strip().upper()
    digest = hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"[{normalized}_{digest}]"


def _build_presidio_analyzer(
    analyzer_cls: type[Any],
    *,
    languages: tuple[str, ...],
) -> Any:
    """Instantiate Presidio ``AnalyzerEngine`` offline without model downloads."""
    module_name = str(getattr(analyzer_cls, "__module__", ""))
    if (
        module_name.startswith("presidio_analyzer")
        and importlib.util.find_spec("spacy") is not None
    ):
        spacy_mod = importlib.import_module("spacy")
        provider_mod = importlib.import_module("presidio_analyzer.nlp_engine")
        model_candidates: dict[str, tuple[str, ...]] = {
            "en": ("en_core_web_lg", "en_core_web_md", "en_core_web_sm", "en_core_web_trf"),
            "es": ("es_core_news_lg", "es_core_news_md", "es_core_news_sm", "es_dep_news_trf"),
        }
        selected_models: list[dict[str, str]] = []
        missing_langs: list[str] = []
        for lang in languages:
            norm = lang.split("-", 1)[0].strip().lower()
            candidates = model_candidates.get(
                norm,
                (
                    f"{norm}_core_news_lg",
                    f"{norm}_core_news_md",
                    f"{norm}_core_news_sm",
                    f"{norm}_core_web_lg",
                    f"{norm}_core_web_md",
                    f"{norm}_core_web_sm",
                ),
            )
            matched_pkg = next(
                (pkg for pkg in candidates if spacy_mod.util.is_package(pkg)),
                None,
            )
            if matched_pkg is None:
                missing_langs.append(lang)
            else:
                selected_models.append({"lang_code": lang, "model_name": matched_pkg})

        if missing_langs:
            raise DocpipeError(
                f"Optional PII NER spaCy models are missing offline for language(s) "
                f"{missing_langs!r}; automatic downloads are disabled."
            )
        nlp_engine = provider_mod.NlpEngineProvider(
            nlp_configuration={"nlp_engine_name": "spacy", "models": selected_models}
        ).create_engine()
        return analyzer_cls(nlp_engine=nlp_engine, supported_languages=list(languages))

    try:
        return analyzer_cls(supported_languages=list(languages))
    except TypeError:
        return analyzer_cls()


def _run_ner_recognizers(
    text: str,
    *,
    entity_types: tuple[str, ...],
    languages: tuple[str, ...],
) -> list[PiiDetection]:
    """Lazily run optional ``[pii]`` Presidio NER across all configured ``languages``."""
    try:
        from presidio_analyzer import AnalyzerEngine
    except ImportError as exc:
        raise MissingExtraError(
            "Optional NER PII detection requires the [pii] extra: "
            "install with `pip install 'docpipe-maestro[pii]'` and download spaCy language "
            f"models needed for {list(languages)!r} / entities {list(entity_types)!r}."
        ) from exc

    try:
        engine = _build_presidio_analyzer(AnalyzerEngine, languages=languages)
        detections: list[PiiDetection] = []
        target_entities = list(entity_types)
        for lang in languages:
            results = engine.analyze(text=text, entities=target_entities, language=lang)
            for res in results:
                ent = str(getattr(res, "entity_type", "")).strip().upper()
                start = getattr(res, "start", -1)
                end = getattr(res, "end", -1)
                score = getattr(res, "score", 0.0)
                if (
                    isinstance(start, int)
                    and isinstance(end, int)
                    and not isinstance(score, bool)
                    and isinstance(score, (int, float))
                ):
                    detections.append(
                        {
                            "entity_type": ent,
                            "start": start,
                            "end": end,
                            "score": float(score),
                            "recognizer": f"presidio:{lang}",
                        }
                    )
        return detections
    except DocpipeError:
        raise
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        raise DocpipeError(
            f"Optional PII NER backend failed offline for languages {list(languages)!r}: {exc}"
        ) from exc


def _needs_ner_backend(
    validated: ValidatedPiiPolicy,
    registered_entities: set[str],
) -> bool:
    """Determine whether optional ``[pii]`` Presidio NER should run for ``validated``."""
    if validated.ner:
        return True
    return any(
        entity in _IMPLIED_NER_ENTITIES and entity not in registered_entities
        for entity in validated.types
    )


def _resolve_overlaps(candidates: Sequence[PiiDetection]) -> list[PiiDetection]:
    """Select non-overlapping spans ordered by ``(-score, -(end - start), start)``."""
    ordered = sorted(
        candidates,
        key=lambda det: (-det["score"], -(det["end"] - det["start"]), det["start"]),
    )
    selected: list[PiiDetection] = []
    for cand in ordered:
        start, end = cand["start"], cand["end"]
        overlaps = any(not (end <= kept["start"] or start >= kept["end"]) for kept in selected)
        if not overlaps:
            selected.append(cand)
    selected.sort(key=lambda det: det["start"])
    return selected


def _collect_detections(
    text: str,
    validated: ValidatedPiiPolicy,
) -> list[PiiDetection]:
    """Execute registered recognizers (and optional NER) and filter valid candidates."""
    if not text or not validated.types:
        return []

    candidates: list[PiiDetection] = []
    registered_entities: set[str] = set()
    text_len = len(text)
    recognizer_keys = PII_RECOGNIZERS.keys()

    for key in recognizer_keys:
        cls = PII_RECOGNIZERS.resolve(key)
        recognizer = cls()
        registered_entities.add(recognizer.entity_type.strip().upper())
        if recognizer.entity_type.strip().upper() not in validated.types:
            continue
        try:
            raw_hits = recognizer.detect(text, languages=validated.languages)
        except Exception as exc:
            if validated.on_error == "continue":
                logger.warning(
                    "PII recognizer %r failed (%s); continuing per on_error='continue'.",
                    key,
                    type(exc).__name__,
                )
                continue
            raise DocpipeError(f"PII recognizer {key!r} failed: {type(exc).__name__}") from exc

        for hit in raw_hits:
            ent = str(hit.get("entity_type", "")).strip().upper()
            start = hit.get("start", -1)
            end = hit.get("end", -1)
            score = hit.get("score", 0.0)
            if (
                ent not in validated.types
                or not isinstance(start, int)
                or not isinstance(end, int)
                or not (0 <= start < end <= text_len)
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
            ):
                continue
            fscore = float(score)
            if fscore < validated.min_confidence or not (0.0 <= fscore <= 1.0):
                continue
            candidates.append(
                {
                    "entity_type": ent,
                    "start": start,
                    "end": end,
                    "score": fscore,
                    "recognizer": str(hit.get("recognizer") or f"custom:{key}"),
                }
            )

    if _needs_ner_backend(validated, registered_entities):
        ner_entities = tuple(sorted(validated.types))
        try:
            ner_hits = _run_ner_recognizers(
                text, entity_types=ner_entities, languages=validated.languages
            )
        except MissingExtraError:
            raise
        except Exception as exc:
            if validated.on_error == "continue":
                logger.warning(
                    "Optional PII NER analysis failed (%s); continuing per on_error='continue'.",
                    type(exc).__name__,
                )
                ner_hits = []
            elif isinstance(exc, DocpipeError):
                raise
            else:
                raise DocpipeError(f"PII NER backend failed: {type(exc).__name__}") from exc

        for hit in ner_hits:
            ent = str(hit.get("entity_type", "")).strip().upper()
            start = hit.get("start", -1)
            end = hit.get("end", -1)
            score = float(hit.get("score", 0.0))
            if (
                ent in validated.types
                and 0 <= start < end <= text_len
                and score >= validated.min_confidence
                and 0.0 <= score <= 1.0
            ):
                candidates.append(
                    {
                        "entity_type": ent,
                        "start": start,
                        "end": end,
                        "score": score,
                        "recognizer": str(hit.get("recognizer") or "presidio"),
                    }
                )

    return _resolve_overlaps(candidates)


def evaluate_pii_text(
    text: str,
    policy: PiiPolicy | ValidatedPiiPolicy,
    *,
    source: str = "",
    phase: str = "ingest",
    egress_mode: bool = False,
    raise_on_block: bool = True,
) -> tuple[str, dict[str, int], dict[str, str], tuple[str, ...]]:
    """Evaluate PII across ``text``, optionally returning block entities before raising."""
    validated = policy if isinstance(policy, ValidatedPiiPolicy) else validate_pii_policy(policy)
    if egress_mode and validated.egress == "allow":
        return text, {}, {}, ()

    kept = _collect_detections(text, validated)
    if not kept:
        return text, {}, {}, ()

    counts: dict[str, int] = {}
    actions: dict[str, str] = {}
    blocked_set: set[str] = set()
    salt_cache: bytes | None = None

    parts: list[str] = []
    cursor = 0
    for det in kept:
        entity = det["entity_type"]
        if egress_mode and validated.egress == "block":
            effective_action = "block"
        else:
            effective_action = validated.types[entity]

        counts[entity] = counts.get(entity, 0) + 1
        # Preserve strictest action if multiple spans target same entity category.
        if actions.get(entity) != "block":
            actions[entity] = effective_action
        if effective_action == "block":
            blocked_set.add(entity)
            continue

        start, end = det["start"], det["end"]
        parts.append(text[cursor:start])
        if effective_action == "redact":
            parts.append(f"[{entity}]")
        else:
            if salt_cache is None:
                salt_cache = resolve_token_salt(validated)
            parts.append(tokenize_value(entity, text[start:end], salt=salt_cache))
        cursor = end

    parts.append(text[cursor:])
    sorted_counts = dict(sorted(counts.items()))
    sorted_actions = dict(sorted(actions.items()))
    blocked_entities = tuple(sorted(blocked_set))

    if blocked_entities and raise_on_block:
        loc = f" in source {source!r}" if source else ""
        raise PiiBlockedError(
            f"Blocked PII entity type(s) {list(blocked_entities)!r}{loc} during {phase}.",
            entity_counts=sorted_counts,
            actions=sorted_actions,
            blocked_entities=blocked_entities,
            source=source,
            phase=phase,
        )

    transformed = text if blocked_entities else "".join(parts)
    return transformed, sorted_counts, sorted_actions, blocked_entities


def apply_pii_policy_to_text(
    text: str,
    policy: PiiPolicy | ValidatedPiiPolicy,
    *,
    source: str = "",
    phase: str = "ingest",
) -> tuple[str, dict[str, int], dict[str, str]]:
    """Apply configured recognizers to ``text``, raising ``PiiBlockedError`` on blocks."""
    transformed, counts, actions, _ = evaluate_pii_text(
        text,
        policy,
        source=source,
        phase=phase,
        egress_mode=(phase == "egress"),
        raise_on_block=True,
    )
    return transformed, counts, actions


__all__ = [
    "PII_RECOGNIZERS",
    "CreditCardRecognizer",
    "EmailAddressRecognizer",
    "EsDniRecognizer",
    "IbanCodeRecognizer",
    "IpAddressRecognizer",
    "PhoneNumberRecognizer",
    "PiiRecognizer",
    "UsSsnRecognizer",
    "ValidatedPiiPolicy",
    "apply_pii_policy_to_text",
    "evaluate_pii_text",
    "register_pii_recognizer",
    "resolve_token_salt",
    "tokenize_value",
    "validate_pii_policy",
]
