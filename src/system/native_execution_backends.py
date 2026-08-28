#!/usr/bin/env python3
"""Optional bounded execution accelerators beneath Hermes graph authority."""
from __future__ import annotations
import asyncio, inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

from execution_state import ExecutionStateLedger, digest

class ExecutionBackendError(ValueError): pass

@dataclass(frozen=True)
class ProgrammaticResult:
    data: Any
    trace: tuple[dict[str, Any], ...]

@dataclass(frozen=True)
class MultiAgentResult:
    data: Any
    subagent_results: tuple[Any, ...]

async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value

def _resolve(value: Any, state: Mapping[str, Any]) -> Any:
    if isinstance(value, dict) and set(value)=={'$ref'}:
        parts=str(value['$ref']).split('.')
        if not parts[0] or parts[0] not in state: raise ExecutionBackendError(f"unknown result reference: {value['$ref']}")
        cur=state[parts[0]]
        for part in parts[1:]:
            if not isinstance(cur, Mapping) or part not in cur: raise ExecutionBackendError(f"unresolved result reference: {value['$ref']}")
            cur=cur[part]
        return cur
    if isinstance(value, dict): return {k:_resolve(v,state) for k,v in value.items()}
    if isinstance(value, list): return [_resolve(v,state) for v in value]
    return value

class ProgrammaticToolExecutor:
    """Execute a pre-bounded tool plan; it cannot expand its own authority."""
    def __init__(
        self, tools: Mapping[str, Callable[..., Any]], *, allowed_tools: set[str], max_calls: int=16,
        state_ledger: ExecutionStateLedger | None = None,
    ):
        self.tools=dict(tools); self.allowed_tools=frozenset(allowed_tools); self.max_calls=max_calls; self.state_ledger=state_ledger
        if max_calls < 1: raise ExecutionBackendError("max_calls must be positive")
    async def run(self, steps: Sequence[Mapping[str, Any]]) -> ProgrammaticResult:
        if len(steps)>self.max_calls: raise ExecutionBackendError("program exceeds bounded tool-call limit")
        state={}; trace=[]; result=None
        for index,step in enumerate(steps):
            tool=str(step.get('tool',''))
            if tool not in self.allowed_tools or tool not in self.tools: raise ExecutionBackendError(f"tool not authorized for programmatic execution: {tool}")
            args=_resolve(step.get('args',{}),state)
            if not isinstance(args,dict): raise ExecutionBackendError("tool args must be an object")
            requires=step.get('requires',[])
            mutates=step.get('mutates',[])
            if not isinstance(requires,list) or any(not isinstance(x,str) or not x for x in requires):
                raise ExecutionBackendError("requires must be a string list")
            if not isinstance(mutates,list) or any(not isinstance(x,str) or not x for x in mutates):
                raise ExecutionBackendError("mutates must be a string list")
            reused=False
            operation=f"programmatic-tool:{tool}"
            reuse_allowed = bool(step.get('reusable', bool(requires))) and not mutates
            if self.state_ledger is not None and reuse_allowed:
                decision=self.state_ledger.preflight(operation,args,requires=tuple(requires))
                if decision.action=='reuse_success':
                    result=decision.result
                    reused=True
            if not reused:
                try:
                    result=await _await(self.tools[tool](**args))
                except Exception as exc:
                    if self.state_ledger is not None:
                        self.state_ledger.record_attempt(operation,args,status='failed',result={'error':f'{type(exc).__name__}: {exc}'},requires=tuple(requires))
                    raise
                if self.state_ledger is not None:
                    self.state_ledger.record_attempt(operation,args,status='success',result=result,requires=tuple(requires))
                    for resource in mutates:
                        self.state_ledger.record_mutation(resource,digest({'tool':tool,'args':args,'result':result,'resource':resource}),source=f'tool:{tool}')
            save_as=step.get('save_as')
            if save_as:
                if not isinstance(save_as,str) or not save_as.isidentifier(): raise ExecutionBackendError("save_as must be an identifier")
                state[save_as]=result
            trace.append({'index':index,'tool':tool,'args':args,'save_as':save_as,'reused':reused,'requires':list(requires),'mutates':list(mutates)})
        return ProgrammaticResult(result,tuple(trace))

class NativeMultiAgentExecutor:
    """Parallelize caller-supplied bounded subtasks, then synthesize once."""
    def __init__(self, worker: Callable[[Any], Any], synthesizer: Callable[[Sequence[Any]], Any], *, max_subagents: int=4):
        if max_subagents < 1: raise ExecutionBackendError("max_subagents must be positive")
        self.worker=worker; self.synthesizer=synthesizer; self.max_subagents=max_subagents
    async def run(self, subtasks: Sequence[Any]) -> MultiAgentResult:
        sem=asyncio.Semaphore(self.max_subagents)
        async def one(task):
            async with sem: return await _await(self.worker(task))
        rows=tuple(await asyncio.gather(*(one(x) for x in subtasks)))
        data=await _await(self.synthesizer(rows))
        return MultiAgentResult(data,rows)
