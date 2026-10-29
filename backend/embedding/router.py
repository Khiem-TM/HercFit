from fastapi import APIRouter, HTTPException, Request
from routers.dependencies import SessionDep, CurrentUserDep
from embedding.config import settings
from embedding.retrieval import SearchRequest, search

router=APIRouter(prefix='/knowledge',tags=['knowledge'])

@router.post('/search')
async def knowledge_search(payload: SearchRequest, session: SessionDep, user: CurrentUserDep, request: Request):
    client=getattr(request.app.state,'embedding_client',None)
    if client is None: raise HTTPException(503,'RAG_UNAVAILABLE')
    # Authentication used this read-only session. Release its connection before
    # the external embedding call so ordinary CRUD remains available.
    await session.commit()
    try:
        return await search(session,payload,settings(),client)
    except HTTPException: raise
    except Exception:
        raise HTTPException(503,'RAG_RETRIEVAL_UNAVAILABLE') from None
