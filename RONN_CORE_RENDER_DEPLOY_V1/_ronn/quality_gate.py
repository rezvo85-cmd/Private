import re
import time
from intelligence_core import explicit_requirements, requirement_coverage, current_information_risk, completion_claim_scan, suspicious_specificity

ABSOLUTE_WORDS=('guaranteed','perfect','100%','zero errors','no errors','always','never fails','fully fixed','completely fixed')
SOURCE_WORDS=('source','according to','documentation','docs','release notes','official','citation','http://','https://')

def sentence_rows(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+',text or '') if s.strip()]

def certainty_scan(answer):
    out=[]
    for s in sentence_rows(answer):
        low=s.lower()
        if any(x in low for x in ABSOLUTE_WORDS): out.append(s[:500])
    return out[:12]

def link_scan(answer):
    return re.findall(r'https?://[^\s)\]>]+',answer or '')[:20]

def format_scan(message,answer):
    low=(message or '').lower(); warnings=[]
    if 'json' in low and ('return json' in low or 'json only' in low):
        stripped=(answer or '').strip()
        if not (stripped.startswith('{') or stripped.startswith('[')): warnings.append('Requested JSON-only output may not be JSON-only.')
    if 'exactly ' in low:
        m=re.search(r'exactly\s+(\d+)\s+(?:items|ideas|steps|things|examples)',low)
        if m:
            expected=int(m.group(1)); numbered=len(re.findall(r'^\s*\d+[.)]\s+',answer or '',re.M))
            if numbered and numbered!=expected: warnings.append(f'Requested exactly {expected} numbered items; detected {numbered}.')
    return warnings

def quality_report(message,answer,evidence_mode='model',runtime_verified=False):
    coverage=requirement_coverage(message,answer)
    completion=completion_claim_scan(answer)
    current=current_information_risk(message)
    certainty=certainty_scan(answer)
    warnings=[]
    if completion and not runtime_verified: warnings.append('Completion/test language appears without runtime verification evidence.')
    if current['time_sensitive'] and evidence_mode not in ('live','research','tools'): warnings.append('Time-sensitive request was answered without a live/research evidence mode.')
    if coverage['total'] and coverage['coverage_signal']<.5: warnings.append('Requirement coverage signal is low; review for dropped constraints.')
    if certainty: warnings.append('Absolute-certainty language detected; confirm it is justified by evidence.')
    warnings += format_scan(message,answer)
    score=100
    score-=20 if completion and not runtime_verified else 0
    score-=20 if current['time_sensitive'] and evidence_mode not in ('live','research','tools') else 0
    score-=15 if coverage['total'] and coverage['coverage_signal']<.5 else 0
    score-=min(20,len(certainty)*4)
    score-=min(20,len(warnings)*3)
    return {
        'quality_score':max(0,score),'warnings':warnings[:20],'coverage':coverage,
        'completion_claims':completion,'certainty_review':certainty,'specificity_review':suspicious_specificity(answer),
        'links':link_scan(answer),'runtime_verified':bool(runtime_verified),'evidence_mode':evidence_mode,'checked_at':int(time.time()),
    }
