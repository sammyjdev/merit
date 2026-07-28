# Cross-review request: PR #5

- repo: sammyjdev/merit
- pr: https://github.com/sammyjdev/merit/pull/5
- issue: #4 - Retry ladder for provider overload (DeepInfra engine_overloaded 429)
- tier: Common
- risk areas hit: none
- gate: pytest -q -p no:cacheprovider -> 43 passed, 1 deselected; ruff check merit tests -> All checks passed!
- reviewers already run: subagent maker (Claude, Common-tier fallback after routed maker was network-unreachable) + spec-compliance reviewer (Haiku 4.5, verdict PASS) + Quench mutation sensor (gpt-5.6-sol via codex exec, mandatory battery: EMPTY_RETURN=KILLED, IDENTITY_RETURN=KILLED, NEGATE_CONDITIONAL=KILLED, DROP_SIDE_EFFECT=N/A)
- quench: 3 mutations injected, 3 killed, 0 survived, 1 valid N/A (DROP_SIDE_EFFECT: max_retries=4 is real-client config the offline fake runnable cannot exercise without violating the issue's no-network-in-unit-tests requirement)

## What the maker was asked to do

In `merit/models.py`: make every built runnable rate-limit resilient, idiomatically:

- Wrap `build_extractor()`, `build_judge()`, and `build_writer()` outputs with LangChain's `.with_retry(retry_if_exception_type=(openai.RateLimitError,), wait_exponential_jitter=True, stop_after_attempt=8)`.
- Raise the underlying client's `max_retries` via `ChatOpenAI(..., max_retries=4)` so short blips never even reach the tenacity layer.
- No new dependencies (tenacity ships with langchain-core).

Tests (offline, TDD): a fake runnable that raises `RateLimitError` twice then succeeds (assert 3 invocations); a fake that always raises (assert exhaustion and re-raise). Existing suite stays green; no network in unit tests. Do not change the env contract (MERIT_MODEL / MERIT_API_BASE / MERIT_API_KEY) or any node/graph code.

## What to look for

Findings the same-family reviewers would be least likely to catch. Do not re-litigate style or re-run the gate - both already passed. Prefer:
- correctness under inputs the tests do not generate (e.g. `.with_retry()`'s interaction with `.with_structured_output()`'s own error surface - does a malformed structured-output response ever masquerade as a retryable error, or vice versa?)
- whether `wait_exponential_jitter=True` with `stop_after_attempt=8` and DeepInfra's actual overload windows (minutes-long, per the issue) leaves enough total wait budget, or converges too fast/slow given LangChain's default base delay
- assumptions the diff makes about the environment: does `max_retries=4` on the underlying `ChatOpenAI` client double-count against the outer `.with_retry()`'s own attempt budget in a way that multiplies total wait time beyond what either config alone implies?
