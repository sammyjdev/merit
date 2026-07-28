"""Human approval gate. Nothing with external effect may run before interrupt()."""
from langgraph.graph import END
from langgraph.types import Command, interrupt

from merit.state import MeritState


def approval(state: MeritState) -> Command:
    payload = {"report_md": state["report_md"], "question": "Approve narrative generation?"}
    answer = interrupt(payload)
    while not isinstance(answer, bool):
        answer = interrupt({**payload, "error": "resume value must be a boolean"})
    if answer:
        return Command(update={"approved": True}, goto="narrative")
    return Command(update={"approved": False}, goto=END)
