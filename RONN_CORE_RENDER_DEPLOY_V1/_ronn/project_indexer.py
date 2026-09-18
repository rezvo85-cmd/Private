import re
from collections import defaultdict

LANG_BY_EXT={
    '.py':'python','.js':'javascript','.jsx':'javascript','.ts':'typescript','.tsx':'typescript',
    '.lua':'lua','.luau':'luau','.html':'html','.css':'css','.json':'json','.md':'markdown',
    '.yml':'yaml','.yaml':'yaml','.toml':'toml','.sql':'sql','.sh':'shell','.bat':'batch'
}

def _ext(name):
    n=(name or '').lower(); i=n.rfind('.')
    return n[i:] if i>=0 else ''

def _symbols(name,content):
    lang=LANG_BY_EXT.get(_ext(name),'text'); defs=[]; imports=[]; env=[]; ports=[]; urls=[]
    text=content or ''
    if lang=='python':
        defs += re.findall(r'^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(',text,re.M)
        defs += re.findall(r'^\s*class\s+([A-Za-z_]\w*)\b',text,re.M)
        imports += re.findall(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',text,re.M)
        imports=[a or b for a,b in imports]
    elif lang in ('javascript','typescript'):
        defs += re.findall(r'\b(?:function|class)\s+([A-Za-z_$][\w$]*)',text)
        defs += re.findall(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>',text)
        imports += re.findall(r'\bfrom\s+[\'\"]([^\'\"]+)[\'\"]|\brequire\(\s*[\'\"]([^\'\"]+)',text)
        imports=[a or b for a,b in imports]
    elif lang in ('lua','luau'):
        defs += re.findall(r'\bfunction\s+([A-Za-z_][\w.:]*)\s*\(',text)
        defs += re.findall(r'\blocal\s+function\s+([A-Za-z_]\w*)\s*\(',text)
    env += re.findall(r'(?:os\.getenv|process\.env[.\[]|getenv\()[\'\"]?([A-Z][A-Z0-9_]{2,})',text)
    ports += re.findall(r'(?<!\d)(?:localhost:|127\.0\.0\.1:|PORT\s*[=:]\s*[\'\"]?)(\d{2,5})',text,re.I)
    urls += re.findall(r'https?://[^\s\'\"<>]+',text)
    return {'language':lang,'definitions':list(dict.fromkeys(defs))[:120],'imports':list(dict.fromkeys(imports))[:120],
            'env_vars':list(dict.fromkeys(env))[:80],'ports':list(dict.fromkeys(ports))[:30],'urls':list(dict.fromkeys(urls))[:40]}

def index_files(files):
    rows=[]; definitions=defaultdict(list); imports=defaultdict(list); env=set(); ports=set(); languages=defaultdict(int)
    for f in files or []:
        name=getattr(f,'name','file'); content=getattr(f,'content','') or ''
        s=_symbols(name,content); languages[s['language']]+=1
        for sym in s['definitions']: definitions[sym].append(name)
        for imp in s['imports']: imports[name].append(imp)
        env.update(s['env_vars']); ports.update(s['ports'])
        rows.append({'name':name,'chars':len(content),**s})
    duplicates={k:v for k,v in definitions.items() if len(v)>1}
    return {
        'file_count':len(rows),'languages':dict(languages),'files':rows[:80],
        'duplicate_symbols':dict(list(duplicates.items())[:40]),
        'env_vars':sorted(env)[:100],'ports':sorted(ports)[:50],
        'dependency_imports':dict(list(imports.items())[:80]),
    }

def index_summary(index):
    if not index or not index.get('file_count'): return 'No attached project files were indexed.'
    lines=[f"Indexed {index['file_count']} files. Languages: {index.get('languages',{})}."]
    if index.get('duplicate_symbols'): lines.append('Duplicate symbol signal: '+', '.join(list(index['duplicate_symbols'])[:12]))
    if index.get('env_vars'): lines.append('Environment variables referenced: '+', '.join(index['env_vars'][:20]))
    if index.get('ports'): lines.append('Ports referenced: '+', '.join(index['ports'][:12]))
    return '\n'.join(lines)
