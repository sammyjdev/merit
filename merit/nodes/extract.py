"""Extract demanded skills from posting text via an injected structured runnable."""
from merit.state import MeritState

EXTRACT_PROMPT = """You extract the skills a job posting demands.

Rules:
- One entry per distinct skill or technology.
- kind is "core" when the posting requires it, "nice-to-have" when it is optional.
- quote is the shortest verbatim excerpt of the posting that demands the skill.
- Do not invent skills the posting does not mention.

Posting:
{posting}
"""


def make_extract_node(extractor):
    def extract(state: MeritState) -> dict:
        result = extractor.invoke(EXTRACT_PROMPT.format(posting=state["posting_text"]))
        return {"demands": [d.model_dump() for d in result.demands]}

    return extract
