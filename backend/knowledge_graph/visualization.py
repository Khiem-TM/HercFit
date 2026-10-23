"""Read-only owner-scoped projection for the personal constellation UI."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from .driver import create_driver, value

QUERY = """
MATCH (s:KGState {key:'main'}) WHERE s.ready=true
CALL {
 MATCH (n:KGEntity {owner_id:$owner})
 WHERE coalesce(n.deleted,false)=false
 AND n.kind IN ['User','Goal','BodyMetric','Meal','MealItem','Session','Run','Execution','Food']
 AND (NOT n:Goal OR n.status='IN_PROGRESS')
 AND (NOT (n:Meal OR n:BodyMetric OR n:MealItem) OR coalesce(n.business_at,n.source_at,'') >= $business)
 AND (NOT n:Session OR any(sid IN $sessions WHERE n.key='agent:Session:'+sid AND n.session_generation=$generations[sid]))
 AND (NOT (n:Run OR n:Execution) OR
      (n.session_id IN $sessions AND n.session_generation=$generations[n.session_id]))
 AND (NOT (n:Run OR n:Execution) OR n.source_at >= $memory)
 WITH n ORDER BY CASE WHEN n:User THEN 0 ELSE 1 END, n.source_at DESC LIMIT 50
 RETURN collect(n) AS owned
}
CALL {
 WITH owned
 UNWIND owned AS n
 MATCH (n)-[:REFERS_TO]->(f:Food {scope:'SYSTEM'})
 WHERE coalesce(f.deleted,false)=false
 RETURN collect(DISTINCT f)[0..15] AS foods
}
WITH s,owned+foods AS nodes
CALL {
 WITH nodes UNWIND nodes AS a
 MATCH (a)-[r]->(b) WHERE b IN nodes
 RETURN collect(DISTINCT {source:a.key,target:b.key,label:type(r)}) AS edges
}
RETURN [n IN nodes | {id:n.key,kind:n.kind,fact:n.fact_json,updated_at:n.source_at}] AS nodes,
 edges,s.projection_lag_ms AS lag_ms
"""
LABELS = {'User':'Bạn','Goal':'Mục tiêu','BodyMetric':'Số đo','Meal':'Bữa ăn','MealItem':'Khẩu phần',
          'Food':'Thực phẩm','Session':'Hội thoại','Run':'Lượt trò chuyện','Execution':'Thao tác'}

async def personal_graph(service, user_id):
    empty = {'nodes':[], 'edges':[], 'status':'unavailable', 'lag_ms':None}
    try:
        async with asyncio.timeout(3):
            gate = await service.store.kg_retrieval_gate(user_id)
            if gate.get('blocked'):
                return {**empty,'status':'blocked'}
            generations = gate.get('session_generations',{})
            if service.driver is None:
                service.driver = create_driver(service.settings)
            now = datetime.now(timezone.utc)
            async with service.driver.session(database=value(service.settings,'NEO4J_DATABASE','neo4j')) as session:
                record = await (await session.run(QUERY,owner=user_id,sessions=list(generations),generations=generations,
                    business=(now-timedelta(days=value(service.settings,'KG_BUSINESS_RETENTION_DAYS',90))).isoformat(),
                    memory=(now-timedelta(days=value(service.settings,'KG_MEMORY_RETENTION_DAYS',30))).isoformat())).single()
            if record is None:
                return {**empty,'status':'warming'}
            nodes=[]
            for node in record['nodes']:
                fact=json.loads(node['fact']) if node['fact'] else {}
                data=fact.get('data',{})
                title=data.get('name') or data.get('name_vi') or data.get('title') or data.get('tool') or LABELS.get(node['kind'],'Dữ liệu')
                details={k:v for k,v in data.items() if k in {'weight_kg','height_cm','consumed_at','recorded_at','quantity','unit','status','duration_ms','start_date','target_date','energy_kcal','protein_g','serving_size','serving_unit'} and v is not None}
                nodes.append({'id':node['id'],'kind':node['kind'],'label':str(title)[:90],
                              'updated_at':node['updated_at'],'source':fact.get('source','backend'), 'details':details})
            return {'nodes':nodes,'edges':record['edges'],'status':'ok' if nodes else 'empty','lag_ms':record['lag_ms']}
    except Exception:
        return empty
