"""
CSP DocMaker — what a dashboard widget is allowed to show

A Super Admin builds dashboards, but not arbitrary ones: a widget names a
metric from this registry, and nothing else. That matters for two reasons.

First, a dashboard that asks for something nobody can compute is refused
when it is saved, not when it is opened — so a built dashboard always
renders.

Second, every metric here is a deliberate query. Letting a dashboard
describe its own SQL would mean a screen that can read anything, which in a
multi-tenant system is a screen that can read another customer's data. The
registry is the list of questions this product knows how to answer.

Metrics are grouped so the builder can offer them sensibly:

  documents    what the system issued, and whether it arrived
  verification where each CSP is in confirming their own details
  data         how complete a workspace's records are
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Groups, in the order a builder should offer them.
DOCUMENTS = "documents"
VERIFICATION = "verification"
DATA = "data"

GROUP_LABELS = {
    DOCUMENTS: "Documents",
    VERIFICATION: "CSP verification",
    DATA: "Record completeness",
}

# What shape a metric returns, so the builder only offers widgets that fit.
SCALAR = "scalar"            # one number
SERIES = "series"            # name/value pairs, for a breakdown
ROWS = "rows"                # a table


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    group: str
    shape: str
    description: str
    # Which widget kinds can show it.
    widgets: tuple = ()
    # True when clicking the number should open a list of what it counted.
    drillable: bool = False


_REGISTRY: Dict[str, Metric] = {}


def register(metric: Metric) -> Metric:
    if metric.key in _REGISTRY:
        raise ValueError(f"A metric called {metric.key!r} is already registered.")
    _REGISTRY[metric.key] = metric
    return metric


def get(key: str) -> Metric:
    metric = _REGISTRY.get(key)
    if metric is None:
        raise KeyError(
            f"No metric called {key!r}. A dashboard can only show metrics "
            f"this system knows how to compute: {', '.join(sorted(_REGISTRY))}"
        )
    return metric


def exists(key: str) -> bool:
    return key in _REGISTRY


def all_metrics(group: Optional[str] = None) -> List[Metric]:
    metrics = sorted(_REGISTRY.values(), key=lambda m: (m.group, m.label))
    return [m for m in metrics if m.group == group] if group else metrics


def groups() -> List[dict]:
    """The builder's palette: every metric, grouped and labelled."""
    out = []
    for group in (DOCUMENTS, VERIFICATION, DATA):
        metrics = all_metrics(group)
        if not metrics:
            continue
        out.append({
            "group": group,
            "label": GROUP_LABELS[group],
            "metrics": [
                {
                    "key": m.key, "label": m.label, "shape": m.shape,
                    "description": m.description, "widgets": list(m.widgets),
                    "drillable": m.drillable,
                }
                for m in metrics
            ],
        })
    return out


# ---- documents: what was issued, and whether it arrived -----------------

from app.models.dashboard import BREAKDOWN, METRIC_CARD, TABLE  # noqa: E402

register(Metric(
    "documents.generated", "Documents generated", DOCUMENTS, SCALAR,
    "How many documents have been produced.",
    widgets=(METRIC_CARD, BREAKDOWN), drillable=True,
))
register(Metric(
    "documents.mailed", "Documents mailed", DOCUMENTS, SCALAR,
    "Documents that reached the CSP by email.",
    widgets=(METRIC_CARD, BREAKDOWN), drillable=True,
))
register(Metric(
    "documents.pending", "Documents pending", DOCUMENTS, SCALAR,
    "Generated but not yet sent.",
    widgets=(METRIC_CARD, BREAKDOWN), drillable=True,
))
register(Metric(
    "documents.failed", "Documents failed", DOCUMENTS, SCALAR,
    "Sending was attempted and did not succeed.",
    widgets=(METRIC_CARD, BREAKDOWN), drillable=True,
))
register(Metric(
    "documents.by_type", "Documents by type", DOCUMENTS, SERIES,
    "Generated, mailed, pending and failed for each document.",
    widgets=(TABLE, BREAKDOWN),
))

# ---- verification: where each CSP is in confirming their details --------

register(Metric(
    "verification.total", "CSPs total", VERIFICATION, SCALAR,
    "Every CSP in this workspace.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "verification.confirmed", "Confirmed by the CSP", VERIFICATION, SCALAR,
    "CSPs who opened their link and submitted their details.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "verification.waiting_on_csp", "Waiting on the CSP", VERIFICATION, SCALAR,
    "A link was sent and has not been answered yet.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "verification.not_contacted", "Not yet contacted", VERIFICATION, SCALAR,
    "No link has been sent to these CSPs.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "verification.expired", "Links expired", VERIFICATION, SCALAR,
    "A link was sent, never answered, and has now run out.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "verification.documents_held", "Documents CSPs already hold", VERIFICATION,
    ROWS,
    "Yes, No and not-yet-answered for each document. Open a row to see who "
    "said what.",
    # BREAKDOWN stays allowed so dashboards already built with it keep
    # saving; it renders from the data's shape, which is now a table.
    widgets=(TABLE, BREAKDOWN), drillable=True,
))
register(Metric(
    "verification.recent_submissions", "Recent submissions", VERIFICATION, ROWS,
    "The latest CSP submissions, newest first.",
    widgets=(TABLE,),
))

# ---- data: how complete the records are ---------------------------------

register(Metric(
    "data.complete", "Records complete", DATA, SCALAR,
    "CSPs with everything their documents need.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "data.missing_csp_details", "Missing the CSP's own details", DATA, SCALAR,
    "Blank fields only the CSP can supply.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "data.missing_org_details", "Missing hierarchy details", DATA, SCALAR,
    "Blank fields the RM or the directory must supply.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "data.missing_photo", "Missing a photograph", DATA, SCALAR,
    "No photo found in the CRM and none supplied.",
    widgets=(METRIC_CARD,), drillable=True,
))
register(Metric(
    "data.awaiting_rm", "Unresolved to an RM", DATA, SCALAR,
    "No RM could be determined, so every RM can see them.",
    widgets=(METRIC_CARD,), drillable=True,
))
