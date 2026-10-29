"""Local, bounded parsing; no document-supplied URL is fetched."""
from html.parser import HTMLParser
from pathlib import Path
import re

class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.blocked=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','iframe','object'}: self.blocked+=1
        if tag in {'h1','h2','h3','h4','h5','h6'} and not self.blocked: self.parts.append('\n\n'+'#'*int(tag[1])+' ')
        elif tag in {'p','div','br','li'} and not self.blocked: self.parts.append('\n\n')
    def handle_endtag(self,tag):
        if tag in {'h1','h2','h3','h4','h5','h6'} and not self.blocked: self.parts.append('\n\n')
        if tag in {'script','style','iframe','object'}: self.blocked=max(0,self.blocked-1)
    def handle_data(self,data):
        if not self.blocked: self.parts.append(data)

def load_file(root, filename, max_bytes):
    root=Path(root).resolve(); path=(root/filename).resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise ValueError('File outside ingestion root')
    if path.stat().st_size>max_bytes: raise ValueError('Document exceeds size limit')
    suffix=path.suffix.lower()
    if suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted or len(reader.pages)>500: raise ValueError('Encrypted/oversized PDF')
        content='\f'.join(p.extract_text() or '' for p in reader.pages)
    elif suffix in {'.md','.txt','.html','.htm'}:
        content=path.read_text(encoding='utf-8')
        if suffix in {'.html','.htm'}:
            parser=TextHTML(); parser.feed(content); content=''.join(parser.parts)
    else: raise ValueError('Unsupported document type')
    if not content.strip() or len(content)>2_000_000: raise ValueError('Empty or excessive extracted content; OCR is unsupported')
    return content

def chunks(content, max_chars=2400):
    result=[]; heading=None
    for page,text in enumerate(content.split('\f'),1):
        buffer=''
        for paragraph in re.split(r'\n\s*\n',text):
            if paragraph.startswith('#'):
                if buffer.strip(): result.append({'content':buffer.strip(),'heading':heading,'page':page}); buffer=''
                heading=paragraph.splitlines()[0].lstrip('# ').strip()[:500]
            for offset in range(0,len(paragraph),max_chars):
                part=paragraph[offset:offset+max_chars]
                if len(buffer)+len(part)>max_chars and buffer.strip():
                    result.append({'content':buffer.strip(),'heading':heading,'page':page}); buffer=''
                buffer+=part+'\n\n'
        if buffer.strip(): result.append({'content':buffer.strip(),'heading':heading,'page':page})
    return result
