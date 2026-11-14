# Retrieval Evaluation Baseline Report

Committed offline reference baselines for `docpipe-maestro` comparing default semantic vector search (`searcher="default"`) against hybrid lexical + dense Reciprocal Rank Fusion (`searcher="fts5_hybrid"`).

> **Machine-Readable Artifact**: [docs/eval-baseline.json](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/docs/eval-baseline.json) (`schema_version = 1`)  
> **Curated Query Fixture**: [tests/fixtures/eval_policy_corpus.json](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/tests/fixtures/eval_policy_corpus.json) (`24` verified queries)

---

## 1. Benchmark Corpus Composition

- **Collection**: `eval_policy` (`profile = "POLICY"`, `embed_model = "ollama/nomic-embed-text"`)
- **Embedding Mode**: `offline_deterministic` (64-D L2-normalized deterministic bag-of-words embeddings matching `mock_litellm_offline`)
- **Indexed Documents**: `5` Markdown policy documents (`21` child chunks, `21` parent sections):
  - `tests/fixtures/policy_corpus/hr_leave_policy.md` (`4` parent sections — preserved unmodified)
  - `tests/fixtures/policy_corpus/travel_expenses_policy.md` (`2` parent sections — preserved unmodified)
  - `tests/fixtures/eval_corpus/information_security_policy.md` (`5` parent sections)
  - `tests/fixtures/eval_corpus/incident_response_runbook.md` (`5` parent sections)
  - `tests/fixtures/eval_corpus/procurement_vendor_policy.md` (`5` parent sections)
- **Query Breakdown (`24` queries)**:
  - `direct_lookup` (`6` queries)
  - `paraphrased` (`6` queries)
  - `exact_identifier` (`6` queries)
  - `rule_and_exception` (`6` queries, targeting complete enclosing parent sections)

---

## 2. Side-by-Side Aggregate Comparison (`K = 1, 3, 5, 10`)

| Metric | `default` (Dense) | `fts5_hybrid` (BM25 + Dense RRF) | Delta (`fts5_hybrid - default`) |
| --- | ---: | ---: | ---: |
| **MRR** | `0.7303` | `0.9005` | `+0.1701` |
| **Precision@1** | `0.6250` | `0.8333` | `+0.2083` |
| **Precision@3** | `0.2778` | `0.3333` | `+0.0556` |
| **Precision@5** | `0.1750` | `0.2000` | `+0.0250` |
| **Precision@10** | `0.1000` | `0.1042` | `+0.0042` |
| **Recall@1** | `0.6042` | `0.8125` | `+0.2083` |
| **Recall@3** | `0.8125` | `0.9583` | `+0.1458` |
| **Recall@5** | `0.8542` | `0.9583` | `+0.1042` |
| **Recall@10** | `0.9583` | `1.0000` | `+0.0417` |

---

## 3. Query-Category Breakdown (Offline Baseline)

| Category (`n = 6` each) | `default` MRR | `fts5_hybrid` MRR | `default` Recall@3 | `fts5_hybrid` Recall@3 |
| --- | ---: | ---: | ---: | ---: |
| `direct_lookup` | `0.9167` | `1.0000` | `1.0000` | `1.0000` |
| `paraphrased` | `0.3241` | `0.6852` | `0.5000` | `0.8333` |
| `exact_identifier` | `0.8056` | `1.0000` | `1.0000` | `1.0000` |
| `rule_and_exception` | `0.8750` | `0.9167` | `0.7500` | `1.0000` |

Key observations:
- Exact control and playbook identifiers (`SEC-101`, `PAM-08`, `BREAKGLASS-99`, `IR-RB-012`, `PROC-204`, `EMERG-PO-09`) reach `1.0000` MRR and `P@1 = 1.0000` under `fts5_hybrid` (`+0.1944` MRR over `default`).
- Exception-bearing policy queries (`rule_and_exception`) achieve `1.0000` Recall@3 (`+0.2500` over `default`) while returning complete parent sections.
- Remaining MRR gap (`0.9005` overall; `0.6852` on `paraphrased`) provides objective baseline headroom for subsequent reranking stages.

---

## 4. Reproduction Steps

### Automated Offline Verification (CI / Zero Network)

```bash
uv run pytest tests/test_eval.py -k "curated_policy_suite" -v
```

### Local Live-Model CLI Benchmark (Optional Ollama)

```bash
uv run docpipe-maestro ingest tests/fixtures/policy_corpus --profile POLICY --collection eval_policy
uv run docpipe-maestro ingest tests/fixtures/eval_corpus --profile POLICY --collection eval_policy

uv run docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json --searcher default --json
uv run docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json --searcher fts5_hybrid
```
