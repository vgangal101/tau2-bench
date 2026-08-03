"""
Scan airline/retail/telecom tasks.json for tasks whose reason_for_call states
more than one subgoal (see ../benchmark_analysis/subgoal_analysis.md for the
definition of "subgoal" this uses).

Heuristic, not ground truth: a task is flagged as conjunctive if its
reason_for_call contains either
  (a) two or more distinct action-verb types from a domain-specific list, or
  (b) one action verb applied to two or more distinct identifiable targets
      (order IDs, reservation codes, named items joined by "and"), or
  (c) an explicit enumeration/conjunction phrase ("also", "as well as", "in
      addition") alongside an action verb.

Run: python3 benchmark_analysis_scripts/scan_conjunctive_goals.py
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "tau2" / "domains"

# Verbs are matched only in infinitive form ("to cancel", "to exchange") to
# avoid false positives from past-tense/gerund/noun uses that don't state a
# goal (e.g. "your order #W123", "after booking", "you booked the flight").
# Chosen from each domain's actual write-tools (tools.py) plus the outcome
# words ("refund") that reliably co-occur with a stated goal.
ACTION_VERBS = {
    "retail": [
        "return", "exchange", "cancel", "refund", "replace", "modify",
        "change", "add", "remove", "upgrade", "downgrade", "swap",
    ],
    "airline": [
        "cancel", "book", "change", "modify", "upgrade", "downgrade",
        "add", "remove", "rebook", "refund", "reschedule",
    ],
    "telecom": [
        "fix", "resolve", "enable", "disable", "activate", "deactivate",
        "upgrade", "downgrade", "suspend", "resume", "unlock", "unblock",
        "dispute", "refuel", "add", "remove", "change", "cancel",
        "request", "unsubscribe", "subscribe", "reset", "restart",
    ],
}

ID_PATTERNS = {
    "retail": re.compile(r"#W\d+"),
    "airline": re.compile(r"\b[A-Z0-9]{6}\b"),
    "telecom": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
}

CONJUNCTION_PHRASES = re.compile(
    r"\balso\b|\bas well as\b|\bin addition\b|\band also\b", re.IGNORECASE
)

# Catches "exchange the keyboard ... and the thermostat ..." — one verb,
# two distinct definite/possessive-article objects joined by "and". Weaker
# signal than a second verb type, only counted alongside >=1 verb hit.
OBJECT_ENUMERATION = re.compile(
    r"\band (the|a|an|your|my)\b", re.IGNORECASE
)


NEGATION = re.compile(
    r"don'?t want to|do not want to|won'?t|refuse to|not going to|"
    r"do not|don'?t|never mind", re.IGNORECASE
)


def verb_hits(domain, text):
    # Base-form-only match (no -ed/-ing/-s alternatives): this alone screens
    # out most inflected/gerund uses that aren't goal statements ("booked",
    # "booking", "ordered") while still catching bare infinitives that share
    # a single "to" across a coordinated list ("want to return X and
    # exchange Y" — "exchange" has no "to" of its own but is still a goal).
    # A verb match preceded within 25 chars by a negation phrase ("you don't
    # want to cancel the flight") is dropped — that's a stated non-goal, not
    # a subgoal.
    text_l = text.lower()
    hits = set()
    for verb in ACTION_VERBS[domain]:
        for m in re.finditer(rf"\b{verb}\b", text_l):
            window = text_l[max(0, m.start() - 25):m.start()]
            if not NEGATION.search(window):
                hits.add(verb)
                break
    return hits


def id_count(domain, text):
    pattern = ID_PATTERNS.get(domain)
    if pattern is None:
        return 0
    return len(set(pattern.findall(text)))


def is_conjunctive(domain, text):
    hits = verb_hits(domain, text)
    ids = id_count(domain, text)
    has_conj_phrase = bool(CONJUNCTION_PHRASES.search(text))

    reasons = []
    if len(hits) >= 2:
        reasons.append(f"multiple action verbs: {sorted(hits)}")
    if ids >= 2:
        reasons.append(f"multiple target IDs ({ids})")
    if has_conj_phrase and len(hits) >= 1:
        reasons.append("explicit conjunction phrase + action verb")
    if len(hits) >= 1 and OBJECT_ENUMERATION.search(text):
        reasons.append("one verb, enumerated objects (\"and the/a/your ...\")")
    return (len(reasons) > 0), reasons


def scan_domain(domain):
    path = DATA_DIR / domain / "tasks.json"
    with open(path) as f:
        tasks = json.load(f)

    flagged = []
    for t in tasks:
        instr = t["user_scenario"]["instructions"]
        if isinstance(instr, str):
            text = instr
        else:
            text = instr.get("reason_for_call", "") or ""
        conjunctive, reasons = is_conjunctive(domain, text)
        if conjunctive:
            flagged.append({"id": t["id"], "reason_for_call": text, "why": reasons})

    return len(tasks), flagged


def main():
    summary = {}
    for domain in ["airline", "retail", "telecom"]:
        total, flagged = scan_domain(domain)
        summary[domain] = {"total": total, "flagged": len(flagged)}
        print(f"\n=== {domain}: {len(flagged)}/{total} flagged as conjunctive ===")
        for f in flagged[:15]:
            print(f"  [{f['id']}] {f['why']}")
            print(f"      {f['reason_for_call'][:160].replace(chr(10), ' ')}")

    print("\n=== summary ===")
    for domain, s in summary.items():
        pct = 100 * s["flagged"] / s["total"] if s["total"] else 0
        print(f"{domain}: {s['flagged']}/{s['total']} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
