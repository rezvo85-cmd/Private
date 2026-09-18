"""RONN R17 multi-agent prompt orchestration."""
from __future__ import annotations

ROLES={
 "planner":"Turn the task into a compact execution plan. Identify dependencies, evidence needs, tests, and permission boundaries. Do not solve yet.",
 "specialist":"Solve the task as the strongest domain specialist. Be concrete. Preserve requirements. Do not claim tools ran unless evidence is supplied.",
 "critic":"Attack the proposed solution. Find factual gaps, dropped requirements, broken interfaces, security problems, and unsupported verification claims.",
 "finalizer":"Produce the final answer using the plan, specialist work, critic findings, and any real tool evidence. Resolve disagreements and keep only useful content.",
}

def messages(role,task,context=""):
    return [
      {"role":"system","content":"You are a RONN multi-agent worker. "+ROLES[role]+" Do not reveal chain-of-thought."},
      {"role":"user","content":"TASK:\n"+str(task)[:24000]+("\n\nSHARED CONTEXT:\n"+str(context)[:32000] if context else "")}
    ]

def status():
    return {"roles":list(ROLES),"architecture":"planner -> specialist -> critic -> finalizer"}
