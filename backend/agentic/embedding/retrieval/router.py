from fastapi import APIRouter, HTTPException, Request

from agentic.embedding.core import settings
from agentic.embedding.retrieval.search import RetrievalUnavailable, SearchRequest, search
from api.dependencies import CurrentUserDep, SessionDep

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/search")
async def knowledge_search(
    payload: SearchRequest, session: SessionDep, user: CurrentUserDep, request: Request
):
    client = getattr(request.app.state, "embedding_client", None)
    if client is None:
        raise HTTPException(503, "RAG_UNAVAILABLE")
    # Bước xác thực đã dùng session chỉ đọc này. Nhả kết nối của nó trước
    # lời gọi embedding bên ngoài để CRUD thông thường vẫn dùng được.
    await session.commit()
    try:
        return await search(
            session, payload, settings(), client, getattr(request.app.state, "rerank_client", None)
        )
    except RetrievalUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(503, "RAG_RETRIEVAL_UNAVAILABLE") from None
