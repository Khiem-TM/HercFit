# Logical evaluation entry points (eval:agent … eval:report). Run from the repository root.
PY ?= python
EVAL = cd backend && $(PY) -m agentic.evaluation
OUT ?= eval_results/quality

.PHONY: eval-agent eval-rag eval-kg eval-jev eval-safety eval-full eval-report eval-ragas eval-alerts

eval-agent:       ## deterministic agent regression on the real graph (MODE=live ARGS=--allow-paid for paid)
	$(EVAL) agent --mode $(or $(MODE),deterministic) --out $(OUT) $(ARGS)
eval-safety:
	$(EVAL) safety --mode $(or $(MODE),deterministic) --out $(OUT) $(ARGS)
eval-rag:         ## retrieval variants (paid embeddings): ARGS="--allow-paid --variants vector bm25 hybrid hybrid_rerank"
	$(EVAL) rag --out $(OUT) $(ARGS)
eval-kg:
	$(EVAL) kg --out $(OUT) $(ARGS)
eval-jev:         ## JEV holdout from reviewed results: ARGS="--import-only <prefix>"
	$(EVAL) jev --split holdout --out $(OUT) $(ARGS)
eval-full:
	$(EVAL) full --out $(OUT) $(ARGS)
eval-report:
	$(EVAL) report --out $(OUT)
eval-ragas:       ## score exported RAG answers in the isolated Ragas env: FILE=<ragas-input.jsonl>
	.venv-ragas/bin/python backend/agentic/evaluation/ragas_scoring.py $(FILE) --out $(FILE:.jsonl=-scores.jsonl)
eval-alerts:
	cd backend && $(PY) -m agentic.observability.alerts --reports $(OUT) $(ARGS)
