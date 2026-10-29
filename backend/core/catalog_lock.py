"""Take catalog locks before row/user locks, including direct model helpers."""
from functools import wraps
from sqlalchemy import text

def catalog_write(fn):
    @wraps(fn)
    async def wrapped(cls, session, *args, **kwargs):
        await session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'catalog:'+cls.__tablename__})
        return await fn(cls,session,*args,**kwargs)
    return wrapped
