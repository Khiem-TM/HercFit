"""Explicit, versioned prompt lookup with no network, environment or runtime state.

Keep version 1 stable. A changed instruction gets a new version and evaluation;
callers opt in rather than silently changing running agent behavior.
"""
from copy import deepcopy
from types import MappingProxyType

from agentic.prompts.v1.answer import ANSWER_PROMPT
from agentic.prompts.v1.clarification import PROMPT as CLARIFICATION_PROMPT
from agentic.prompts.v1.domains import CAPABILITY_GUIDANCE, COACH_GUIDANCE
from agentic.prompts.v1.jev import RESEARCH_QUESTIONS
from agentic.prompts.v1.memory import SUMMARY_PROMPT
from agentic.prompts.v1.research import PROMPT as RESEARCH_PROMPT
from agentic.prompts.v1.routing import GRAPH_CONTEXT_GUIDANCE, JEV_ROUTING_QUESTIONS, ROUTING_PROMPT
from agentic.prompts.v1.tool import PROMPT as TOOL_PROMPT


TEMPLATES = MappingProxyType({
    ('orchestration.route', 'v1'): ROUTING_PROMPT,
    ('orchestration.answer', 'v1'): ANSWER_PROMPT,
    ('orchestration.graph_context', 'v1'): GRAPH_CONTEXT_GUIDANCE,
    ('tool.call', 'v1'): TOOL_PROMPT,
    ('research.extract', 'v1'): RESEARCH_PROMPT,
    ('clarification.form', 'v1'): CLARIFICATION_PROMPT,
    ('memory.summary', 'v1'): SUMMARY_PROMPT,
    ('nutrition.capabilities', 'v1'): CAPABILITY_GUIDANCE,
    ('training.coach', 'v1'): COACH_GUIDANCE,
})

_QUESTIONS = {
    ('routing.jev', 'v1'): JEV_ROUTING_QUESTIONS,
    **{('research.' + phase, 'v1'): questions for phase, questions in RESEARCH_QUESTIONS.items()},
}


def get_prompt(name: str, version: str = 'v1') -> str:
    """Return the exact template; format dynamic fields only at the call site."""
    return TEMPLATES[(name, version)]


def get_questions(name: str, version: str = 'v1') -> dict:
    """Return an isolated copy so an evaluator cannot mutate another run's policy."""
    return deepcopy(_QUESTIONS[(name, version)])
