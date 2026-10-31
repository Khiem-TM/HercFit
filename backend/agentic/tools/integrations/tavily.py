from agentic.observability import observed, annotate, span
import asyncio
import ipaddress
import time
from collections import OrderedDict
from urllib.parse import urlparse
import httpx


def public_url(url):
    try:
        parsed=urlparse(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password: return False
        host=parsed.hostname.lower()
        if host=='localhost' or host.endswith(('.local','.internal','.localhost')) or '.' not in host: return False
        try: return ipaddress.ip_address(host).is_global
        except ValueError: return True
    except ValueError: return False

class TavilyUnavailable(Exception): pass

class TavilyClient:
    def __init__(self,key='',transport=None):
        self.key=key or ''
        headers={'Authorization':'Bearer '+self.key} if self.key else {}
        self.http=httpx.AsyncClient(base_url='https://api.tavily.com',timeout=12,transport=transport,headers=headers)
        self.cache=OrderedDict()
    async def close(self): await self.http.aclose()

    @observed('tavily.request', 'tool', capture=('path',), output=False)
    async def _post(self,path,body,reserve=None,timeout=None):
        if not self.key: raise TavilyUnavailable('Tavily is not configured')
        for attempt in range(2):
            if reserve:
                if path=='/search': await reserve('search')
                await reserve('web')
            try:
                with span('tavily.http_attempt', 'tool', attempt=attempt+1) as run:
                    response=await self.http.post(path,json=body,**({'timeout':timeout} if timeout else {}))
                    if run:
                        run.add_metadata({'http_status': response.status_code, 'attempt': attempt+1})
                        if response.is_error: run.error = f'HTTP{response.status_code}'
                if response.status_code in {429,500,502,503,504} and attempt==0:
                    await asyncio.sleep(.2); continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException,httpx.TransportError):
                if attempt: raise
                await asyncio.sleep(.2)

    @observed('tavily.search', 'tool', capture=('query', 'depth', 'domains'), output=True)
    async def search(self,query,*,reserve=None,depth='advanced',domains=None):
        key=(query.casefold().strip(),depth,tuple(domains or []))
        cached=self.cache.get(key)
        if cached and cached[0]>time.monotonic():
            annotate(cache_hit=True, result_count=len(cached[1]))
            return [dict(r) for r in cached[1]]
        annotate(cache_hit=False)
        body={'query':query,'max_results':6,'search_depth':depth,'include_raw_content':False}
        if domains: body['include_domains']=domains
        data=await self._post('/search',body,reserve)
        rows=[{'url':r['url'],'title':str(r.get('title',''))[:500],'content':str(r.get('content',''))[:18000]}
              for r in data.get('results',[]) if public_url(r.get('url',''))][:6]
        self.cache[key]=(time.monotonic()+300,rows)
        self.cache.move_to_end(key)
        while len(self.cache)>128: self.cache.popitem(last=False)
        annotate(result_count=len(rows))
        return [dict(r) for r in rows]

    @observed('tavily.search_images', 'tool', capture=('query',), output=False)
    async def search_images(self,query,*,reserve=None,limit=4):
        """Illustrative images for a public food/exercise name; display candidates, never evidence."""
        key=('images',query.casefold().strip())
        cached=self.cache.get(key)
        if cached and cached[0]>time.monotonic():
            annotate(cache_hit=True, result_count=len(cached[1]))
            return [dict(r) for r in cached[1]]
        annotate(cache_hit=False)
        body={'query':query,'max_results':1,'search_depth':'basic','include_images':True,'include_image_descriptions':True}
        # Image search with descriptions is slower than text search.
        data=await self._post('/search',body,reserve,timeout=25)
        rows=[]
        for image in data.get('images',[]):
            url,description=(image.get('url'),image.get('description')) if isinstance(image,dict) else (image,None)
            if isinstance(url,str) and url.startswith('https://') and public_url(url) and len(url)<=2048:
                rows.append({'url':url,'description':str(description or '')[:300]})
        rows=list({r['url']:r for r in rows}.values())[:limit]
        # Empty answers are flaky upstream: retry them soon instead of pinning them for an hour.
        self.cache[key]=(time.monotonic()+(3600 if rows else 60),rows)
        self.cache.move_to_end(key)
        while len(self.cache)>128: self.cache.popitem(last=False)
        annotate(result_count=len(rows))
        return [dict(r) for r in rows]

    @observed('tavily.extract', 'tool', capture=('urls',), output=True)
    async def extract(self,urls,*,reserve=None):
        urls=list(dict.fromkeys(u for u in urls if public_url(u)))[:3]
        if not urls: return []
        data=await self._post('/extract',{'urls':urls,'extract_depth':'advanced','format':'text'},reserve)
        # failed_results are not evidence, even when the overall HTTP call is 200.
        return [{'url':r['url'],'raw_content':str(r.get('raw_content',''))[:18000]}
                for r in data.get('results',[]) if r.get('url') in urls]
