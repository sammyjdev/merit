"""Assemble the six-node StateGraph. Models are injected; no IO here."""
from langgraph.graph import END, StateGraph

from merit.nodes.approval import approval
from merit.nodes.extract import make_extract_node
from merit.nodes.ingest import ingest
from merit.nodes.match import make_match_node
from merit.nodes.narrative import make_narrative_node
from merit.nodes.report import report
from merit.schemas import Profile
from merit.state import MeritState
from merit.telemetry import traced_node


def build_graph(profile: Profile, extractor, judge, writer, checkpointer):
    g = StateGraph(MeritState)
    g.add_node("ingest", traced_node("ingest")(ingest))
    g.add_node("extract", traced_node("extract")(make_extract_node(extractor)))
    g.add_node("match", traced_node("match")(make_match_node(profile, judge)))
    g.add_node("report", traced_node("report")(report))
    g.add_node("approval", traced_node("approval")(approval), ends=("narrative", END))
    g.add_node("narrative", traced_node("narrative")(make_narrative_node(writer)))
    g.set_entry_point("ingest")
    g.add_edge("ingest", "extract")
    g.add_edge("extract", "match")
    g.add_edge("match", "report")
    g.add_edge("report", "approval")
    g.add_edge("narrative", END)
    return g.compile(checkpointer=checkpointer)
