"""Bounded reusable research graph; no node has access to write tools."""
from agentic.components.hybrid_retriever import retrieve_knowledge
from agentic.components.context_filter import bounded_documents
from agentic.security.output_validation import parse_draft, check_claims, verify_claims, verified_claims, related_claims
from agentic.security.input_guard import ClinicalQuestion, clinical_topic, safe_query
from agentic.components.reranker import NUTRITION_FIELDS, relevance, target_words, topical, rank_sources
from agentic.prompts.registry import get_questions
from agentic.prompts.registry import get_prompt
from agentic.observability import annotate
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from agentic.services import catalog_choice
from agentic.services.illustrations import find_illustrations
from agentic.core.context import request_context
from agentic.agents.state import AgentState
from agentic.tools.integrations.tavily import TavilyUnavailable, public_url
from agentic.services.research_budget import research_lease, reserve, reserve_documents, BudgetExceeded
from agentic.research.contracts import ResearchPlan, ResearchDraft, ResearchResult, ResearchStatus, QA_INTENTS
from agentic.research.evidence import audit
from agentic.research.sources import quality_gate, rate, social
from schemas.foods import FoodCreate
from schemas.exercises import ExerciseCreate
from models.foods import normalize_food_text

PROMPT = get_prompt('research.extract')


def findings(claims,documents,heading):
    """Bulleted claims with numbered references, one per source."""
    references={}; lines=[]
    for claim in claims[:8]:
        source=documents[claim.source_id]
        if claim.source_id not in references:
            label=source.get('title') or 'Tài liệu'
            where=source.get('url') or f"revision {source.get('version','?')}, trang {source.get('page','?')}"
            references[claim.source_id]=(len(references)+1,f'{label} — {where}')
        note=(' (các nguồn chưa thống nhất)' if claim.conflict else
              '' if claim.applicable else ' (không khớp hoàn toàn với yêu cầu)')
        lines.append(f'- {claim.claim}{note} [{references[claim.source_id][0]}]')
    return [heading,*lines,'','Nguồn:',*[f'[{i}] {ref}' for i,ref in references.values()]]


def consulted(documents,limit=4):
    rows=[d for d in documents.values() if public_url(d.get('url',''))][:limit]
    return ['Đã xem:',*[f'- {d.get("title") or d["url"]} — {d["url"]}' for d in rows]] if rows else []


def partial_answer(target,claims,documents,weak=False):
    """What the sources say when they do not settle a knowledge question; never a guess of our own."""
    if not claims:
        return '\n'.join([f'Mình đã xem {len(documents)} nguồn trên web nhưng không thấy thông tin đủ tin cậy về "{target}".',
                          '',*consulted(documents)]).strip()
    caveat=('Các nguồn này chưa đủ tin cậy hoặc chưa đủ căn cứ, nên đây chỉ là thông tin tham khảo.' if weak else
            'Đây là thông tin tham khảo, chưa đủ căn cứ để trả lời chắc chắn.')
    return '\n'.join([f'Mình chưa tìm được câu trả lời chắc chắn cho "{target}". {caveat}','',
                      *findings(claims,documents,'Các nguồn trên web có nói:')])


def catalog_followup(domain,target,claims,documents,product):
    """(reply, form, estimate choice) after catalog research could not build a savable record."""
    searched=f'Mình đã tìm {len(documents)} nguồn trên web cho "{target}"'
    # Only facts the record needs, about the item itself ("it is a drink of avocado and coconut", or the
    # calories of one ingredient, do not help logging it); food facts are numbers.
    claims=[c for c in claims if relevance(target,c.quote)>=.5 and not catalog_choice.QUESTION.search(normalize_food_text(c.quote)) and (
        c.field in NUTRITION_FIELDS and re.search(r'\d',c.quote) if domain=='foods' else c.field.startswith(('configuration','muscle')))]
    if domain=='foods':
        clarification,choice=catalog_choice.estimate_form(target,claims,documents,product)
        if choice:
            reply=[f'{searched} nhưng chưa có bảng dinh dưỡng chính thức đủ căn cứ để lưu vào catalog.','',
                   *findings(claims,documents,'Các ước tính tìm được:')]
            return '\n'.join(reply),clarification,choice
        reply=[f'{searched} nhưng không thấy số liệu dinh dưỡng đủ căn cứ.','',
               *(findings(claims,documents,'Các nguồn có nói:') if claims else consulted(documents))]
        return '\n'.join(reply).strip(),clarification,None
    reply=[f'{searched} nhưng chưa đủ căn cứ để lưu bài tập vào catalog.','',
           *(findings(claims,documents,'Các nguồn có nói:') if claims else consulted(documents))]
    return '\n'.join(reply).strip(),catalog_choice.manual_form(domain,target),None


class ResearchV2:
    def __init__(self,models,tavily,store,settings,jev=None):
        self.models,self.tavily,self.store,self.settings=models,tavily,store,settings
        self.jev=jev
        def observed(fn,name):
            async def call(state):
                from agentic.observability.node_span import span
                with span(getattr(settings,'LANGSMITH_ENABLED',False),name,state['run_id']):
                    return await fn(state)
            return call
        graph=StateGraph(AgentState)
        graph.add_node('research_plan',observed(self.plan,'research_plan'))
        graph.add_node('research_gather',observed(self.gather,'research_gather'))
        graph.add_node('research_synthesize',observed(self.synthesize,'research_synthesize'))
        graph.add_node('research_validate',observed(self.validate,'research_validate'))
        graph.add_edge(START,'research_plan')
        # Similar catalog records end the round with a choice instead of spending web budget.
        graph.add_conditional_edges('research_plan',lambda s:END if s['research_work'].get('choice') else 'research_gather',
                                    {END:END,'research_gather':'research_gather'})
        graph.add_edge('research_gather','research_synthesize'); graph.add_edge('research_synthesize','research_validate')
        graph.add_edge('research_validate',END)
        self.graph=graph.compile()

    async def invoke(self,state):
        try:
            if state.get('tool_count',0)>=self.settings.MAX_TOOL_CALLS:
                raise BudgetExceeded('Tool limit')
            async with research_lease(self.store,state):
                await reserve(self.store,state['run_id'],'rounds')
                timeout=60  # Runtime's enclosing timeout also cancels this subgraph.
                async with asyncio.timeout(timeout):
                    result=await self.graph.ainvoke(state)
                async with self.store.pool.connection() as conn:
                    usage=await (await conn.execute('SELECT web,search,llm,rounds FROM agent_research_budgets WHERE run_id=%s',(state['run_id'],))).fetchone()
                result['research_usage']=dict(usage)
                annotate(research=True, research_mode='v2', research_web_calls=usage['web'], research_search_calls=usage['search'], research_llm_calls=usage['llm'], research_rounds=usage['rounds'])
            keys=('research_usage','research_work','research_result','research_answer','research_trace','candidate','sources','illustrations',
                  'status','error','jev_events','jev_rejections','clarification','catalog_choice','tool_outputs','prepared_reply')
            return {**{k:result[k] for k in keys if k in result},'research_count':state.get('research_count',0)+1}
        except Exception as exc:
            # The user can still answer: budget, invalid topic or no web provider; anything else failed.
            asks=isinstance(exc,(BudgetExceeded,ValueError,TavilyUnavailable))
            annotate(error_code=type(exc).__name__, budget_exceeded=isinstance(exc, BudgetExceeded), status='needs_input' if asks else 'failed')
            status=ResearchStatus.NEEDS_USER_INPUT if asks else ResearchStatus.FAILED
            if isinstance(exc,ClinicalQuestion):
                error='Câu hỏi liên quan chấn thương hoặc y khoa cần được chuyên gia đánh giá. HercFit chưa đủ căn cứ để đề xuất điều trị hoặc phác đồ phục hồi.'
            elif isinstance(exc,TavilyUnavailable):
                error='Chưa cấu hình tìm kiếm web; hãy cung cấp thông tin dinh dưỡng hoặc bài tập kèm nguồn.'
            else:
                error='Nghiên cứu chưa hoàn tất ('+type(exc).__name__+'). Không có dữ liệu được ghi.'
            return {'research_count':state.get('research_count',0)+1,
                    'research_result':ResearchResult(status=status,error_code=type(exc).__name__).model_dump(mode='json'),
                    'status':'needs_input' if asks else 'failed','error':error}

    async def evaluate(self,state,phase,projection,questions):
        """Jev is advisory evidence validation, never a source or a writer."""
        if self.jev is None:
            return {'status':'unknown','enforced':False,'mode':'off','reason':'disabled'}, list(state.get('jev_events',[]))
        result=await self.jev.evaluate(state,phase=phase,projection=projection,questions=questions)
        # Metadata only: no draft, source passages, identifiers or question text.
        event={'phase':phase,**{k:result[k] for k in ('status','mode','enforced','reason','model','usage','cost','duration_ms','cached','fingerprint') if k in result}}
        event['answers']=result.get('answers',{})
        return result,[*state.get('jev_events',[]),event]

    @staticmethod
    def probability(result,name):
        value=result.get('answers',{}).get(name,{}).get('noul')
        return value if result.get('status')=='ok' and isinstance(value,(float,int)) and not isinstance(value,bool) and 0<=value<=1 else None

    @staticmethod
    def evidence_projection(work):
        # Pass only public evidence, retaining the exact passages used for synthesis.
        return [{k:v for k,v in source.items() if k in {'source_id','title','url','content','version','page','published_at'}}
                for source in work['documents'].values()]

    async def plan(self,state):
        ctx=request_context.get(); d=state['decision']
        query=safe_query(d.get('research_query') or '',ctx.private_values)
        qa=d.get('intent') in QA_INTENTS
        if qa and clinical_topic(query):
            raise ClinicalQuestion('Clinical question requires professional evaluation')
        domain=d.get('domain')
        if not qa and domain not in {'foods','exercises'}: raise ValueError('Invalid research domain')
        queries=[safe_query(q,ctx.private_values) for q in (d.get('research_queries') or [query])][:3]
        distinct=bool(d.get('create_distinct')) and not qa
        lookup=None
        if not qa:
            lookup=await ctx.backend.call('resolve_'+domain,{'query':query},ctx.token)
        plan=ResearchPlan(intent=d['intent'],target=query,queries=queries,confirmation_required=not qa,
                          output_schema='claims' if qa else domain,
                          preferred_sources=['approved_knowledge','professional_organizations'] if qa or domain=='exercises' else ['manufacturer_label','nutrition_database'],
                          required_fields=[] if qa else [k for k,v in (FoodCreate if domain=='foods' else ExerciseCreate).model_fields.items() if v.is_required()],
                          distinct_from=[m['name_vi'] for m in lookup['matches'][:5]] if distinct else [])
        work={'plan':plan.model_dump(),'qa':qa,'documents':{},'lookup':lookup,'distinct':distinct}
        update={'research_work':work,'research_answer':None}
        if lookup and lookup['status']!='MISSING' and not distinct:
            # Database-first: the user picks an existing record or confirms a new variant before any web call.
            clarification,choice=catalog_choice.form(domain,query,{'query':lookup,'name':None})
            work['choice']=True
            noun='món' if domain=='foods' else 'bài tập'
            update.update(status='needs_input',clarification=clarification,catalog_choice=choice,
                          prepared_reply=f'Catalog đã có {noun} giống hoặc gần giống "{query}". Bạn chọn dùng bản có sẵn hoặc tạo {noun} mới bên dưới.',
                          research_result=ResearchResult(status=ResearchStatus.NEEDS_USER_INPUT).model_dump(mode='json'),
                          error=f'Catalog đã có bản ghi giống hoặc gần giống "{query}"; cần người dùng chọn dùng bản có sẵn hay tạo biến thể mới.',
                          tool_outputs=[*state.get('tool_outputs',[]),{'tool':'resolve_'+domain,'ok':True,'output':lookup,'arguments':{'query':query}}])
        return update

    async def gather(self,state):
        work=dict(state['research_work']); docs={}; ctx=request_context.get()
        query=work['plan']['target']
        if work['qa'] and getattr(self.settings,'RAG_ENABLED',False):
            try:
                docs = await retrieve_knowledge(ctx.backend, ctx.token, query)
            except Exception:
                work['retrieval_status']='unavailable'
        # Local evidence is graded first. Web is only used now if local retrieval is empty.
        if docs:
            allowed=await reserve_documents(self.store,state['run_id'],list(docs))
            docs={k:v for k,v in docs.items() if k in allowed}
        if not docs: docs=await self.web(state,work['plan']['queries'])
        work['documents']=docs
        events=list(state.get('jev_events',[]))
        if docs and any(k.startswith('kb:') for k in docs):
            evaluation,events=await self.evaluate(state,'local',
                {'request':work['plan']['target'],'sources':self.evidence_projection(work)},
                get_questions("research.local"))
            work['jev_local_status']=evaluation.get('status','unknown')
            work['jev_local_enforced']=bool(evaluation.get('enforced'))
            probability=self.probability(evaluation,'local_insufficient')
            if evaluation.get('enforced') and probability is not None and probability>=.90:
                # Reserve documents durably before adding web sources, retaining useful KB passages.
                web=await self.web(state,work['plan']['queries'])
                work['documents']={**docs,**web}
                work['web_fallback_done']=True
        return {'research_work':work,'jev_events':events}

    async def web(self,state,queries):
        async def budget(kind): await reserve(self.store,state['run_id'],kind)
        rows=[]
        for query in queries:
            kwargs={'reserve':budget}
            if getattr(self.settings,'RESEARCH_SOURCE_DOMAINS',[]): kwargs['domains']=self.settings.RESEARCH_SOURCE_DOMAINS
            rows.extend(await self.tavily.search(query,**kwargs))
        decision=state['decision']
        target=((state.get('research_work') or {}).get('plan') or {}).get('target') or queries[0]
        product=target if decision.get('domain')=='foods' and decision.get('intent') not in QA_INTENTS else None
        catalog=decision.get('intent') not in QA_INTENTS and decision.get('domain')
        rows = rank_sources(rows, target, domain=catalog, product=product)
        allowed=await reserve_documents(self.store,state['run_id'],[r['url'] for r in rows])
        rows=[r for r in rows if r['url'] in allowed]
        # Full text only where it can be fetched: social pages block extraction and are opinions anyway.
        thin=[r['url'] for r in rows if len(r.get('content',''))<600 and not social(r['url'])][:3]
        extracted=await self.tavily.extract(thin,reserve=budget) if thin else []
        content={r['url']:r['raw_content'] for r in extracted}
        return {r['url']:{**r,'source_id':r['url'],'content':content.get(r['url'],r['content'])[:12000],
                         'retrieved_at':datetime.now(timezone.utc).isoformat()} for r in rows}

    async def draft(self,state,work):
        await reserve(self.store,state['run_id'],'llm')
        domain=state['decision'].get('domain')
        schema='' if work['qa'] else '\nSchema backend của payload: '+json.dumps(
            (FoodCreate if domain=='foods' else ExerciseCreate).model_json_schema(),ensure_ascii=False)
        # Bounded evidence context; private history/profile is never sent to research.
        documents = bounded_documents(work['documents'])
        # Verification sees exactly the passages the model was given.
        work['documents']={r['source_id']:r for r in documents}
        # Plain-text sources under short labels: the model copies "S2" reliably, a long URL not always.
        labels={f'S{i}':row['source_id'] for i,row in enumerate(documents,1)}
        plan=work['plan']
        task='Trả lời câu hỏi kiến thức bằng claims có nguồn.' if work['qa'] else f'Dựng payload {domain} cho catalog HercFit từ các claims.'
        if plan.get('distinct_from'):
            task+=' Biến thể mới, phân biệt với: '+', '.join(plan['distinct_from'])+'.'
        sources='\n\n'.join(f'[{label}] {row.get("title") or ""} — {row.get("url") or row["source_id"]}\n{row["content"]}'
                            for label,row in zip(labels,documents))
        message=await self.models.get('research').ainvoke([SystemMessage(content=PROMPT+schema),
            HumanMessage(content=f'Mục tiêu: {plan["target"]}\nNhiệm vụ: {task}\n\nNguồn:\n{sources}')])
        return parse_draft(message,labels)

    async def synthesize(self,state):
        work=dict(state['research_work'])
        if not work['documents']:
            work['draft']=ResearchDraft(missing_fields=['nguồn xác minh']).model_dump(); return {'research_work':work}
        draft=await self.draft(state,work)
        if work['qa'] and not draft.sufficient and not work.get('web_fallback_done') and any(k.startswith('kb:') for k in work['documents']):
            # One adaptive fallback, with the same durable budget and deadline.
            web=await self.web(state,work['plan']['queries'])
            work['documents']={**work['documents'],**web} if work.get('jev_local_enforced') else web
            if work['documents']: draft=await self.draft(state,work)
        work['draft']=draft.model_dump()
        return {'research_work':work}

    async def validate(self,state):
        work=state['research_work']; draft=ResearchDraft.model_validate(work['draft'])
        domain=state['decision'].get('domain')
        product=work['plan']['target'] if domain=='foods' and not work['qa'] else None
        def url_of(source_id): return str((work['documents'].get(source_id) or {}).get('url') or '')
        # Authority is the source registry's rating of the publisher; the model's own label is discarded.
        checked=[c.model_copy(update={'authority':rate(c.source_id,url_of(c.source_id),product).tier})
                 for c in verify_claims(draft.claims,work['documents'])]
        dropped=len(draft.claims)-len(checked)-sum(1 for c in draft.claims if c.conflict or not c.applicable)
        missing=list(draft.missing_fields); conflicts=list(draft.conflicts)
        if any(c.conflict for c in draft.claims): conflicts.append('Nguồn bất đồng')
        if not checked or not draft.sufficient: missing.append('bằng chứng đầy đủ')
        if checked and not quality_gate(checked,url_of,product):
            conflicts.append('Cần kiểm duyệt chất lượng nguồn')
        candidate=None
        if not work['qa']:
            schema=FoodCreate if domain=='foods' else ExerciseCreate
            draft.payload.pop('image_url',None)  # images are imported to Cloudinary after confirmation
            cleared=[]
            try:
                payload=schema.model_validate(draft.payload).model_dump(mode='json')
                # Values without field-level evidence are cleared to null/default, never kept on trust.
                payload,needed,cleared=audit(domain,payload,checked,url_of)
                payload=schema.model_validate(payload).model_dump(mode='json')
                missing.extend(needed)
            except ValueError:
                payload=draft.payload; missing.append('backend schema')
            cited={c.source_id for c in checked}
            sources=[{'source_id':key,'url':url_of(key),'title':str(doc.get('title') or '')[:500],
                      'retrieved_at':str(doc['retrieved_at']) if doc.get('retrieved_at') else None}
                     for key,doc in work['documents'].items() if key in cited]
            if domain=='foods' and 'backend schema' not in missing:
                payload['data_quality']={'research':{'sources':[s['url'] for s in sources if s['url']],'unverified_fields':cleared}}
            draft=draft.model_copy(update={'payload':payload})
            candidate={'schema_version':2,'domain':domain,'query':work['plan']['target'],'payload':payload,
                       'evidence':[c.model_dump() for c in checked],'sources':sources,'unverified_fields':cleared,
                       'missing_fields':missing,'conflicts':conflicts}
        events=list(state.get('jev_events',[])); rejections=dict(state.get('jev_rejections',{}))
        if not missing and not conflicts:
            projection={'request':work['plan']['target'],'sources':self.evidence_projection(work),'draft':draft.model_dump(mode='json')}
            fingerprint=hashlib.sha256(json.dumps(projection,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            evaluation,events=await self.evaluate(state,'final',projection,get_questions("research.final"))
            # A known refusal is a property of this exact evidence/draft. Switching
            # mode or exhausting the ledger must not turn it into an approval.
            rejection=rejections.get(fingerprint,{})
            if evaluation.get('enforced'):
                supported=self.probability(evaluation,'supported'); conflict=self.probability(evaluation,'conflict')
                sufficient=self.probability(evaluation,'sufficient')
                if supported is not None and supported<=.10 or conflict is not None and conflict>=.90:
                    rejection={**rejection,'conflict':'Jev: khẳng định thiếu căn cứ hoặc mâu thuẫn nguồn'}
                if sufficient is not None and sufficient<=.10:
                    rejection={**rejection,'missing':'Jev: chưa đáp ứng đầy đủ yêu cầu'}
            if rejection:
                rejections[fingerprint]=rejection
                if rejection.get('conflict'): conflicts.append(rejection['conflict'])
                if rejection.get('missing'): missing.append(rejection['missing'])
        clarification=choice=None; found=None
        if candidate is not None and not missing and not conflicts:
            secret=getattr(self.settings,'RESEARCH_ATTESTATION_SECRET',None)
            found=await catalog_choice.lookups(domain,candidate['query'],payload['name_vi'])
            if secret is None:
                missing.append('chứng thực research chưa được cấu hình')
            elif work.get('distinct') and catalog_choice.name_taken(found):
                missing.append('name_vi: trùng tên bản ghi có sẵn, cần tên phân biệt')
            else:
                # Persisted and signed only after the deterministic AND Jev gates.
                candidate['research_id']=await self.store.research(state,candidate)
                candidate['attestation']=catalog_choice.attest(candidate,state['user_id'],secret.get_secret_value())
                resolution,existing=catalog_choice.settle(found,'create_distinct' if work.get('distinct') else 'create')
                if resolution:
                    candidate.update(catalog_choice.revise(candidate,resolution,found,existing))
                else:
                    clarification,choice=catalog_choice.form(domain,candidate['query'],found,candidate)
        status=(ResearchStatus.NEEDS_REVIEW if conflicts else ResearchStatus.INSUFFICIENT_EVIDENCE if missing
                else ResearchStatus.NEEDS_USER_INPUT if choice else ResearchStatus.COMPLETED)
        result=ResearchResult(status=status,claims=checked,missing_fields=missing,conflicts=conflicts)
        annotate(source_count=len(work['documents']), citation_count=len(checked), dropped_claims=max(0, dropped),
                 missing_count=len(missing), conflict_count=len(conflicts), sufficient=not missing and not conflicts)
        # Verified quotes about another size/recipe: never saved as facts, shown as estimates.
        related=[c.model_copy(update={'authority':rate(c.source_id,url_of(c.source_id),product).tier})
                 for c in related_claims(draft.claims,work['documents'])]
        complete=status==ResearchStatus.COMPLETED
        sources=[]
        for claim in [*checked,*([] if complete else related)]:
            source=work['documents'][claim.source_id]
            if public_url(source.get('url','')):
                sources.append({'title':source.get('title',''),'url':source['url'],'content':claim.quote})
        answer=findings(checked,work['documents'],'Theo các nguồn đã kiểm chứng:') if checked else []
        if work['plan']['intent']=='TRAINING_PLAN' and answer:
            answer.insert(0,'Đề xuất tham khảo dựa trên nguồn bên dưới. Để cá nhân hóa, cần mục tiêu, số buổi mỗi tuần và kinh nghiệm tập hiện tại.')
        async def image_budget(kind): await reserve(self.store,state['run_id'],kind)
        images=await find_illustrations(self.tavily,work['plan']['target'],domain,reserve=image_budget) if complete or choice else []
        if candidate is not None:
            candidate['missing_fields']=missing
            candidate['conflicts']=conflicts
            candidate['image_candidates']=images
        update={'research_result':result.model_dump(mode='json'),'candidate':candidate,'sources':sources,'illustrations':images[:1],
                'research_answer':'\n'.join(answer) if work['qa'] and complete else None,
                'research_trace':[c.model_dump() for c in checked],
                'jev_events':events,'jev_rejections':rejections,
                'status':'running' if complete else 'needs_input',
                'error':None if complete else 'Chưa đủ căn cứ: '+', '.join(missing+conflicts)}
        if work['qa'] and not complete:
            # A knowledge question gets what the sources do say, marked as unconfirmed, instead of a form.
            # Claims Jev found unsupported or contradicted are not repeated, only the sources consulted.
            rejected=any(rejection for rejection in rejections.values()) and any(c.startswith('Jev') for c in conflicts+missing)
            update.update(status='running',error=None,research_answer=partial_answer(
                work['plan']['target'],[] if rejected else [*checked,*related],work['documents'],weak=bool(conflicts)))
        elif candidate is not None and not complete and not choice:
            # Human in the loop with what research found: pick a sourced estimate or give label values.
            # Sources that disagree are exactly when the person should choose, so disputed figures stay.
            material=[c.model_copy(update={'authority':rate(c.source_id,url_of(c.source_id),product).tier})
                      for c in verified_claims(draft.claims,work['documents'])]
            reply,form,estimates=catalog_followup(domain,work['plan']['target'],material,work['documents'],product)
            update.update(prepared_reply=reply,clarification=form,catalog_choice=estimates)
        if choice:
            update.update(clarification=clarification,catalog_choice=choice,
                          prepared_reply=f'Kết quả nghiên cứu "{payload["name_vi"]}" trùng hoặc gần giống bản đã có trong catalog. '
                                         'Bạn chọn dùng bản có sẵn hoặc tạo bản mới bên dưới.',
                          error=f'Bản ghi nghiên cứu "{payload["name_vi"]}" trùng hoặc gần giống bản có sẵn trong catalog; cần người dùng chọn dùng bản có sẵn hay tạo biến thể mới.',
                          tool_outputs=[*state.get('tool_outputs',[]),*({'tool':'resolve_'+domain,'ok':True,'output':found[key],'arguments':{'query':query}}
                                        for key,query in (('query',candidate['query']),('name',payload['name_vi'])))])
        return update
