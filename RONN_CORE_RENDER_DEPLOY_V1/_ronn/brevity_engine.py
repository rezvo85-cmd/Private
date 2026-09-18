import re

# RONN R6 adaptive brevity policy. These are executable policy rules, not UI labels.
BREVITY_RULES = [
    "Detect whether a question is simple or complex.",
    "Default simple questions to 1-3 short sentences.",
    "Avoid paragraphs when one sentence is enough.",
    "Avoid long introductions.",
    "Put the direct answer first.",
    "Do not repeat the user's question.",
    "Remove filler words.",
    "Avoid unnecessary background information.",
    "Do not explain obvious facts unless asked.",
    "Prefer short sentences for casual questions.",
    "Use short paragraphs for medium questions.",
    "Use long explanations only for genuinely difficult topics.",
    "Detect questions answerable with a name, number, or yes/no.",
    "Give the answer alone when that is all the user needs.",
    "Use Quick Answer automatically for easy questions.",
    "Use Normal detail for everyday explanations.",
    "Use Deep detail only for difficult requests.",
    "Honor explicit requests such as shorter or concise.",
    "Adapt toward shorter replies when the user's style calls for it.",
    "Avoid huge bullet lists unless requested.",
    "Limit ordinary lists to the most relevant items.",
    "Do not restate the same point in different words.",
    "Avoid conclusions that merely repeat the answer.",
    "Avoid generic preambles such as comprehensive breakdown.",
    "Stop when the question has been answered.",
    "Avoid extra detail that does not improve the answer.",
    "Keep optional depth separate from the main answer.",
    "Audit response length before finalizing.",
    "Shorten drafts that exceed the request's needs.",
    "Simple question = simple answer; hard question = enough detail to solve it.",
]

DETAIL_WORDS = (
    'detail','detailed','explain deeply','deep dive','comprehensive','thorough','everything',
    'step by step','full breakdown','long answer','all of the','analyze','research','why exactly'
)
SHORT_WORDS = ('short','shorter','brief','quick answer','just answer','simple answer','one sentence','concise')
ACTION_WORDS = ('build','make','create','implement','debug','fix','repair','analyze','research','plan','design','code')


def _clean(text: str) -> str:
    return re.sub(r'\s+',' ',str(text or '')).strip()


def requested_list_count(message: str):
    low=_clean(message).lower()
    patterns=(
        r'\b(?:top|best|give me|list|name|show me)\s+(\d{1,3})\b',
        r'\b(\d{1,3})\s+(?:things|ideas|ways|examples|reasons|steps|people|streamers|items|tips|upgrades)\b',
    )
    for pat in patterns:
        m=re.search(pat,low)
        if m:
            n=int(m.group(1))
            if 1 <= n <= 200:
                return n
    return None


def simple_question(message: str, has_files=False, has_images=False, has_project=False) -> bool:
    text=_clean(message); low=text.lower()
    if has_files or has_images or has_project: return False
    if any(x in low for x in DETAIL_WORDS): return False
    if len(text)>220: return False
    if sum(1 for x in ACTION_WORDS if x in low)>=2: return False
    # A requested list can still be simple if the list is modest.
    n=requested_list_count(text)
    if n and n>15: return False
    return bool(
        '?' in text or
        re.match(r'^(who|what|when|where|which|is|are|was|were|does|did|can|could|should|how many|name|list|top|best)\b',low)
    )


def response_length_policy(message: str, style='balanced', difficulty=0, has_files=False, has_images=False, has_project=False):
    text=_clean(message); low=text.lower(); style=(style or 'balanced').lower()
    list_count=requested_list_count(text)
    explicit_short=style=='concise' or any(x in low for x in SHORT_WORDS)
    explicit_detail=style=='detailed' or any(x in low for x in DETAIL_WORDS)
    simple=simple_question(text,has_files,has_images,has_project)

    if explicit_short:
        tier='quick'
    elif explicit_detail or difficulty>=5:
        tier='deep'
    elif list_count and list_count>15:
        tier='normal'
    elif simple and difficulty<=1:
        tier='quick'
    elif difficulty>=3 or has_files or has_project:
        tier='normal'
    else:
        tier='normal'

    budgets={
        'quick': {'max_tokens':180,'target_sentences':2,'target_words':70,'sentence_word_target':18},
        'normal': {'max_tokens':800,'target_sentences':10,'target_words':450,'sentence_word_target':24},
        'deep': {'max_tokens':1500,'target_sentences':24,'target_words':1100,'sentence_word_target':28},
    }
    out={'tier':tier,'simple_question':simple,'explicit_short':explicit_short,'explicit_detail':explicit_detail,'list_count':list_count,'message':text}
    out.update(budgets[tier])
    if list_count:
        out['target_sentences']=max(out['target_sentences'], list_count)
        out['target_words']=max(out['target_words'], min(900, list_count*18 + 35))
    return out


def brevity_directive(policy: dict) -> str:
    tier=policy.get('tier','normal'); n=policy.get('list_count')
    if tier=='quick':
        instruction=(
            "Answer immediately in 1-2 short sentences. Do not use headings, bullets, numbered lists, or a breakdown "
            "unless the user explicitly asks for a list or more detail. No intro, no restating the question, "
            "no generic conclusion, and no extra background unless essential."
        )
    elif tier=='deep':
        instruction=(
            "Use enough detail to fully solve the task, but still remove repetition and filler. Lead with the result, then explanation."
        )
    else:
        instruction=(
            "Be direct and moderately concise. Use short paragraphs and only the detail needed to understand or act."
        )
    if n:
        instruction += f" The user requested {n} items; provide that count when feasible, with concise entries."
    if re.match(r"^(who(?:'s| is)|whos|what(?:'s| is))\b", _clean(str(policy.get('message') or '')).lower()):
        instruction += " For a who-is/what-is identity question, give the plain identity plus one useful sentence and stop."
    return (
        "RONN ADAPTIVE BREVITY POLICY:\n"
        f"- Response tier: {tier}\n"
        f"- Target maximum visible answer size: about {policy.get('target_words')} words unless correctness requires more.\n"
        f"- Prefer sentences around {policy.get('sentence_word_target')} words or fewer when natural.\n"
        f"- {instruction}\n"
        "- Never cut away necessary safety, uncertainty, sources, calculations, code, or steps just to be short.\n"
        "- Do not expose hidden reasoning."
    )


def answer_length_metrics(answer: str):
    text=_clean(answer)
    words=re.findall(r"\b\w+[\w'-]*\b",text)
    sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+',text) if s.strip()]
    lens=[len(re.findall(r"\b\w+[\w'-]*\b",s)) for s in sentences]
    return {
        'words':len(words),'sentences':len(sentences),
        'avg_sentence_words':round(sum(lens)/len(lens),1) if lens else 0,
        'long_sentences':sum(1 for x in lens if x>32),
    }


def brevity_audit(message: str, answer: str, policy: dict):
    m=answer_length_metrics(answer); warnings=[]
    target=int(policy.get('target_words') or 450)
    if policy.get('tier')=='quick' and m['words']>max(target,140): warnings.append('Quick-answer response is longer than the target.')
    if m['long_sentences']>=2: warnings.append('Multiple sentences exceed the long-sentence threshold.')
    if policy.get('simple_question') and m['sentences']>8 and not policy.get('list_count'): warnings.append('Simple question received an unnecessarily long response.')
    return {'policy':policy,'metrics':m,'warnings':warnings}
