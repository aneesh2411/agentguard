# Roadmap

Phase 1 - Measure (this scaffold)
- [x] SDK event model: runs, attempts, LLM calls, tool calls
- [x] Cost computation from a model pricing table
- [x] Ingestion API + SQLite store
- [x] Read-only aggregates: cost per completed task, per workflow, retry waste
- [x] Minimal dashboard UI

Phase 2 - Integrate
- [x] LiteLLM proxy event import
- [ ] Langfuse trace import
- [ ] OpenTelemetry spans

Phase 3 - Warn
- [x] Per-workflow budget thresholds and alerts

Phase 4 - Control
- [x] SDK budget policies: cheaper-model signal, human-approval pause, hard stop
      (in-run guard; alert delivery / remote enforcement still open)
