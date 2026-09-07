# Team Meeting Notes — Retrieval Platform

## 2026-09-01 Weekly Sync

Attendees: Wei Zhang, Li Chen, Maria Rodriguez.

Agenda and decisions:

- The hybrid retrieval A/B test reached statistical significance: hybrid
  Recall@5 improved from 0.71 to 0.79 against the dense-only baseline.
- Embedding model upgrade to BAAI/bge-m3 is approved for the next release.
- Maria will own the frontend management console rewrite (React + antd).

Action items:

1. Wei: publish the new eval dataset for format expansion (due 2026-09-05).
2. Li: benchmark reranker latency on CPU instances (due 2026-09-08).

## 2026-08-25 Architecture Review

We reviewed the multi-domain retrieval design (knowledge scopes). Key
decisions:

- Every retrieval request must carry an explicit scope reference; implicit
  whole-library search is forbidden.
- Domain differences (supported formats, graph vocabularies) are expressed
  declaratively through domain profiles instead of code paths.

## 2026-08-18 Onboarding Notes

New team members should read the constitution first, then the 1.0
architecture blueprint. The evaluation README in eval/ describes how to
rerun every baseline report.
