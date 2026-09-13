# Files

- [Golden Q&A Set Generation](golden-set-generation.md) - The cqg golden subcommand — producing a reference question/answer set for business validation, with a density-driven question count, corpus-wide questions grounded by retrieval over full text, and a coverage fallback that refuses to fabricate an answer.
- [The run Pipeline](run-pipeline.md) - End-to-end orchestration of the cqg run subcommand — the two entry modes (a raw folder parsed on the fly, or a parsed_input/ read back), how each document is sequenced through enrichment, deterministic metrics, screening, sectioned judgment and scoring, the four exit paths, and the corpus artifacts written at the end.
