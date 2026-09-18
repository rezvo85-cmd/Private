"""RONN R14 restricted Python execution sandbox.

This intentionally supports a safe Python subset: expressions, assignments,
print, if, lists/dicts/tuples and bounded range loops. No imports, files,
network, subprocesses, dynamic evaluation, classes, functions or dunder access.
"""
from __future__ import annotations
import ast, io, math, statistics, contextlib, time

MAX_SOURCE=8000
MAX_RANGE=1000
MAX_OUTPUT=12000

SAFE_BUILTINS={
    "abs":abs,"all":all,"any":any,"bool":bool,"dict":dict,"enumerate":enumerate,
    "float":float,"int":int,"len":len,"list":list,"max":max,"min":min,"pow":pow,
    "print":print,"range":range,"reversed":reversed,"round":round,"set":set,
    "sorted":sorted,"str":str,"sum":sum,"tuple":tuple,"zip":zip
}
SAFE_MODULES={"math":math,"statistics":statistics}
ALLOWED=(
    ast.Module,ast.Expr,ast.Assign,ast.AnnAssign,ast.AugAssign,ast.If,ast.For,
    ast.Pass,ast.Break,ast.Continue,ast.Load,ast.Store,ast.Name,ast.Constant,
    ast.List,ast.Tuple,ast.Set,ast.Dict,ast.BinOp,ast.UnaryOp,ast.BoolOp,
    ast.Compare,ast.IfExp,ast.Subscript,ast.Slice,ast.Call,ast.Attribute,
    ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,
    ast.USub,ast.UAdd,ast.Not,ast.And,ast.Or,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,
    ast.Gt,ast.GtE,ast.In,ast.NotIn
)
BLOCKED_NAMES={"__import__","eval","exec","compile","open","input","globals","locals","vars","getattr","setattr","delattr","help","dir","type","object","super","memoryview","breakpoint"}

class SandboxError(ValueError): pass

def _validate(tree):
    nodes=list(ast.walk(tree))
    if len(nodes)>900: raise SandboxError("Program is too complex for the safe sandbox.")
    if sum(1 for n in nodes if isinstance(n,ast.For))>1:
        raise SandboxError("Only one bounded loop is allowed per sandbox run.")
    for node in nodes:
        if not isinstance(node,ALLOWED): raise SandboxError(f"Blocked Python feature: {node.__class__.__name__}")
        if isinstance(node,ast.Constant) and isinstance(node.value,int) and abs(node.value)>1000000:
            raise SandboxError("Integer constant is too large.")
        if isinstance(node,ast.Name) and (node.id in BLOCKED_NAMES or node.id.startswith("__")):
            raise SandboxError(f"Blocked name: {node.id}")
        if isinstance(node,ast.Attribute):
            if node.attr.startswith("_"): raise SandboxError("Private/dunder attributes are blocked.")
            if not isinstance(node.value,ast.Name) or node.value.id not in SAFE_MODULES:
                raise SandboxError("Only safe math/statistics attributes are allowed.")
        if isinstance(node,ast.Call):
            if isinstance(node.func,ast.Name):
                if node.func.id not in SAFE_BUILTINS: raise SandboxError(f"Function not allowed: {node.func.id}")
                if node.func.id=="range":
                    if not node.args or any(not isinstance(a,ast.Constant) or not isinstance(a.value,int) for a in node.args):
                        raise SandboxError("range() arguments must be literal integers.")
                    for a in node.args:
                        if abs(a.value)>MAX_RANGE:
                            raise SandboxError("range is too large.")
            elif isinstance(node.func,ast.Attribute):
                pass
            else:
                raise SandboxError("Dynamic function calls are blocked.")
        if isinstance(node,ast.For):
            if not (isinstance(node.iter,ast.Call) and isinstance(node.iter.func,ast.Name) and node.iter.func.id=="range"):
                raise SandboxError("For loops must iterate over a bounded range().")
    return len(nodes)

def execute(source):
    source=str(source or "")
    if len(source)>MAX_SOURCE: raise SandboxError("Program is too large.")
    started=time.time()
    tree=ast.parse(source,mode="exec")
    node_count=_validate(tree)
    env={"__builtins__":SAFE_BUILTINS,**SAFE_MODULES}
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(tree,"<ronn-safe-python>","exec"),env,env)
    output=buf.getvalue()[:MAX_OUTPUT]
    public={k:v for k,v in env.items() if not k.startswith("_") and k not in SAFE_MODULES and k!="__builtins__"}
    safe_vars={}
    for k,v in list(public.items())[:30]:
        if isinstance(v,(str,int,float,bool,type(None),list,tuple,dict,set)):
            safe_vars[k]=repr(v)[:1000]
    return {"ok":True,"output":output,"variables":safe_vars,"nodes":node_count,"ms":round((time.time()-started)*1000,2),"sandbox":"restricted-python-v1"}
