# Roadmap

Phase 1 - Measure (this scaffold)
- [x] SDK event model: runs, attempts, LLM calls, tool calls
- [x] Cost computation from a model pricing table
- [x] Ingestion API + SQLite store
- [ ] Read-only aggregates: cost per completed task, per workflow, retry waste
- [ ] Minimal dashboard UI

Phase 2 - Integrate
- [ ] LiteLLM proxy event import
- [ ] Langfuse trace import
- [ ] OpenTelemetry spans

Phase 3 - Warn
- [ ] Per-workflow budget thresholds and alerts

Phase 4 - Control
- [ ] Fallback policies: cheaper model, human approval, hard stop
