# Files

- [The Docling Subprocess Boundary](docling-subprocess.md) - Why cqg's default parser runs out-of-process in page batches — process isolation converts an out-of-memory kill into a detectable return code, per-batch fallback preserves content, and batch size is a tuned RAM/latency tradeoff.
- [Corpus Triage and Document Parsing](document-parsing.md) - How a folder of files becomes ParsedDoc objects — enumeration and classification, the direct extractors for text and office formats, the layered Docling/pdfminer/pdfplumber PDF chain, (cid:NNN) font-mapping failure detection with its re-extraction attempt, and how parse_confidence is computed and penalized.
- [Image Enrichment](image-enrichment.md) - The optional stage that converts a document's images into text before evaluation — cropping each image out of the PDF, describing it with a vision model independent of the judge LLM, and substituting the description into the markdown that is actually scored and ingested.
