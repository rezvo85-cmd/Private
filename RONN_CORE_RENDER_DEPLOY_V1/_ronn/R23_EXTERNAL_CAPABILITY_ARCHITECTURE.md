# R23 External Capability Architecture

## Non-negotiable ownership rule

RONN has one decision-making brain: `r23_brain.py`.

External libraries are implementation helpers beneath existing R23-owned interfaces. They may improve parsing, evaluation, or workflow execution, but they must never introduce another router, planner, confidence engine, memory system, research brain, or final-answer owner.

## Capability ownership

| Capability | RONN owner | External helper | Boundary |
| --- | --- | --- | --- |
| Main reasoning / routing | `r23_brain.py` | none | R23 alone chooses model, depth, tools, verification, and final-answer ownership. |
| Documents | `document_engine.py` | Docling | Docling is a parsing backend. The public document API remains `extract_document()`; the existing parser remains a fallback. |
| Evaluation | `r23_eval_lab.py` + existing CI | DeepEval | DeepEval is an evaluation harness only. It is not imported on the production chat path and cannot change routing automatically. |
| Multi-step execution | `r23_task_graph.py` | LangGraph | R23 creates and owns the task graph. LangGraph may execute an already-approved complex workflow; it cannot create/rewrite the R23 plan. |
| Memory | RONN_MEMORY Postgres / project brain | none | No second database or vector store is introduced by this integration. |
| Search / research | `r23_research.py` + existing SearXNG/Reader | none in this change | Do not create a second research pipeline. |\n| Interactive browser execution | `r23_agent_runtime.py` | Browser Use | Browser Use may sequence page-level UI actions only after R23 approves an interactive browser task. It cannot select RONN models, rewrite R23 plans, access RONN memory, change confidence, or own final synthesis. |

## Runtime rules

1. Normal chat never invokes Docling, DeepEval, or LangGraph.
2. Docling loads lazily only when a supported document is uploaded.
3. DeepEval is installed only in the external-evaluation CI job, not in production Core requirements.
4. LangGraph is allowed only for complex R23 task graphs that already require real tools. Simple and medium chat keeps the direct R23 path.
5. Every external integration has a deterministic fallback. If a helper is unavailable, RONN keeps its existing behavior rather than failing the main brain.
6. No external framework may write R23 prompts, select the final model, modify Requirement Contracts, modify confidence scores, or own final synthesis.
7. External-version upgrades are pinned and must pass R23 CI before production.\n8. Browser Use is a task-local executor under R23. Its optional planner and judge layers are disabled; it may select only immediate page actions inside one R23-approved browser task, is hard-capped, and returns evidence only. R23 remains the plan of record and final-answer owner.\n9. Browser Use stays lazy and optional in Core until the Chromium runtime is independently proven on the deployment host; normal chat must not require it. Local file actions, uploads, downloads, PDF saving, arbitrary page JavaScript evaluation, wildcard domain expansion, and Browser Use web search are disabled at the adapter boundary.

## Why these integrations exist

- Docling: improve structure-preserving parsing of documents while keeping one document interface.
- DeepEval: add an independent evaluation framework around RONN's existing benchmark/evaluation system.
- LangGraph: provide durable state-machine execution for the hardest multi-step tool jobs while preserving R23's Task Graph as the plan of record.\n- Browser Use: provide bounded interactive page control for approved browser tasks without becoming a second RONN brain.

This file is the architectural guardrail for future work. If a proposed change violates these ownership boundaries, it should be rejected or redesigned before implementation.
