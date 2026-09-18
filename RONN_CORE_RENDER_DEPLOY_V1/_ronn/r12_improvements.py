"""RONN R12 Improvement Engine.

400 active improvement policies (20 domains x 20 policies). These policies are
used to strengthen routing, context handling, verification, response quality,
project continuity, mobile behavior, privacy, and reliability. They are policy
rules, not 400 separate foundation models.
"""
from __future__ import annotations

import re
from collections import Counter

IMPROVEMENTS = {
    "context": ["Resolve short follow-ups from recent turns before asking again","Prefer newest explicit instruction over older context","Carry named entities across adjacent turns","Track active subject when pronouns are used","Recover omitted objects in commands like do it","Remember active project names during follow-ups","Preserve user-selected options across turns","Detect when a question depends on the previous answer","Keep recent corrections higher priority than older facts","Avoid repeating questions already answered in context","Maintain conversation topic until the user clearly changes it","Recognize shorthand references like the first one","Track comparative references like better or worse","Link screenshots and text from the same task","Use prior constraints when the user says same","Treat continue as continuation of current task","Resolve this/that/it using recent salient objects","Preserve the requested output format across follow-ups","Notice when the user rejects a previous approach","Keep task state after brief interruptions"],
    "reliability": ["Separate verified facts from model inference","Avoid confident guesses when evidence is weak","Recheck contradictory claims before finalizing","Mark uncertainty when source support is incomplete","Prefer stable facts over speculative detail","Avoid inventing dates names numbers or URLs","Treat completion claims as requiring evidence","Detect unsupported specifics before answering","Cross-check high-impact factual claims","Use a second pass for correction requests","Escalate when the user explicitly asks for reliability","Downgrade confidence after provider inconsistency","Prefer primary evidence for changing facts","Repair answers that drop requested constraints","Check answer consistency with prior messages","Reject fake runtime verification language","Distinguish configured from reachable services","Distinguish static checks from runtime tests","Detect likely hallucinated citations or sources","Prefer concise uncertainty over fabricated certainty"],
    "research": ["Route current facts to live research","Prefer primary official sources when available","Cross-check important claims across sources","Use publication dates when freshness matters","Avoid stale rankings for fast-changing topics","Separate source facts from interpretation","Prefer recent evidence for software and model questions","Compare conflicting sources explicitly","Use official release notes for version questions","Use current market data for changing prices","Use recent schedules for events and sports","Avoid quoting unsupported secondary summaries","Track time context for today/current/latest requests","Use source diversity for controversial claims","Prioritize authoritative documentation for APIs","Prefer direct datasets for quantitative claims","Identify when web research is unnecessary","Stop searching once evidence is sufficient","Synthesize instead of dumping raw search results","State when live evidence is unavailable"],
    "reasoning": ["Escalate multi-step problems to deeper reasoning","Break hard tasks into explicit internal phases","Compare alternative solution paths before choosing","Check assumptions before calculation","Detect hidden constraints in wording","Use causal reasoning for why questions","Use counterexamples to test fragile conclusions","Check edge cases in technical solutions","Prefer simpler explanations when complexity is unnecessary","Use dimensional sanity checks in quantitative work","Detect contradictions between premises","Avoid circular reasoning","Distinguish correlation from causation","Check whether the conclusion follows from evidence","Use independent verification for difficult answers","Preserve user goals while optimizing substeps","Estimate uncertainty for incomplete problems","Recognize when a problem is underspecified","Ask only when missing information materially changes the result","Conclude with the most actionable answer first"],
    "coding": ["Trace root cause before rewriting code","Preserve existing interfaces unless change is required","Check imports and references across files","Keep naming consistent across generated files","Prefer minimal coherent patches over broad rewrites","Check likely syntax errors before delivery","Validate API request and response shapes","Handle failure paths explicitly","Avoid hardcoded secrets in client code","Separate client and server responsibilities","Use safe defaults for missing configuration","Check async error handling","Preserve backwards compatibility when practical","Detect stale cache and build artifacts","Add logging at meaningful failure boundaries","Verify route names and file paths","Check environment-variable dependencies","Avoid claiming code works without execution evidence","Prefer deterministic state transitions","Check regression risk after fixes"],
    "debugging": ["Reproduce or isolate the failure before guessing","Rank likely root causes by evidence","Inspect logs before changing unrelated code","Check configuration before code rewrites","Check stale processes and caches","Check permissions and authentication boundaries","Check dependency versions and compatibility","Check network reachability for service failures","Check environment variables for deployment failures","Check path and working-directory assumptions","Check race conditions for intermittent bugs","Compare working and broken states","Prefer smallest reversible repair first","Verify the exact failing path after repair","Check adjacent regressions after a fix","Separate frontend failure from backend failure","Separate provider errors from application errors","Detect silent exceptions and swallowed errors","Use diagnostics to confirm runtime state","Record known failure causes for future avoidance"],
    "memory": ["Store only useful durable preferences","Reject secrets from memory","Prefer project memory over unrelated global memory","Use memory only when relevant","Respect the newest correction to a remembered fact","Track confidence for remembered items","Allow important memories to be pinned","Avoid storing temporary chat noise","Use memory to preserve naming conventions","Use memory to preserve design language","Use memory to preserve known failed approaches","Use memory to preserve project architecture","Use memory to preserve output-style preferences","Avoid over-personalizing unrelated answers","Keep sensitive information out of ordinary memory","Detect conflicts between memory and current request","Prefer current explicit instruction over memory","Summarize long project history into compact facts","Track memory usage to reduce irrelevant recall","Expire low-confidence stale project facts"],
    "planning": ["Turn broad goals into ordered steps","Prioritize blockers before polish","Identify dependencies between tasks","Keep milestones small enough to verify","Prefer reversible early changes","Estimate risk before irreversible actions","Track completion criteria for each phase","Avoid starting optional work before core functionality","Use checkpoints for long projects","Keep one continuous project state","Prevent duplicate competing implementations","Record decisions that affect later phases","Separate must-have from optional work","Stop scope creep when user says no more features","Resume from the last verified state","Identify the next smallest useful action","Use verification gates before deployment","Keep rollback possible during risky changes","Optimize for user outcome rather than task count","Summarize progress without overstating completion"],
    "files": ["Treat related files as one project graph","Inspect file names before proposing structure","Preserve existing file organization when sensible","Avoid rewriting files not involved in the bug","Check cross-file references after edits","Respect user-provided source as authoritative context","Distinguish generated artifacts from originals","Keep backups before destructive transformations","Prefer exact file paths in technical instructions","Detect duplicate or stale file copies","Use content type to select the right parser","Avoid truncating critical configuration files","Keep encoding stable when rewriting text","Preserve line endings when practical","Validate structured files after modification","Check archive contents before assuming layout","Use file evidence instead of guessing unseen content","Trace dependencies through import statements","Avoid exposing secrets found in files","Summarize changed files after a patch"],
    "projects": ["Keep a stable project identity across sessions","Track active project goals","Preserve architecture decisions","Preserve known failure history","Preserve visual design language","Keep feature names consistent","Maintain a project requirement ledger","Track blockers separately from nice-to-haves","Reuse existing working systems","Avoid replacing working parts unnecessarily","Prefer one continuous build over version sprawl","Keep project-specific memory scoped","Track deployment environment assumptions","Track provider and model configuration","Track ownership and permission boundaries","Track data persistence limitations","Record successful fixes for future reuse","Record rejected approaches to avoid repeats","Check new changes against project constraints","Summarize project state before major pivots"],
    "mobile": ["Use native phone viewport sizing","Avoid horizontal overflow","Keep input text at least sixteen pixels on iPhone","Respect safe-area insets","Pin composer above the home indicator","Use full-height dynamic viewport units","Keep navigation behind an accessible drawer","Make touch targets comfortably large","Hide desktop-only clutter on small screens","Keep settings pages independently scrollable","Prevent accidental browser auto-zoom","Use responsive text sizing","Preserve readable line lengths","Keep composer usable with keyboard open","Reduce unnecessary mobile padding","Use one-column layouts on narrow screens","Keep menu controls reachable with one hand","Prevent fixed elements from covering content","Support small-height devices","Keep PWA shell visually app-like"],
    "performance": ["Use fast route for trivial chat","Escalate only when needed","Avoid duplicate provider calls","Cache stable local computations","Bound history sent to models","Compress old context before token overflow","Limit file context to relevant excerpts","Use streaming for long responses","Use provider health to avoid failing routes","Use fallback only after real failure","Avoid unnecessary second-pass checks on trivial tasks","Keep deterministic tools local","Limit expensive live research to changing facts","Track latency by model","Prefer healthy models when quality is comparable","Avoid large UI reflows","Avoid stale service-worker caches","Use bounded database history","Keep diagnostics lightweight during normal chat","Separate background status polling from chat quotas"],
    "privacy": ["Keep provider keys server-side","Never place privileged tokens in public JavaScript","Use HttpOnly sessions for browser owner access","Reject secrets from ordinary memory","Avoid logging sensitive prompt content unnecessarily","Restrict privileged actions to owner sessions","Separate user identity from provider credentials","Use least-privilege permission checks","Avoid exposing internal stack traces to users","Keep recovery codes one-time use","Encrypt vault content at rest","Use secure cookies behind HTTPS proxies","Avoid sharing secrets in diagnostic output","Sanitize filenames and user-controlled labels","Prevent accidental cross-user memory mixing","Scope project data to owner identity","Keep public endpoints minimal","Avoid persistent client storage for privileged secrets","Provide explicit lock/logout behavior","Treat uploads as untrusted content"],
    "security": ["Validate authentication on protected API routes","Use constant-time comparison for secret tokens","Rate-limit expensive public endpoints","Limit request body size","Set security headers","Disallow framing by default","Restrict browser permissions by policy","Validate user-controlled identifiers","Sanitize generated HTML output","Avoid executing uploaded content","Keep CORS explicit when cross-origin access is needed","Detect insecure client-side secret handling","Use secure cookie flags over HTTPS","Separate owner privileges from normal access","Avoid trusting forwarded headers blindly","Handle malformed authorization headers safely","Prevent path traversal in file operations","Use safe serialization for structured data","Prefer allowlists for sensitive operations","Record security-relevant failures without secrets"],
    "verification": ["Run deterministic local checks before strong claims","Use second-model critique for hard work","Check provider response is non-empty","Retry empty streams through fallback","Audit final answers for unsupported completion language","Check requirement coverage before finishing","Check time-sensitive answers used live evidence","Check code snippets for obvious syntax defects","Check structured output validity when requested","Verify UI selectors exist before binding","Verify build identifiers match expected runtime","Verify provider configuration separately from reachability","Verify package files exist","Verify task checkpoints for long work","Check regressions after broad edits","Keep verification status visible in diagnostics","Distinguish passed static checks from runtime proof","Fail closed when critical verification is absent","Use benchmarks to protect intelligence behavior","Keep verification concise for simple tasks"],
    "communication": ["Lead with the answer for simple questions","Match requested length","Avoid filler introductions","Use plain language unless technical detail is needed","Keep instructions sequential","Avoid overwhelming users with too many steps","Use one clear next action when troubleshooting","Preserve user tone without copying hostility","Explain errors in actionable terms","Avoid repeating the same conclusion","Use headings only when they improve scanning","Keep warnings concise","State limitations without overexplaining","Avoid claiming certainty beyond evidence","Summarize complex work in practical terms","Use examples only when they help","Make mobile instructions tap-by-tap","Use direct verbs in action steps","Keep technical names exact","End with the result rather than unnecessary offers"],
    "creativity": ["Generate multiple candidate ideas internally","Select the most coherent creative direction","Keep visual language consistent","Avoid generic placeholder concepts","Use specific implementation details","Align creative choices with project identity","Preserve existing successful style elements","Vary concepts without random inconsistency","Use naming that matches the product tone","Balance novelty with usability","Design interactions not just static visuals","Use hierarchy and spacing intentionally","Prefer meaningful motion over excessive animation","Keep color use consistent with branding","Avoid feature clutter in premium interfaces","Design empty states intentionally","Design loading and error states","Keep iconography consistent","Use responsive creative layouts","Translate creative concepts into buildable specifications"],
    "decision_support": ["Compare options on explicit criteria","Separate facts from preferences","Expose meaningful tradeoffs","Avoid false precision in uncertain comparisons","Use current evidence when options change over time","Prefer reversible choices when uncertainty is high","Identify hidden costs","Identify maintenance burden","Identify security implications","Identify performance implications","Identify learning curve","Identify compatibility risks","Identify vendor lock-in","Identify data persistence risk","Identify scalability limits","Avoid choosing for the user when values are subjective","State what information would change the decision","Use side-by-side comparison when helpful","Keep recommendation logic transparent","Distinguish short-term convenience from long-term fit"],
    "quality": ["Check directness before finalizing","Check factual consistency before finalizing","Check requested format before finalizing","Check constraints before finalizing","Check for unnecessary verbosity","Check for missing edge cases","Check for duplicated content","Check for contradictory recommendations","Check for unsupported claims","Check for stale context","Check for unresolved user corrections","Check for broken references","Check for accidental secret exposure","Check whether the answer is actionable","Check whether the answer matches task difficulty","Check whether a shorter answer would be better","Check whether current data was required","Check whether tools were actually used before claiming use","Check whether completion language is justified","Check whether the user can act without extra clarification"],
    "adaptation": ["Learn from explicit positive feedback","Learn from explicit negative feedback","Demote repeatedly failing model routes","Promote reliable routes for similar tasks","Use recent latency when routes are otherwise equal","Remember successful debugging patterns","Remember failed repair patterns","Adapt answer length to user preference","Adapt technical depth to task complexity","Adapt clarification behavior to context availability","Adapt model choice to provider health","Adapt verification depth to risk","Adapt research depth to freshness requirements","Adapt file retrieval depth to project size","Adapt memory recall to relevance","Adapt creative output to established design language","Adapt planning granularity to project stage","Adapt retry strategy to failure class","Adapt UI density to viewport size","Adapt warnings to actual risk instead of showing everything"],
}
IMPROVEMENT_COUNT=sum(len(v) for v in IMPROVEMENTS.values())
assert IMPROVEMENT_COUNT == 400

TRIGGERS={
    "context":("this","that","it","continue","again","same","before","earlier"),
    "reliability":("reliable","accurate","correct","verify","wrong","fact","evidence"),
    "research":("latest","current","today","research","source","cite","look up","web"),
    "reasoning":("why","analyze","solve","compare","hard","complex","reason"),
    "coding":("code","script","api","backend","frontend","python","javascript","typescript","repo"),
    "debugging":("bug","error","broken","fix","not working","fails","crash","issue"),
    "memory":("remember","memory","previous","project","keep consistent"),
    "planning":("plan","steps","roadmap","next","milestone","strategy"),
    "files":("file","folder","zip","pdf","document","attachment","upload"),
    "projects":("project","build","architecture","system","repo","deployment"),
    "mobile":("phone","iphone","mobile","screen","zoom","app","pwa"),
    "performance":("slow","fast","latency","speed","optimize","performance"),
    "privacy":("privacy","secret","token","api key","password","owner"),
    "security":("security","auth","permission","vulnerability","secure","xss","csrf"),
    "verification":("verify","test","check","prove","confirm","runtime","benchmark"),
    "communication":("short","simple","explain","tell me","step by step","professional"),
    "creativity":("design","create","idea","visual","style","brand","creative"),
    "decision_support":("choose","which","better","best","compare","option","recommend"),
    "quality":("better","improve","quality","polish","fix everything","make sure"),
    "adaptation":("feedback","again","wrong","better","preference","learn"),
}

def _norm(x:str)->str:
    return re.sub(r"\s+"," ",str(x or "").lower()).strip()

def r12_preflight(message:str, history=None, profile:str="chat", difficulty:int=0,
                  has_files:bool=False, has_images:bool=False, project_context:str="")->dict:
    text=_norm(message)
    scores=Counter()
    for category, terms in TRIGGERS.items():
        scores[category]=sum(1 for t in terms if t in text)
    if has_files:
        scores["files"]+=3; scores["projects"]+=1; scores["verification"]+=1
    if has_images:
        scores["context"]+=1; scores["quality"]+=1
    if project_context:
        scores["projects"]+=2; scores["context"]+=1; scores["memory"]+=1
    if history:
        scores["context"]+=1
    if int(difficulty or 0)>=4:
        scores["reasoning"]+=2; scores["verification"]+=1
    active=[k for k,v in scores.most_common() if v>0][:8]
    return {
        "version":"R12",
        "improvement_registry":IMPROVEMENT_COUNT,
        "active_domains":active,
        "domain_scores":dict(scores),
        "active_policy_count":sum(len(IMPROVEMENTS[k]) for k in active),
        "quality_floor":"high" if scores["verification"]+scores["reliability"]>=3 else "standard",
        "mobile_sensitive":scores["mobile"]>0,
        "project_sensitive":scores["projects"]>0,
        "privacy_sensitive":scores["privacy"]+scores["security"]>0,
    }

def r12_directive(report:dict)->str:
    active=report.get("active_domains") or []
    rules=[
        "RONN R12 IMPROVEMENT ENGINE:",
        f"- Improvement registry: {report.get('improvement_registry',400)} active policies.",
        f"- Active domains for this request: {', '.join(active) if active else 'general quality'}.",
        "- Apply only improvements relevant to the task; do not dump internal policy lists into the answer.",
        "- Preserve the user's newest explicit intent, constraints, and requested format.",
        "- Prefer evidence, verified state, and direct usefulness over confident-sounding filler.",
        "- Keep simple requests simple; scale depth only when complexity or risk requires it.",
    ]
    if "context" in active:
        rules.append("- Resolve short follow-ups from recent context before asking the user to repeat information.")
    if "research" in active:
        rules.append("- Use fresh evidence for changing facts and prefer primary/official sources.")
    if "coding" in active or "debugging" in active:
        rules.append("- Trace interfaces and root causes; prefer minimal coherent repairs and do not claim runtime success without proof.")
    if "verification" in active or "reliability" in active:
        rules.append("- Run the strongest available verification path before strong factual or completion claims.")
    if "privacy" in active or "security" in active:
        rules.append("- Keep secrets out of client output, memory, logs, and generated public code.")
    if "mobile" in active:
        rules.append("- For phone UI work, prioritize native-fit viewport behavior, safe areas, reachable navigation, and no manual zoom requirement.")
    if "communication" in active:
        rules.append("- Match the requested level of detail and make the next action obvious.")
    return "\n".join(rules)
