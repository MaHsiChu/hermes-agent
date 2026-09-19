"""Read local text documents only after a click on an exact transcript link."""
import re
from pathlib import Path
from urllib.parse import unquote
from markdown_it import MarkdownIt

MAX_BYTES=2*1024*1024
TEXT_SUFFIXES={'.md','.markdown','.txt','.json','.yaml','.yml','.toml','.csv','.log','.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.css','.html','.xml','.rs','.go','.cpp','.h','.hpp','.cs','.sh','.ps1','.sql','.ini','.cfg','.diff','.patch'}

def links(item):
    result=[]
    for block in item.get('blocks',[]):
        if block.get('type')=='diff' and block.get('path'):result.append(block['path'])
        if block.get('type')!='text':continue
        for token in MarkdownIt().parse(block.get('text','')):
            for child in token.children or []:
                if child.type=='link_open':result.append(child.attrGet('href'))
    return result

def location(href,cwd):
    value=unquote(href);line=None
    if value.lower().startswith('file:///'):value=value[8:]
    match=re.search(r'(?:#L|:)(\d+)(?::\d+)?$',value)
    if match:line=int(match[1]);value=value[:match.start()]
    else:value=value.split('#',1)[0]
    value=re.sub(r'^/([a-zA-Z]:[/\\])',r'\1',value)
    if value.startswith('\\\\?\\'):value=value[4:]
    if value.startswith(('\\\\','//')) or (re.match(r'^[a-zA-Z][\w+.-]*:',value) and not re.match(r'^[a-zA-Z]:[/\\]',value)):
        raise ValueError('只预览本机文件链接。')
    path=Path(value)
    if not path.is_absolute():path=Path(cwd)/path
    path=path.resolve()
    if str(path).startswith(('\\\\','//')):raise ValueError('不预览网络文件。')
    return path,line

def read(item,href,cwd):
    if not isinstance(href,str) or href not in links(item):raise ValueError('链接不属于这条会话记录。')
    path,line=location(href,cwd)
    if path.suffix.lower() not in TEXT_SUFFIXES:raise ValueError('此文件类型暂不支持内嵌预览。')
    try:
        with path.open('rb') as f:data=f.read(MAX_BYTES+1)
    except OSError as e:raise ValueError('文件不存在或当前无法读取。') from e
    if len(data)>MAX_BYTES:raise ValueError('文件超过 2 MB，无法内嵌预览。')
    if b'\0' in data:raise ValueError('文件不是文本。')
    try:text=data.decode('utf-8-sig').replace('\r\n','\n')
    except UnicodeError as e:raise ValueError('文件不是 UTF-8 文本。') from e
    return {'path':str(path),'name':path.name,'text':text,'line':line,'markdown':path.suffix.lower() in ('.md','.markdown')}

def change_summary(items):
    files={}
    for item in items:
        if item.get('status') not in (None,'completed'):continue
        for block in item.get('blocks',[]):
            if block.get('type')!='diff' or not block.get('path'):continue
            path=block['path'];key=path.replace('\\','/')
            if re.match(r'^[a-zA-Z]:/',key):key=key.casefold()
            file=files.setdefault(key,{'path':path,'added':0,'removed':0,'patches':[]})
            diff=block.get('text') or ''
            kind=block.get('change') or {}
            kind=kind.get('type') if isinstance(kind,dict) else kind
            # Native add/delete records carry full file text, not a unified hunk.
            if kind in ('add','delete'):
                prefix='+' if kind=='add' else '-'
                count=len(diff.splitlines())
                diff='\n'.join(prefix+line for line in diff.splitlines())
                file['added']+=count if kind=='add' else 0
                file['removed']+=count if kind=='delete' else 0
            else:
                file['added']+=sum(line.startswith('+') and not line.startswith('+++ ') for line in diff.splitlines())
                file['removed']+=sum(line.startswith('-') and not line.startswith('--- ') for line in diff.splitlines())
            file['patches'].append({'item_id':item['id'],'diff':diff,'change':block.get('change')})
    rows=list(files.values())
    return {'files':rows,'added':sum(f['added'] for f in rows),'removed':sum(f['removed'] for f in rows)}
