import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from knowledge_graph.visualization import personal_graph

@pytest.mark.asyncio
async def test_owner_gate_and_output_allowlist():
    record={'nodes':[{'id':'backend:Meal:1','kind':'Meal','updated_at':None,
        'fact':'{"source":"backend","data":{"name":"Bữa sáng","protein_g":null,"token":"secret","energy_kcal":200}}'}],
        'edges':[],'lag_ms':0}
    session=AsyncMock()
    result=AsyncMock(); result.single.return_value=record; session.run.return_value=result
    driver=MagicMock(); driver.session.return_value.__aenter__.return_value=session
    store=SimpleNamespace(kg_retrieval_gate=AsyncMock(return_value={'session_generations':{'mine':2}}))
    service=SimpleNamespace(store=store,driver=driver,settings=SimpleNamespace())
    data=await personal_graph(service,'owner-a')
    assert data['nodes'][0]['details']=={'energy_kcal':200}
    assert 'secret' not in str(data)
    assert session.run.call_args.kwargs['owner']=='owner-a'
    assert session.run.call_args.kwargs['generations']=={'mine':2}

@pytest.mark.asyncio
async def test_outage_returns_no_old_private_data():
    service=SimpleNamespace(store=SimpleNamespace(kg_retrieval_gate=AsyncMock(side_effect=RuntimeError('secret'))))
    data=await personal_graph(service,'owner-a')
    assert data['nodes']==[] and data['status']=='unavailable'
    assert 'secret' not in str(data)

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('KG_TEST_NEO4J_URI'),reason='isolated Neo4j required')
async def test_real_cypher_compiles_and_excludes_another_owner():
    from knowledge_graph.driver import create_driver
    settings=SimpleNamespace(NEO4J_URI=os.environ['KG_TEST_NEO4J_URI'],NEO4J_PASSWORD=os.environ['KG_TEST_NEO4J_PASSWORD'])
    driver=create_driver(settings)
    try:
        async with driver.session() as session:
            await (await session.run("MERGE (s:KGState {key:'main'}) SET s.ready=true")).consume()
        service=SimpleNamespace(driver=driver,settings=settings,store=SimpleNamespace(kg_retrieval_gate=AsyncMock(return_value={'session_generations':{}})))
        data=await personal_graph(service,'nonexistent-test-owner')
        assert data['status']=='empty' and data['nodes']==[]
    finally:
        await driver.close()
