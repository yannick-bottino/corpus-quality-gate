# Files

- [Configuration and Secrets](configuration-and-secrets.md) - The YAML configuration surface that parameterizes every cqg stage, the rule that no API key is ever stored in plaintext, the difference between the two shipped configurations, and the run fingerprint stamped into every scored document — including what that fingerprint does not cover.
- [Testing and the License Gate](testing-and-license-gate.md) - How cqg verifies itself — the invariants each area of the pytest suite pins, the synthetic-PDF and mock-provider fixtures that keep end-to-end runs hermetic, and the permissive-license dependency constraint enforced by a checkable script.
