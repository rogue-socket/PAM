from __future__ import annotations

from datetime import date, timedelta


SCENARIOS = [
    {
        "project": "Harbor Ledger",
        "alias": "HLD",
        "issue": "the freezer manifest checksum still duplicates thawed invoice lines",
        "metric_action": "prewarming ledger shards before handoff",
        "metric_value": "304ms",
        "residency": "the Reykjavik annex",
        "approver": "Mira Chen",
        "drill": "checksum board replay",
        "incident_site": "Pier 12 cold room",
        "workaround": "laminated berth stickers",
        "incident_problem": "radios dropped berth codes during sleet",
    },
    {
        "project": "Harbor Lattice",
        "alias": "HLT",
        "issue": "quay map merges still collapse split berth windows",
        "metric_action": "packing quay maps before handoff",
        "metric_value": "317ms",
        "residency": "the Bergen vault",
        "approver": "Owen Vale",
        "drill": "quay handoff simulation",
        "incident_site": "Dock 9 walkway",
        "workaround": "grease-pencil dock cards",
        "incident_problem": "tablets lost route overlays in salt fog",
    },
    {
        "project": "Cascade Forms",
        "alias": "CFM",
        "issue": "customs packets still drop handwritten cargo marks",
        "metric_action": "grouping customs pages by vessel lane",
        "metric_value": "329ms",
        "residency": "the Nuuk shelf",
        "approver": "Priya Nordin",
        "drill": "customs bundle rehearsal",
        "incident_site": "Manifest desk 3",
        "workaround": "stamped reroute slips",
        "incident_problem": "scanners skipped damp carbon copies",
    },
    {
        "project": "Drift Signals",
        "alias": "DFS",
        "issue": "storm relays still merge separate signal windows",
        "metric_action": "splitting storm relays by watch window",
        "metric_value": "341ms",
        "residency": "the Helsinki corridor",
        "approver": "Lena Brooks",
        "drill": "signal shadow drill",
        "incident_site": "Antenna 4 platform",
        "workaround": "color-coded mast flags",
        "incident_problem": "link lights vanished in freezing mist",
    },
    {
        "project": "Ember Archive",
        "alias": "EBA",
        "issue": "archive exports still pin deleted crew notes to live watchlists",
        "metric_action": "bucketing archive shards by watchday",
        "metric_value": "338ms",
        "residency": "the Oslo ledger room",
        "approver": "Rafiq Stone",
        "drill": "watchlist replay",
        "incident_site": "Records cage B",
        "workaround": "numbered audit bands",
        "incident_problem": "scanners replayed archived IDs after battery swaps",
    },
    {
        "project": "Fjord Notices",
        "alias": "FJN",
        "issue": "notice bundles still overwrite separate tide warnings",
        "metric_action": "slicing notice bundles by harbor window",
        "metric_value": "326ms",
        "residency": "the Tromso ring",
        "approver": "Alina Voss",
        "drill": "tide bulletin walkthrough",
        "incident_site": "Pier 7 notice board",
        "workaround": "magnetized tide cards",
        "incident_problem": "screens blanked during sleet gusts",
    },
    {
        "project": "Gull Registry",
        "alias": "GLR",
        "issue": "gull-noise labels still merge dock and market recordings",
        "metric_action": "splitting label batches by recorder lane",
        "metric_value": "352ms",
        "residency": "the Kirkenes shelf",
        "approver": "Samir Bale",
        "drill": "classifier replay",
        "incident_site": "Mic locker 2",
        "workaround": "wax-tagged mic sleeves",
        "incident_problem": "batteries drained below minus twelve",
    },
    {
        "project": "Harbor Sketch",
        "alias": "HBS",
        "issue": "sketch uploads still duplicate berth outlines after tunnel sync",
        "metric_action": "caching quay tiles before tunnel entry",
        "metric_value": "319ms",
        "residency": "the Tallinn vault",
        "approver": "Elena Park",
        "drill": "tunnel sync rehearsal",
        "incident_site": "Survey van bay",
        "workaround": "QR sticker packs",
        "incident_problem": "tablets lost contour layers in the underpass",
    },
    {
        "project": "Ice Dispatch",
        "alias": "ICD",
        "issue": "dispatch queues still replay stale forklift routes after reconnect",
        "metric_action": "precomputing route bundles by shift",
        "metric_value": "333ms",
        "residency": "the Nuuk annex",
        "approver": "Kaito Mori",
        "drill": "forklift handoff drill",
        "incident_site": "Freezer gate 5",
        "workaround": "thermal clipboard sheets",
        "incident_problem": "handhelds rebooted below minus ten",
    },
    {
        "project": "Jetty Claims",
        "alias": "JTC",
        "issue": "claims merges still collapse separate hull photos into one case",
        "metric_action": "grouping claim photos by hull window",
        "metric_value": "347ms",
        "residency": "the Aarhus archive room",
        "approver": "Nadia Wu",
        "drill": "hull claim audit",
        "incident_site": "Claims counter north",
        "workaround": "preprinted hull bands",
        "incident_problem": "kiosks blurred hull numbers after rain",
    },
    {
        "project": "Lantern Briefs",
        "alias": "LNB",
        "issue": "briefing drafts still reattach expired safety waivers",
        "metric_action": "partitioning brief packs by shift handover",
        "metric_value": "322ms",
        "residency": "the Malmo cabinet",
        "approver": "Imani Cole",
        "drill": "waiver review pass",
        "incident_site": "Briefing room east",
        "workaround": "clipped waiver bundles",
        "incident_problem": "printers smeared badge codes in drizzle",
    },
    {
        "project": "Meridian Cache",
        "alias": "MDC",
        "issue": "cache warmers still replay archived berth tags after failover",
        "metric_action": "invalidating warm cache by manifest revision",
        "metric_value": "308ms",
        "residency": "the Bergen annex",
        "approver": "Noah Quinn",
        "drill": "failover replay",
        "incident_site": "Cache rack 6",
        "workaround": "nylon tag strings",
        "incident_problem": "failover nodes revived retired berth tags",
    },
    {
        "project": "Northline Relay",
        "alias": "NLR",
        "issue": "relay packs still merge separate crane outages into one alert",
        "metric_action": "splitting outage packs by crane bay",
        "metric_value": "344ms",
        "residency": "the Riga shelf",
        "approver": "Amina Sorensen",
        "drill": "outage shadow test",
        "incident_site": "Crane bay 3",
        "workaround": "amber outage placards",
        "incident_problem": "blue alerts disappeared in sleet",
    },
    {
        "project": "Orion Manifests",
        "alias": "ORM",
        "issue": "manifest OCR still swaps deck codes with pallet notes",
        "metric_action": "prebinding OCR pages by deck code",
        "metric_value": "336ms",
        "residency": "the Helsinki annex",
        "approver": "Rafael Gomez",
        "drill": "OCR replay",
        "incident_site": "OCR bench west",
        "workaround": "tactile keyboard overlays",
        "incident_problem": "battery loss killed scanners below minus eleven",
    },
    {
        "project": "Prism Sync",
        "alias": "PRS",
        "issue": "sync diffs still duplicate passenger counts after ferry reconnect",
        "metric_action": "batching sync diffs by crossing window",
        "metric_value": "327ms",
        "residency": "the Gothenburg ledger room",
        "approver": "Talia Reed",
        "drill": "ferry reconnect drill",
        "incident_site": "Ferry dock south",
        "workaround": "numbered passenger strips",
        "incident_problem": "tunnels dropped sync packets mid-crossing",
    },
    {
        "project": "Tidal Atlas",
        "alias": "TDA",
        "issue": "atlas proofs still merge distinct berth polygons across tide shifts",
        "metric_action": "separating atlas proofs by tide band",
        "metric_value": "339ms",
        "residency": "the Helsinki atlas room",
        "approver": "Yusuf Karim",
        "drill": "atlas proofing session",
        "incident_site": "Chart table 4",
        "workaround": "grease-pencil polygon sheets",
        "incident_problem": "plotters skipped wet chart margins",
    },
]


NEGATIVE_TOPICS = [
    "orchard pruning ladders",
    "greenhouse humidity ribbons",
    "terrarium apricot spoons",
    "marble beehive ribbons",
    "willow canyon tablecloths",
    "velvet orchard teaspoons",
    "cocoa conservatory shutters",
    "plum meadow weathercocks",
    "ivory greenhouse umbrellas",
    "saffron apiary notebooks",
    "walnut conservatory brushes",
    "cedar orchard handbells",
    "apricot hillside cushions",
    "cocoa meadow satchels",
    "ivory terrarium needles",
    "plum orchard thimbles",
]


NEGATIVE_ESCALATIONS = [
    "terrarium velvet codicil",
    "orchard apricot addendum",
    "willow teacup petition",
    "meadow cocoa affidavit",
    "ivory plum variance",
    "saffron cedar exception",
    "marble orchid codicil",
    "walnut canyon petition",
    "velvet willow appendix",
    "apricot teacup proviso",
    "cocoa orchard schedule",
    "ivory meadow addendum",
    "plum terrarium clause",
    "saffron walnut notation",
    "cedar velvet appendix",
    "orchid marble footnote",
]


def _iso(value: date) -> str:
    return value.isoformat()


def build_hard_eval_fixture() -> dict:
    corpus: list[dict] = []
    queries: list[dict] = []
    supersedes: list[tuple[str, str]] = []
    base_day = date(2026, 8, 1)

    for index, scenario in enumerate(SCENARIOS):
        project = scenario["project"]
        alias = scenario["alias"]
        prefix = project.lower().replace(" ", "_")
        session = f"hard-eval-{index + 1}"
        note_v1_at = base_day + timedelta(days=index * 4)
        note_v2_at = note_v1_at + timedelta(days=1)
        source_at = note_v1_at + timedelta(days=2)
        url_at = note_v1_at + timedelta(days=3)
        event_at = note_v1_at + timedelta(days=4)
        incident_at = note_v1_at + timedelta(days=5)
        old_target = _iso(note_v1_at + timedelta(days=14))
        new_target = _iso(note_v1_at + timedelta(days=21))

        note_v1_key = f"{prefix}_note_v1"
        note_v2_key = f"{prefix}_note_v2"

        note_v1_text = (
            f"Idea: {project} ({alias}) target is {old_target} if the first compliance gate clears without a late redline."
        )
        note_v2_text = f"Idea: revise {project} ({alias}) target to {new_target} because {scenario['issue']}."
        source_title = f"{project} operations brief"
        source_text = (
            f"{source_title}\n\n"
            f"The revised {project} ({alias}) plan moved the target from {old_target} to {new_target} because {scenario['issue']}.\n"
            f"After {scenario['metric_action']}, operator handoff settled at {scenario['metric_value']}.\n\n"
            f"This brief is derived from the revised {project} plan so the approval trail stays inspectable.\n"
        )
        link_title = f"{project} residency note"
        link_text = (
            "<html>\n"
            "  <head>\n"
            '    <meta charset="utf-8" />\n'
            f"    <title>{link_title}</title>\n"
            "  </head>\n"
            "  <body>\n"
            f"    <h1>{link_title}</h1>\n"
            f"    <p>{project} ({alias}) snapshots stay in {scenario['residency']} until customer names are redacted.</p>\n"
            f"    <p>The boundary keeps {project} data local and auditable during handoffs.</p>\n"
            "  </body>\n"
            "</html>\n"
        )
        event_text = (
            f"{project} ({alias}) approval on {_iso(event_at)}: {scenario['approver']} signed off after the {scenario['drill']}."
        )
        incident_text = (
            f"Incident: {project} night drill at {scenario['incident_site']} stalled because {scenario['incident_problem']}. "
            f"Crews kept work moving with {scenario['workaround']} until the screens recovered."
        )

        corpus.extend(
            [
                {
                    "key": note_v1_key,
                    "session": session,
                    "ingest_kind": "note",
                    "text": note_v1_text,
                    "at": _iso(note_v1_at),
                },
                {
                    "key": note_v2_key,
                    "session": session,
                    "ingest_kind": "note",
                    "text": note_v2_text,
                    "at": _iso(note_v2_at),
                },
                {
                    "key": f"{prefix}_source",
                    "session": session,
                    "ingest_kind": "file",
                    "text": source_text,
                    "at": _iso(source_at),
                    "derived_from": note_v2_key,
                },
                {
                    "key": f"{prefix}_link",
                    "session": session,
                    "ingest_kind": "url",
                    "filename": f"{prefix}_residency_note.html",
                    "title": link_title,
                    "text": link_text,
                    "at": _iso(url_at),
                },
                {
                    "key": f"{prefix}_event",
                    "session": session,
                    "ingest_kind": "event",
                    "text": event_text,
                    "at": _iso(event_at),
                },
                {
                    "key": f"{prefix}_incident",
                    "session": session,
                    "ingest_kind": "note",
                    "text": incident_text,
                    "at": _iso(incident_at),
                },
            ]
        )
        supersedes.append((note_v1_key, note_v2_key))

        queries.extend(
            [
                {
                    "kind": "direct",
                    "query_type": "lookup",
                    "query": f"Who approved the revised {project} plan after the {scenario['drill']}?",
                    "expected_substrings": [scenario["approver"], scenario["drill"]],
                },
                {
                    "kind": "direct",
                    "query_type": "lookup",
                    "query": f"What target did {alias} move to after the revision?",
                    "expected_substrings": [project, new_target],
                    "expected_note_title_substrings": [f"Idea: revise {project} ({alias}) target to {new_target}"],
                },
                {
                    "kind": "direct",
                    "query_type": "lookup",
                    "query": f"Where must {alias} snapshots stay before redaction?",
                    "expected_substrings": [project, scenario["residency"]],
                    "expected_source_titles": [link_title],
                },
                {
                    "kind": "direct",
                    "query_type": "lookup",
                    "query": f"What fallback kept {project} moving at {scenario['incident_site']}?",
                    "expected_substrings": [scenario["incident_site"], scenario["workaround"]],
                },
                {
                    "kind": "indirect",
                    "query_type": "paraphrase",
                    "query": f"What changed handoff speed for {project} after {scenario['metric_action']}?",
                    "expected_substrings": [scenario["metric_action"], scenario["metric_value"]],
                    "expected_source_titles": [source_title],
                },
                {
                    "kind": "indirect",
                    "query_type": "paraphrase",
                    "query": f"When screens failed during the {project} night drill, what paper fallback did crews use?",
                    "expected_substrings": [scenario["incident_problem"], scenario["workaround"]],
                },
                {
                    "kind": "indirect",
                    "query_type": "relationship",
                    "query": f"What source was derived from the revised {project} plan?",
                    "expected_substrings": [source_title],
                    "expected_source_titles": [source_title],
                    "expected_relationships": [
                        {
                            "relation": "DERIVED_FROM",
                            "source_contains": f"Idea: revise {project} ({alias}) target to {new_target}",
                            "target_contains": source_title,
                        }
                    ],
                },
                {
                    "kind": "indirect",
                    "query_type": "relationship",
                    "query": f"What older {project} target was explicitly replaced by a newer note?",
                    "expected_substrings": [old_target, new_target],
                    "expected_relationships": [
                        {
                            "relation": "SUPERSEDES",
                            "source_contains": f"Idea: revise {project} ({alias}) target to {new_target}",
                            "target_contains": f"Idea: {project} ({alias}) target is {old_target}",
                        }
                    ],
                },
                {
                    "kind": "indirect",
                    "query_type": "timeline",
                    "query": f"Between {_iso(note_v2_at)} and {_iso(event_at)}, what target did {alias} move to and what brief captured the revision?",
                    "expected_substrings": [new_target, source_title],
                    "expected_source_titles": [source_title],
                },
                {
                    "kind": "indirect",
                    "query_type": "timeline",
                    "query": f"On {_iso(incident_at)}, where did the {project} night drill fail and what workaround kept things moving?",
                    "expected_substrings": [scenario["incident_site"], scenario["workaround"]],
                },
                {
                    "kind": "indirect",
                    "query_type": "negative",
                    "query": f"What do we know about {NEGATIVE_TOPICS[index]}?",
                    "expect_empty": True,
                },
                {
                    "kind": "indirect",
                    "query_type": "negative",
                    "query": f"Which {NEGATIVE_ESCALATIONS[index]} required escalation?",
                    "expect_empty": True,
                },
            ]
        )

    return {"corpus": corpus, "queries": queries, "supersedes": supersedes}