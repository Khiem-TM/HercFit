import ipaddress
from urllib.parse import urlparse
import httpx


def public_url(url):
    parsed=urlparse(url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host=parsed.hostname.lower()
    if host=='localhost' or host.endswith(('.local','.internal','.localhost')) or '.' not in host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True

class TavilyClient:
    def __init__(self,key='',transport=None):
        self.key=key or ''
        headers={'Authorization':'Bearer '+self.key} if self.key else {}
        self.http=httpx.AsyncClient(base_url='https://api.tavily.com',timeout=25,transport=transport,
                                   headers=headers)
    async def close(self):
        await self.http.aclose()
    async def search(self,query):
        if not self.key:
            return []
        r=await self.http.post('/search',json={'query':query,'max_results':5,'search_depth':'advanced','include_raw_content':False})
        r.raise_for_status()
        return r.json().get('results',[])[:5]
    async def extract(self,urls):
        if not self.key:
            return []
        urls=[u for u in urls if public_url(u)][:3]
        if not urls:
            return []
        r=await self.http.post('/extract',json={'urls':urls,'extract_depth':'advanced','format':'text'})
        r.raise_for_status()
        return r.json().get('results',[])[:3]
