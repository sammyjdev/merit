## Validation: issue #4 — PASS
Spec-anchored check: no spec.md for this issue (entered task directly) — fell back to "assertion exists and covers the criterion": 3/3 acceptance criteria matched (retry-then-succeed for build_extractor and build_writer with exact invocation count 3, exhaust-and-reraise for build_judge with exact invocation count 8, existing suite unchanged and green).
Mutation sensor (mandatory): EMPTY_RETURN=KILLED, IDENTITY_RETURN=KILLED, NEGATE_CONDITIONAL=KILLED, DROP_SIDE_EFFECT=N/A: fake runnable bypasses ChatOpenAI (max_retries=4 is a real-client config not exercised by an offline fake; no network-hitting unit test can observe it without contradicting the issue's own no-network-in-unit-tests requirement)
Mutation sensor (extras): 0 injected, 0 killed, 0 survived (Common tier — no extras)
Report: .specs/features/retry-ladder-provider-overload/validation.md
