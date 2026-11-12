# Test và eval. Chạy từ gốc repo: make -C tests check PY=/abs/path/python
# Package evaluation import code backend nên chạy từ backend/ với thư mục này trên PYTHONPATH.
# Cài đặt: pip install -r tests/requirements-dev.txt -r tests/requirements-eval.txt
PY ?= python
TESTS := $(abspath .)
# Eval tất định không gọi mạng; .env dev bật Langfuse và Jev nên tắt bằng biến môi trường.
SAFE_ENV = JWT_SECRET_KEY=ci-only LANGFUSE_TRACING=false JEV_MODE=off
EVAL = cd ../backend && $(SAFE_ENV) PYTHONPATH=$(TESTS) $(PY) -m evaluation
OUT ?= eval_results/quality

.PHONY: check lint import unit integration cypher-safety \
	eval-agent eval-rag eval-kg eval-jev eval-safety eval-full eval-report eval-ragas eval-alerts

check: lint import unit integration eval-agent eval-safety cypher-safety   ## cổng đầy đủ, không gọi dịch vụ tốn phí

lint:
	cd ../backend && uvx ruff@0.17.4 check . --config agentic/ruff.toml
import:
	cd ../backend && $(SAFE_ENV) $(PY) -c "import agentic.core.app.main, app"
unit:
	$(PY) -m pytest unit
integration:
	@echo "integration: chưa có test tích hợp (L1.2)"
cypher-safety:
	cd ../backend && $(SAFE_ENV) PYTHONPATH=$(TESTS) $(PY) -m evaluation.kg_eval safety --offline

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
	../.venv-ragas/bin/python evaluation/ragas_scoring.py $(FILE) --out $(FILE:.jsonl=-scores.jsonl)
eval-alerts:
	cd ../backend && $(PY) -m agentic.observability.alerts --reports $(OUT) $(ARGS)
