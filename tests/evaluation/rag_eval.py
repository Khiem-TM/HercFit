"""Retrieval quality of the approved-document RAG search, without any chat model.

Run from backend/ against the development database and the configured embedding provider:
    python -m evaluation.rag_eval retrieval --label baseline --out eval_results/rag
    python -m evaluation.rag_eval retrieval --label full --multi --options '{"min_score": null}'
    python -m evaluation.rag_eval calibrate eval_results/rag/<run>
    python -m evaluation.rag_eval compare eval_results/rag/<run-a> eval_results/rag/<run-b>
    python -m evaluation.rag_eval answer --limit 20   # research model drafts; claim verification rate

Gold labels are physical source page ranges and chapter headings, not chunk ids, so the
same cases stay valid after re-chunking. A retrieved chunk is relevant when its page span
[page, page_end] intersects any expected range.
"""
import argparse
import asyncio
import csv
import inspect
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import text

from core.database import get_db_session, close_crud_db_pool
from agentic.embedding.core import EmbeddingClient, normalize_text, settings as embedding_settings
from agentic.embedding.retrieval.search import SearchRequest, search

CASES = Path(__file__).parent / 'datasets' / 'rag_cases.jsonl'
K = 10


def load_cases(path=CASES):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def span(chunk):
    return chunk['page'], chunk.get('page_end') or chunk['page']


def relevant(chunk, case):
    start, end = span(chunk)
    return any(start <= high and low <= end for low, high in case.get('expected_pages', []))


def ranges_hit(chunks, case):
    return sum(any(span(c)[0] <= high and low <= span(c)[1] for c in chunks) for low, high in case['expected_pages'])


async def available_relevant(session, case):
    """Relevant chunks that exist in the active revisions: the ideal ranking for nDCG."""
    has_end = (await session.execute(text('''SELECT EXISTS(SELECT 1 FROM information_schema.columns
        WHERE table_name='knowledge_chunks' AND column_name='page_end')'''))).scalar_one()
    end = 'COALESCE(c.page_end,c.page)' if has_end else 'c.page'
    count = 0
    for low, high in case['expected_pages']:
        count += (await session.execute(text(f'''SELECT count(*) FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.active_revision=c.revision_id
            WHERE c.page<=:high AND {end}>=:low'''), {'low': low, 'high': high})).scalar_one()
    return count


async def legacy_keyword_hits(session, query):
    """Matches of the original AND full-text query, for the pre-fix baseline only."""
    return (await session.execute(text('''SELECT count(*) FROM knowledge_chunks c
        JOIN knowledge_documents d ON d.active_revision=c.revision_id
        WHERE c.search_vector @@ plainto_tsquery('simple', :q)'''), {'q': normalize_text(query)})).scalar_one()


def metrics(case, chunks, ideal):
    flags = [relevant(c, case) for c in chunks]
    first = next((i for i, flag in enumerate(flags, 1) if flag), None)
    dcg = sum(1 / math.log2(i + 1) for i, flag in enumerate(flags[:5], 1) if flag)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(5, ideal) + 1)) or 1
    return {
        'hit@1': float(any(flags[:1])), 'hit@3': float(any(flags[:3])), 'hit@5': float(any(flags[:5])),
        'recall@5': ranges_hit(chunks[:5], case) / len(case['expected_pages']),
        'mrr@10': 1 / first if first else 0.0, 'ndcg@5': dcg / idcg,
        'chapter@3': float(any(c.get('heading') == case['expected_heading'] for c in chunks[:3])),
    }


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))] if values else None


async def search_once(request, cfg, client, extra):
    started = perf_counter()
    async with get_db_session() as session:
        result = await search(session, request, cfg, client, **extra)
    return result, (perf_counter() - started) * 1000


async def attempt(call, tries=3):
    """A provider network blip retries the case instead of discarding the whole run."""
    for index in range(tries):
        try:
            async with asyncio.timeout(60):
                return await call()
        except (httpx.TransportError, TimeoutError) as exc:
            if index + 1 == tries:
                raise
            print(f'retry after {type(exc).__name__}', flush=True)
            await asyncio.sleep(2 ** index)


async def retrieval(args):
    cfg = embedding_settings()
    client = EmbeddingClient(cfg)
    extra = {}
    parameters = inspect.signature(search).parameters
    if 'options' in parameters:
        from agentic.embedding.retrieval.search import SearchOptions
        extra['options'] = SearchOptions(**{'debug': True, **json.loads(args.options or '{}')})
    if 'reranker' in parameters and args.rerank:
        from agentic.embedding.core import RerankClient
        extra['reranker'] = RerankClient(cfg)
    cases = load_cases(args.cases)
    out = Path(args.out) / f'{datetime.now():%Y%m%d-%H%M%S}-{args.label}'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for case in cases:
            body = {'query': case['query'], 'limit': K}
            if args.multi and case.get('queries') and 'queries' in SearchRequest.model_fields:
                body['queries'] = case['queries']
            result, elapsed = await attempt(lambda: search_once(SearchRequest(**body), cfg, client, extra))
            chunks = result['chunks']
            diagnostics = result.get('diagnostics') or {}
            async with get_db_session() as session:
                ideal = await available_relevant(session, case) if case['kind'] == 'in_domain' else 0
                keyword = diagnostics.get('keyword_hits')
                if keyword is None:
                    keyword = await legacy_keyword_hits(session, case['query'])
            row = {'id': case['id'], 'kind': case['kind'], 'lang': case['lang'], 'status': result.get('status'),
                   'returned': len(chunks), 'top_score': diagnostics.get('top_score'),
                   'top_similarity': diagnostics.get('top_similarity'), 'keyword_hits': keyword,
                   'rerank': result.get('rerank'), 'latency_ms': round(elapsed, 1),
                   'pages': ' '.join('%d-%d' % span(c) for c in chunks)}
            if case['kind'] == 'in_domain':
                row.update(metrics(case, chunks, ideal))
            rows.append(row)
            print(json.dumps({k: row[k] for k in ('id', 'status', 'returned', 'latency_ms')} | {k: row.get(k) for k in ('hit@3', 'mrr@10')}), flush=True)
    finally:
        await client.close()
        if 'reranker' in extra:
            await extra['reranker'].close()
        await close_crud_db_pool()
    summary = summarize(rows, args)
    with open(out / 'cases.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (out / 'summary.md').write_text(markdown([summary]))
    print(markdown([summary]))
    print('Saved', out)


def summarize(rows, args):
    inside = [r for r in rows if r['kind'] == 'in_domain']
    outside = [r for r in rows if r['kind'] == 'out_of_domain']
    mean = lambda items, key: round(statistics.mean(r[key] for r in items), 3) if items else None
    english = [r for r in rows if r['lang'] == 'en']
    summary = {'label': args.label, 'multi': bool(args.multi), 'options': json.loads(args.options or '{}'),
               'cases': len(rows), 'in_domain': len(inside), 'out_of_domain': len(outside)}
    for key in ('hit@1', 'hit@3', 'hit@5', 'recall@5', 'mrr@10', 'ndcg@5', 'chapter@3'):
        summary[key] = mean(inside, key)
        for lang in ('vi', 'en'):
            summary[f'{key}_{lang}'] = mean([r for r in inside if r['lang'] == lang], key)
    summary['keyword_nonempty_en'] = round(sum(1 for r in english if r['keyword_hits']) / len(english), 3) if english else None
    summary['keyword_nonempty_all'] = round(sum(1 for r in rows if r['keyword_hits']) / len(rows), 3)
    summary['ood_accepted'] = round(sum(1 for r in outside if r['returned']) / len(outside), 3) if outside else None
    summary['in_domain_rejected'] = round(sum(1 for r in inside if not r['returned']) / len(inside), 3) if inside else None
    latencies = [r['latency_ms'] for r in rows]
    summary['latency_p50_ms'] = percentile(latencies, .5)
    summary['latency_p95_ms'] = percentile(latencies, .95)
    return summary


COLUMNS = [('label', 'Cấu hình'), ('hit@1', 'Hit@1'), ('hit@3', 'Hit@3'), ('hit@5', 'Hit@5'), ('recall@5', 'Recall@5'),
           ('mrr@10', 'MRR@10'), ('ndcg@5', 'nDCG@5'), ('chapter@3', 'Chương@3'), ('hit@3_vi', 'Hit@3 VI'),
           ('hit@3_en', 'Hit@3 EN'), ('keyword_nonempty_en', 'Keyword EN có KQ'), ('ood_accepted', 'OOD bị nhận'),
           ('in_domain_rejected', 'In-domain bị từ chối'), ('latency_p50_ms', 'p50 ms'), ('latency_p95_ms', 'p95 ms')]


def markdown(summaries):
    lines = ['| ' + ' | '.join(title for _, title in COLUMNS) + ' |', '|' + '---|' * len(COLUMNS)]
    for summary in summaries:
        lines.append('| ' + ' | '.join(str(summary.get(key, '')) for key, _ in COLUMNS) + ' |')
    return '\n'.join(lines) + '\n'


def compare(args):
    print(markdown([json.loads((Path(run) / 'summary.json').read_text()) for run in args.runs]))


def calibrate(args):
    """Largest in-domain acceptance with out-of-domain false acceptance at or below the budget."""
    rows = list(csv.DictReader(open(Path(args.run) / 'cases.csv')))
    key = args.score
    scored = [(r['kind'], float(r[key])) for r in rows if r.get(key) not in (None, '')]
    if not scored:
        raise SystemExit(f'No {key} values; run retrieval with options {{"min_score": null}} first')
    inside = [s for kind, s in scored if kind == 'in_domain']
    outside = [s for kind, s in scored if kind == 'out_of_domain']
    best = None
    for threshold in sorted({s for _, s in scored}):
        false_accept = sum(s >= threshold for s in outside) / len(outside)
        accept = sum(s >= threshold for s in inside) / len(inside)
        if false_accept <= args.max_false_accept and (best is None or accept > best[1]):
            best = (threshold, accept, false_accept)
    recall = None
    if max(outside) < min(inside):
        # Separable. The gold questions are clean knowledge questions; advice and planning queries
        # score lower against the same books, so the recall-leaning point sits near the out-of-domain
        # edge (a false accept is still judged by the draft; a false reject loses the book evidence).
        gap = min(inside) - max(outside)
        best = (max(outside) + gap / 2, 1.0, 0.0)
        recall = round(max(outside) + gap / 6, 4)
    print(json.dumps({'score': key, 'separable': max(outside) < min(inside), 'threshold_recall_leaning': recall,
                      'in_domain_scores': [min(inside), statistics.median(inside), max(inside)],
                      'out_of_domain_scores': [min(outside), statistics.median(outside), max(outside)],
                      'threshold': best and round(best[0], 4), 'in_domain_accept': best and round(best[1], 3),
                      'ood_false_accept': best and round(best[2], 3)}, indent=2))


async def answer(args):
    """Draft answers from retrieved passages with the research model and count claims the
    deterministic quote check drops, by reason. Calls the configured research model."""
    from collections import Counter
    from agentic.core.app.config import agent_settings
    from agentic.core.llm import Models
    from agentic.agents import research_agent
    from agentic.security.output_validation import check_claims

    async def unbudgeted(*_args, **_kwargs):
        return None  # budgets live in the agent database; an offline measurement charges no run
    research_agent.reserve = unbudgeted
    agent = research_agent.ResearchV2(Models(agent_settings), None, None, agent_settings)
    cfg = embedding_settings()
    client = EmbeddingClient(cfg)
    reranker = None
    if cfg.RERANK_ENABLED or args.rerank:
        from agentic.embedding.core import RerankClient
        reranker = RerankClient(cfg)
    cases = [c for c in load_cases(args.cases) if c['kind'] == 'in_domain'][:args.limit]
    reasons, rows = Counter(), []
    try:
        for case in cases:
            request = SearchRequest(query=case['query'], queries=case.get('queries', []), limit=4)
            result, _ = await attempt(lambda: search_once(request, cfg, client, {'reranker': reranker} if reranker else {}))
            documents = {'kb:' + c['id']: {**c, 'url': c.get('source_url') or '', 'source_id': 'kb:' + c['id']} for c in result['chunks']}
            work = {'qa': True, 'documents': documents, 'plan': {'target': case['query'], 'intent': 'SPORTS_KNOWLEDGE_QA'}}
            draft = await agent.draft({'run_id': 'rag-eval', 'decision': {'domain': None}}, work)
            checked, dropped = check_claims(draft.claims, work['documents'])
            reasons.update(reason for _, reason in dropped)
            rows.append({'id': case['id'], 'claims': len(draft.claims), 'verified': len(checked),
                         'dropped': len(dropped), 'sufficient': draft.sufficient})
            print(json.dumps(rows[-1]), flush=True)
    finally:
        await client.close()
        if reranker:
            await reranker.close()
        await close_crud_db_pool()
    claims = sum(r['claims'] for r in rows)
    print(json.dumps({'cases': len(rows), 'claims': claims, 'verified': sum(r['verified'] for r in rows),
                      'dropped': dict(reasons), 'drop_rate': round(sum(reasons.values()) / claims, 3) if claims else None,
                      'sufficient_drafts': sum(r['sufficient'] for r in rows)}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('retrieval')
    run.add_argument('--label', required=True)
    run.add_argument('--out', default='eval_results/rag')
    run.add_argument('--cases', default=str(CASES))
    run.add_argument('--multi', action='store_true', help='Send each case\'s English variant as queries')
    run.add_argument('--rerank', action='store_true', help='Pass the configured rerank client')
    run.add_argument('--options', help='JSON SearchOptions overrides')
    cal = sub.add_parser('calibrate')
    cal.add_argument('run')
    cal.add_argument('--score', default='top_score', choices=['top_score', 'top_similarity'])
    cal.add_argument('--max-false-accept', type=float, default=.10)
    cmp = sub.add_parser('compare')
    cmp.add_argument('runs', nargs='+')
    ans = sub.add_parser('answer')
    ans.add_argument('--cases', default=str(CASES))
    ans.add_argument('--limit', type=int, default=20)
    ans.add_argument('--rerank', action='store_true')
    args = parser.parse_args()
    if args.command == 'retrieval':
        asyncio.run(retrieval(args))
    elif args.command == 'answer':
        asyncio.run(answer(args))
    elif args.command == 'calibrate':
        calibrate(args)
    else:
        compare(args)


if __name__ == '__main__':
    main()
