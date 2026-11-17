# Quickstart Validation: Additional Document Formats (`014-additional-intake-formats`)

**Feature Branch**: `014-additional-intake-formats` | **Date**: 2026-11-17  
**Contracts**: [intake-formats.md](./contracts/intake-formats.md) | **Data Model**: [data-model.md](./data-model.md)

---

## Scenario 1: Core-Only Delimited Intake (`.csv` & `.tsv`, Zero Optional Extras)

Verify built-in CSV/TSV parsing works without optional parser packages installed and leaves optional dependencies unloaded:

```bash
uv run --no-sync python -c '
import sys, tempfile
from pathlib import Path
from unittest.mock import patch
import docpipe_maestro as dp

assert len(dp.__all__) == 36
for mod in ("openpyxl", "pptx", "ebooklib", "docutils"):
    assert mod not in sys.modules, f"{mod} eagerly loaded"

with tempfile.TemporaryDirectory() as tmp:
    corpus = Path(tmp) / "corpus"
    persist = Path(tmp) / ".docpipe"
    corpus.mkdir()
    (corpus / "leave.csv").write_text("Role,Days,Exception\nFull-Time,20,Except 90-day probation\n", encoding="utf-8-sig")
    (corpus / "travel.tsv").write_text("Item\tLimit\tRule\nHotel\t$250\tUnless VP approved\n", encoding="utf-8")

    with patch("litellm.embedding", side_effect=lambda input, **kw: {"data": [{"index": i, "embedding": [0.1, 0.2, 0.3, 0.4]} for i, _ in enumerate(input)]}):
        res = dp.ingest(corpus, profile="POLICY", collection="csv_tsv_smoke", persist_dir=persist)
        assert sorted(res.ingested) == ["leave.csv", "travel.tsv"]
        hits = dp.retrieve("Full-Time probation", collection="csv_tsv_smoke", persist_dir=persist)
        assert hits and "Except 90-day probation" in hits[0].text
print("CORE_CSV_TSV_OK")
'
```

---

## Scenario 2: Fail-Loud Missing-Extra Guards & Rich Optional Formats

Verify `.xlsx`, `.pptx`, `.epub`, and `.rst`:
1. Raise `MissingExtraError` (naming `[xlsx]`, `[pptx]`, `[epub]`, `[rst]`) before any vector-store write when uninstalled/shadowed (`tests/test_api_stability.py` / `tests/test_intake_formats_optional.py`).
2. Extract structured sheet/row, slide/notes, spine chapter, and heading hierarchy cleanly once extras (`uv sync --locked --all-extras --group dev`) are installed, while skipping hidden Excel sheets and hidden EPUB HTML blocks (`data-model.md` §2).

---

## Scenario 3: Container, Encoding & Inclusion Safety Gates

Verify negative safety paths cleanly fail with `UnsupportedFormatError` and zero store/filesystem side effects:
- Oversized (`> 256 MiB`) or corrupt `.xlsx`/`.pptx`/`.epub` containers and generic extensionless ZIPs.
- Legacy binary `.xls`/`.ppt` signatures.
- Invalid non-UTF-8 (e.g., Windows-1252 or NUL-byte) `.csv`/`.tsv` inputs.
- `.rst` files attempting `.. include:: /etc/passwd` or `.. raw::`.

---

## Scenario 4: Full Quality, Lockfile & Safety Suites (Laptop-Safe Caps)

```bash
systemd-run --user --scope --quiet \
  -p CPUQuota=300% -p MemoryHigh=700M -p MemoryMax=950M -p MemorySwapMax=0 -p TasksMax=64 \
  nice -n 15 ionice -c 3 env LITELLM_LOCAL_MODEL_COST_MAP=true \
  uv lock --check \
  && uv run --no-sync ruff format --check . \
  && uv run --no-sync ruff check . \
  && uv run --no-sync ruff check --select S src/ \
  && uv run --no-sync mypy src tests \
  && uv run --no-sync pytest -m reverse -v \
  && uv run --no-sync pytest -m pii -v \
  && uv run --no-sync pytest -v --cov
```
