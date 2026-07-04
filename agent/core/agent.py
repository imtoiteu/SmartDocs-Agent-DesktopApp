"""Agent Core — model-agnostic orchestration loop.

Flow (SmartDocs-Agent/CLAUDE.md → Agent Workflow):

    analyze (plan) → select skill/tool → execute → observe → repeat → synthesize

The Agent Core contains orchestration ONLY — no business logic. Capabilities
come from the Tool Registry and (optionally) the Skill Registry; text generation
comes from an ``LLMProvider``. The tool/skill-calling protocol is a simple,
model-neutral JSON contract, so it works with any text LLM (local Qwen today, an
API model tomorrow) without changing this loop.

Phase 7 adds two opt-in capabilities, both off by default so the existing
contract is unchanged:
* ``enable_planning`` — a single up-front analysis pass that drafts a short plan
  which then guides execution;
* ``skills`` — a Skill Registry the agent may select from, alongside tools, using
  a ``{"skill": ...}`` action. Tenancy for skills is injected via the
  ``SkillContext`` per run (the LLM never chooses the scope).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..tools import ToolRegistry, get_registry
from .provider import LLMProvider, Message, get_default_provider

if TYPE_CHECKING:                       # hints only — avoids an import cycle at runtime
    from ..skills import SkillContext, SkillRegistry

# Cap the size of an observation fed back into the prompt (OCR results etc. can
# be large, including base64 images). The full observation is kept on the step.
_OBS_MAX_CHARS = 1500

# Cap the Sources surfaced for an answer to one retrieval's worth — the most
# relevant chunks actually retrieved during the run, never the user's whole library.
# Matches the per-query retrieval breadth (chat_service.TOP_K / knowledge top_k = 5)
# so repeated or corpus-wide lookups can't accumulate into an ever-growing list.
_MAX_CITATIONS = 5


@dataclass
class AgentStep:
    kind: str                                    # "tool" | "skill" | "final"
    tool: Optional[str] = None                   # tool OR skill name for this step
    arguments: Dict[str, Any] = field(default_factory=dict)
    observation: Optional[Dict[str, Any]] = None  # ToolResult/SkillResult.to_dict()
    raw: Optional[str] = None                     # raw model text for this step


@dataclass
class AgentResult:
    answer: str
    steps: List[AgentStep] = field(default_factory=list)
    completed: bool = True                        # False if max_steps/time hit first
    provider: Optional[str] = None
    plan: Optional[str] = None                    # up-front plan, when planning is on
    citations: List[Dict[str, Any]] = field(default_factory=list)  # merged evidence
    timed_out: bool = False                       # True when the time budget ended the run

    def tool_calls(self) -> List[str]:
        return [s.tool for s in self.steps if s.kind == "tool" and s.tool]

    def skill_calls(self) -> List[str]:
        return [s.tool for s in self.steps if s.kind == "skill" and s.tool]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "completed": self.completed,
            "timed_out": self.timed_out,
            "provider": self.provider,
            "plan": self.plan,
            "tool_calls": self.tool_calls(),
            "skill_calls": self.skill_calls(),
            "citations": self.citations,
            "steps": [
                {"kind": s.kind, "tool": s.tool, "arguments": s.arguments,
                 "observation": s.observation}
                for s in self.steps
            ],
        }


def _extract_json(text: str) -> Optional[dict]:
    """Return the first balanced top-level JSON object in ``text``, or None.

    Tolerates leading prose and ``` fences, and respects braces that appear
    inside string values.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = text[start:i + 1]
                        try:
                            obj = json.loads(chunk)
                            if isinstance(obj, dict):
                                return obj
                        except Exception:
                            break  # malformed — try the next '{'
        start = text.find("{", start + 1)
    return None


class AgentCore:
    """Orchestrates tool/skill use over an LLM provider and the registries."""

    def __init__(self, registry: Optional[ToolRegistry] = None,
                 provider: Optional[LLMProvider] = None,
                 max_steps: int = 5,
                 tenancy_tools=("chat", "knowledge_search"),
                 skills: Optional["SkillRegistry"] = None,
                 skill_context: Optional["SkillContext"] = None,
                 enable_planning: bool = False,
                 time_budget_s: Optional[float] = None,
                 on_progress=None) -> None:
        self.registry = registry or get_registry()
        self.provider = provider or get_default_provider()
        self.max_steps = max_steps
        # Tools whose calls must be scoped to the caller's documents. The agent
        # (not the LLM) injects allowed_file_ids — preserving the file ownership
        # invariant. The LLM never sees or chooses this argument.
        self.tenancy_tools = set(tenancy_tools)
        # Optional Skill selection. ``skills`` is None → skill selection is
        # disabled and the loop behaves exactly as before. ``skill_context`` is
        # the base context; tenancy scope is injected per run.
        self.skills = skills
        self.skill_context = skill_context
        self.enable_planning = enable_planning
        # Wall-clock budget for one run (seconds). When exceeded the loop stops
        # starting new tool steps and goes straight to synthesis — a long run
        # ends safely with an answer from what it has, instead of hanging the
        # request. None = unbounded (the prior contract).
        self.time_budget_s = time_budget_s
        # Optional progress callback, called with one dict per phase change
        # (planning / thinking / acting / synthesis). Purely observational and
        # best-effort — a raising callback never breaks the run.
        self.on_progress = on_progress

    def _emit(self, **event) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(dict(event))
        except Exception:                       # progress must never break a run
            pass

    # ── prompt construction ─────────────────────────────────────────────────────
    def _system_prompt(self) -> str:
        lines = [
            "You are SmartDocs Agent, an orchestrator that fulfils the user's "
            "request by calling tools and skills and then answering.",
            "",
            "Available tools:",
        ]
        for spec in self.registry.specs():
            lines.append(f"- {spec['name']}: {spec['description']}")
            lines.append(f"  arguments schema: {json.dumps(spec['parameters'])}")
        # Only advertise skills when there actually are some — an empty registry
        # (e.g. a pure-tool agent) omits the section AND the skill action entirely.
        skill_specs = self.skills.specs() if self.skills is not None else []
        if skill_specs:
            lines += [
                "",
                "Available skills (higher-level workflows that orchestrate several "
                "tools; prefer a skill when one matches the request):",
            ]
            for spec in skill_specs:
                lines.append(f"- {spec['name']}: {spec['description']}")
                lines.append(f"  arguments schema: {json.dumps(spec['parameters'])}")
        lines += [
            "",
            "Protocol — reply with EXACTLY ONE JSON object and nothing else:",
            '  to call a tool:    {"tool": "<name>", "arguments": { ... }}',
        ]
        if skill_specs:
            lines.append('  to run a skill:    {"skill": "<name>", "arguments": { ... }}')
        lines += [
            '  to answer finally: {"final": "<your answer>"}',
            "Arguments must match the schema. Do not wrap the JSON in markdown "
            "fences. Take one action at a time and use the observation that comes "
            "back before deciding the next step.",
            "",
            "Grounding: when the user asks about their documents or an attached "
            "document, retrieve evidence FIRST (a retrieval tool such as "
            "'knowledge_search' or 'chat', or the attached document text in this "
            "conversation) and base your answer on it. If you answer a "
            "document-related question without having checked any document, say "
            "so explicitly in your answer.",
        ]
        return "\n".join(lines)

    def _initial_messages(self, user_message: str,
                          history: Optional[List[Message]]) -> List[Message]:
        msgs: List[Message] = [{"role": "system", "content": self._system_prompt()}]
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_message})
        return msgs

    @staticmethod
    def _format_observation(name: str, result) -> str:
        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        if len(payload) > _OBS_MAX_CHARS:
            payload = payload[:_OBS_MAX_CHARS] + "…(truncated)"
        return f"Observation from '{name}': {payload}"

    # ── citations ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _observation_citations(observation: Optional[Dict[str, Any]]) -> List[dict]:
        """Pull citation-shaped dicts out of a tool/skill observation.

        ``knowledge_search`` and the ``research`` skill expose ``data.citations``;
        the ``chat`` tool exposes ``data.sources`` (same {file_id, score, excerpt}
        shape). Anything without a ``file_id`` is ignored.
        """
        data = (observation or {}).get("data") or {}
        out: List[dict] = []
        for key in ("citations", "sources"):
            items = data.get(key)
            if isinstance(items, list):
                out.extend(d for d in items if isinstance(d, dict) and d.get("file_id"))
        return out

    @staticmethod
    def _finalize_citations(cite_dicts: List[dict]) -> List[dict]:
        """Normalize, de-duplicate, rank and CAP the citations gathered across steps.

        The Sources surfaced for an answer represent the retrieval set that fed it —
        the most relevant chunks actually retrieved during the run — ranked by score
        and capped to the per-query retrieval breadth (``_MAX_CITATIONS``). This keeps
        repeated or corpus-wide lookups from accumulating into the user's whole library.
        """
        from ..knowledge import Citation, merge_citations  # lazy: keep import light

        merged = merge_citations([Citation.from_dict(d) for d in cite_dicts],
                                 top_k=_MAX_CITATIONS)
        return [c.to_dict() for c in merged]

    # ── planning ─────────────────────────────────────────────────────────────────
    def _make_plan(self, messages: List[Message]) -> Optional[str]:
        """One up-front analysis pass → a short plain-text plan, or None.

        Robust by design: any failure, an empty answer, or a model that ignores
        the instruction and emits JSON yields None, and the normal loop proceeds.
        """
        instruction = (
            "Before taking any action, analyze the request and briefly outline "
            "your plan: which tools or skills you will use and in what order. "
            "Answer in 1-3 short sentences of plain text. Do NOT call anything or "
            "output JSON yet."
        )
        try:
            raw = self.provider.complete(
                list(messages) + [{"role": "user", "content": instruction}],
                max_tokens=256, temperature=0.0)
        except Exception:                         # planning must never break a run
            return None
        text = (raw or "").strip()
        if not text or text.startswith("{") or text.startswith("```"):
            return None                            # JSON/empty → no usable plan
        return text

    # ── main loop ────────────────────────────────────────────────────────────────
    def run(self, user_message: str, *, history: Optional[List[Message]] = None,
            allowed_file_ids: Optional[set] = None) -> AgentResult:
        t0 = time.monotonic()
        messages = self._initial_messages(user_message, history)
        steps: List[AgentStep] = []
        cite_dicts: List[dict] = []                   # raw citations gathered across steps

        def out_of_time() -> bool:
            return (self.time_budget_s is not None
                    and time.monotonic() - t0 >= self.time_budget_s)

        # Per-run skill context with the caller's tenancy scope injected (the LLM
        # never chooses the scope). None scope (admin) keeps the base context.
        run_ctx = None
        if self.skills is not None and self.skill_context is not None:
            run_ctx = (replace(self.skill_context, allowed_file_ids=allowed_file_ids)
                       if allowed_file_ids is not None else self.skill_context)

        # Planning (optional) — analyze the request, then guide execution by it.
        if self.enable_planning:
            self._emit(phase="planning")
        plan = self._make_plan(messages) if self.enable_planning else None
        if plan:
            messages.append({"role": "assistant", "content": "Plan: " + plan})
            messages.append({"role": "user", "content":
                "Now carry out the plan. Reply with exactly one JSON action "
                "(a tool call, a skill call, or a final answer) per step."})

        timed_out = False
        for step_no in range(1, self.max_steps + 1):
            # Wall-clock gate: past the budget, take no more actions — fall
            # through to the synthesis pass so the run still ends with an answer.
            if out_of_time():
                timed_out = True
                break
            self._emit(phase="thinking", step=step_no, max_steps=self.max_steps)
            raw = self.provider.complete(messages)
            action = _extract_json(raw)

            tool_name = action.get("tool") if action else None
            skill_name = action.get("skill") if action else None

            # No actionable JSON, or an explicit final → answer.
            if not action or (tool_name is None and skill_name is None):
                if action and isinstance(action.get("final"), str):
                    answer = action["final"]
                else:
                    answer = (raw or "").strip()
                steps.append(AgentStep(kind="final", raw=raw))
                return AgentResult(answer=answer, steps=steps, completed=True,
                                   provider=getattr(self.provider, "name", None), plan=plan,
                                   citations=self._finalize_citations(cite_dicts))

            # Resolve the requested capability. Be lenient when the (weak) model
            # puts a name in the wrong slot.
            if skill_name is not None:
                kind, name = "skill", str(skill_name)
            else:
                kind, name = "tool", str(tool_name)
            args = action.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}

            has_skill = self.skills is not None and self.skills.has(name)
            has_tool = self.registry.has(name)
            if kind == "skill" and not has_skill:
                kind = "tool"                      # skills off / unknown skill → tool slot
            elif kind == "tool" and not has_tool and has_skill:
                kind = "skill"                     # skill name placed in the tool slot

            self._emit(phase="acting", step=step_no, max_steps=self.max_steps,
                       kind=kind, name=name)
            if kind == "skill":
                result = self.skills.run(name, run_ctx, **args)     # SkillResult
            else:
                call_args = dict(args)
                if name in self.tenancy_tools and allowed_file_ids is not None:
                    call_args["allowed_file_ids"] = allowed_file_ids
                result = self.registry.run(name, **call_args)       # ToolResult

            observation = result.to_dict()
            cite_dicts.extend(self._observation_citations(observation))
            steps.append(AgentStep(kind=kind, tool=name, arguments=args,
                                   observation=observation, raw=raw))
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": self._format_observation(name, result)})

        # max_steps or time budget exhausted → one synthesis pass, no more tools.
        self._emit(phase="synthesis")
        messages.append({
            "role": "user",
            "content": ("Time is up. " if timed_out else "")
                       + "Stop calling tools. Give your best final answer now as "
                         "plain text, based on the observations you already have.",
        })
        final_raw = self.provider.complete(messages)
        answer = (final_raw or "").strip()
        maybe = _extract_json(final_raw)
        if maybe and isinstance(maybe.get("final"), str):
            answer = maybe["final"]
        steps.append(AgentStep(kind="final", raw=final_raw))
        return AgentResult(answer=answer, steps=steps, completed=False,
                           provider=getattr(self.provider, "name", None), plan=plan,
                           citations=self._finalize_citations(cite_dicts),
                           timed_out=timed_out)
