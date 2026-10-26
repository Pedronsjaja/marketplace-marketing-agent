# Model routing

DETERMINISTIC-FIRST → LOCAL-FIRST → CACHE-FIRST → SMALL-MODEL-FIRST → PREMIUM-AS-FALLBACK.

| Level | Execution | Current availability |
|---|---|---|
| 0 | Python: validate, state, metrics, IDs, files, CSV/JSON, duplicates, sort/cache | Implemented operations; route returns 0 |
| 1 | Local or inexpensive model | Contract only |
| 2 | Economical cloud model | Contract only; allow_cloud required |
| 3 | Premium model | Contract only; allow_cloud and allow_premium required |

route() is a pure decision function. For qualitative tasks it chooses the lowest available permitted level not listed as failed. It does not call providers, verify model quality, perform retries or infer escalation need. The caller must supply availability and evidence of failure; when none is permitted the result is null. A caller may offer only a cloud tier, but cloud still requires authorization.

Available task types are explicit. An unknown task or model level is rejected rather than silently dispatched. Cache keys include task, input payload and prompt version. Future response caches must additionally include provider/model, parameters, evidence freshness and policy; they must not reuse an unreviewed answer as a verified fact.

## Adding a provider
Implement Provider.generate(prompt, model=...) -> GenerationResult. Optional usage fields remain null when unknown. Put credential access in the adapter, never prompts, samples or logs. Keep network timeouts, rate-limit behavior, budget/consent checks and errors explicit. Test with a fake provider before a real call.
Potential future adapters: OpenAI, Anthropic, Gemini, Ollama, OpenRouter and OpenAI-compatible APIs. Listing them here does not mean support is implemented. No API key or SDK is needed to run the current project.

config/providers.example.json is an interface planning artifact, not executable provider setup. Credentials are neither read nor used by v0.1.

## Future benchmarking
Use [tasks.sample.json](../benchmarks/tasks.sample.json) and [result.example.json](../benchmarks/result.example.json). Keep fixed tasks/rubrics, model/version/settings, prompt version and source hashes. Record quality, latency, input/output tokens, cost/currency, success, retries and tool calls. Unknown is null; a no-call baseline may record zero usage only after measuring that execution.
No benchmark ran and no token/cost savings are claimed.
