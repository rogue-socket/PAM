from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
CLI = REPO_ROOT / "cli.py"
EVAL_ROOT = Path(__file__).resolve().parent
RUN_ROOT = EVAL_ROOT / "run"
ARTICLES_ROOT = RUN_ROOT / "articles"
LINKS_ROOT = RUN_ROOT / "links"
DATASET_PATH = EVAL_ROOT / "dataset_snapshot.json"
RESULTS_PATH = EVAL_ROOT / "results.json"
SUMMARY_PATH = EVAL_ROOT / "results_summary.md"

FIRST_RESULT_PATTERN = re.compile(r"^\s*1\.\s+\[(?P<node_type>[^\]]+)\]\s+(?P<label>.+)$")
NODE_ID_PATTERN = re.compile(r"^(?:Added|Already exists):\s+([^\s]+)$")


def clean(text: str) -> str:
    return dedent(text).strip() + "\n"


def html_page(title: str, *paragraphs: str) -> str:
    body = "\n".join(f"    <p>{paragraph}</p>" for paragraph in paragraphs)
    return clean(
        f"""
        <html>
          <head>
            <meta charset="utf-8" />
            <title>{title}</title>
          </head>
          <body>
            <h1>{title}</h1>
{body}
          </body>
        </html>
        """
    )


def note(key: str, session: str, category: str, text: str, at: str) -> dict:
    return {
        "key": key,
        "session": session,
        "category": category,
        "ingest_kind": "note",
        "text": clean(text).strip(),
        "at": at,
    }


def event(key: str, session: str, text: str, at: str) -> dict:
    return {
        "key": key,
        "session": session,
        "category": "event",
        "ingest_kind": "event",
        "text": clean(text).strip(),
        "at": at,
    }


def file_item(
    key: str,
    session: str,
    filename: str,
    text: str,
    at: str,
    derived_from: str | None = None,
) -> dict:
    return {
        "key": key,
        "session": session,
        "category": "article",
        "ingest_kind": "file",
        "filename": filename,
        "text": clean(text),
        "at": at,
        "derived_from": derived_from,
    }


def url_item(
    key: str,
    session: str,
    filename: str,
    title: str,
    at: str,
    *paragraphs: str,
    derived_from: str | None = None,
) -> dict:
    return {
        "key": key,
        "session": session,
        "category": "link",
        "ingest_kind": "url",
        "filename": filename,
        "text": html_page(title, *paragraphs),
        "title": title,
        "at": at,
        "derived_from": derived_from,
    }


CORPUS: list[dict] = [
    note(
        "arch_note_contradictions",
        "architecture",
        "idea",
        """
        Idea: keep contradictory ship notices as sibling notes instead of overwriting them;
        the later correction should supersede the earlier note so history stays readable.
        """,
        "2026-03-13",
    ),
    note(
        "arch_note_session_names",
        "architecture",
        "idea",
        """
        Idea: session names should follow harbor-date-topic, like bergen-2026-03-cold-start,
        so incident review and query sessions stay easy to compare.
        """,
        "2026-03-13",
    ),
    file_item(
        "arch_file_harborcache",
        "architecture",
        "harborcache_design_note.md",
        """
        HarborCache design note

        The HarborCache prototype pre-bakes berth dictionaries each dawn before vessels leave the quay.
        That change cut cold query time from 900ms to 280ms without increasing the tablet budget.

        The design note also capped memory use at 512 MB per vessel tablet and called out stale tug manifests
        as the main red-team risk for cached retrieval packs.
        """,
        "2026-03-14",
    ),
    file_item(
        "arch_file_ranking",
        "architecture",
        "ranking_postmortem.md",
        """
        Retrieval ranking postmortem

        Nadia Wu signed off the retrieval ranking fix on 2026-03-14 after Rafael Gomez replayed the full regression pack.
        The revised scorer prefers provenance before freshness whenever scores tie.

        The same postmortem notes that the shadow index should run every Friday at 04:30 UTC so ranking drift
        can be measured before the weekend pilot load arrives.
        """,
        "2026-03-14",
    ),
    url_item(
        "arch_url_graph_expansion",
        "architecture",
        "graph_expansion_memo.html",
        "Graph expansion memo",
        "2026-03-15",
        "The graph expansion depth remains 2 because deeper walks started blending berth history with unrelated dispatch notes.",
        "Edges below 0.35 are skipped during expansion, and RELATED edges are only considered after direct hits exceed two nodes.",
    ),
    url_item(
        "arch_url_parser_fallback",
        "architecture",
        "parser_fallback_guide.html",
        "Parser fallback guide",
        "2026-03-16",
        "The fallback parser drops stop words, keeps up to 5 keywords, and recognizes between, after, and before as timeline hints.",
        "Engineers were told to keep explicit dates in ISO form so the parser could preserve reliable time windows.",
    ),
    note(
        "arch_tweet_latency",
        "architecture",
        "tweet",
        """
        Tweet: We cut cold query time from 900ms to 280ms by pre-baking harbor dictionaries instead of chasing bigger GPUs.
        """,
        "2026-03-14",
    ),
    note(
        "arch_tweet_metric",
        "architecture",
        "tweet",
        """
        Tweet: Stop celebrating abstract benchmarks; during pilot week the only metric that mattered was first useful answer under three seconds.
        """,
        "2026-03-15",
    ),
    event(
        "arch_event_approval",
        "architecture",
        """
        Architecture review on 2026-03-14: Nadia Wu approved the HarborCache rollout after Rafael Gomez demonstrated the regression pack replay.
        """,
        "2026-03-14",
    ),
    event(
        "arch_event_parser_bug",
        "architecture",
        """
        Parser patch test on 2026-03-16: fallback parsing failed on the phrase after the crane outage until the date normalizer was fixed.
        """,
        "2026-03-16",
    ),
    note(
        "field_note_forms",
        "field",
        "idea",
        """
        Idea: bundle paper customs forms with QR stickers so crews can rescan them into Tideglass when the ferry tunnel returns connectivity.
        """,
        "2026-02-10",
    ),
    note(
        "field_note_cleaning_schedule",
        "field",
        "idea",
        """
        Idea: schedule antenna cleaning every second Tuesday after gull nesting season,
        because salt fog and feathers keep fouling antenna 3.
        """,
        "2026-02-10",
    ),
    file_item(
        "field_file_pilot",
        "field",
        "northline_pilot_field_report.md",
        """
        Northline pilot field report

        The Bergen pilot ran from Dock 14, where solar relays survived sleet better than expected.
        Salt fog corroded antenna 3, and the night shift kept asking for warmer visual treatments during late scans.

        Operators said the offline map felt more trustworthy than older clipboard workflows once the pilot reached full night-shift use.
        """,
        "2026-02-11",
    ),
    file_item(
        "field_file_sync",
        "field",
        "offline_sync_handbook.md",
        """
        Offline sync handbook

        Whispergrid batches updates every 17 minutes and compacts attachments over 12 MB before the next ferry transfer.
        Ferry mode exists for dead zones between tunnels and quays where crews still need steady replayable sync.

        The handbook warns teams not to assume continuous backhaul during dock handoffs, especially during snow and sleet.
        """,
        "2026-02-12",
    ),
    url_item(
        "field_url_battery",
        "field",
        "freezer_battery_memo.html",
        "Freezer battery memo",
        "2026-02-13",
        "Below -12C the freezer packs lost 18 percent capacity during the first hour of a shift.",
        "A warm pocket sleeve solved the battery loss without changing the charger routine.",
    ),
    url_item(
        "field_url_cleaning",
        "field",
        "sensor_cleaning_bulletin.html",
        "Sensor cleaning bulletin",
        "2026-02-14",
        "Imani Cole posted the bulletin after finding alcohol haze on a lidar lens after sleet cleanup.",
        "The instruction is to rinse the lidar lens with deionized water, not alcohol.",
    ),
    note(
        "field_tweet_clipboard",
        "field",
        "tweet",
        """
        Tweet: The pilot only felt real when crane operator Marta said the offline map beat the laminated clipboard.
        """,
        "2026-02-15",
    ),
    note(
        "field_tweet_ferry",
        "field",
        "tweet",
        """
        Tweet: Ferry mode is boring in the best possible way; people stop noticing sync when it survives tunnels.
        """,
        "2026-02-16",
    ),
    event(
        "field_event_antenna",
        "field",
        """
        Bergen drill on 2026-02-11: antenna 3 failed after salt fog, so the team switched to the ceramic mast.
        """,
        "2026-02-11",
    ),
    event(
        "field_event_alerts",
        "field",
        """
        Northline night shift on 2026-02-19 asked for amber alerts instead of blue because blue vanished in sleet.
        """,
        "2026-02-19",
    ),
    note(
        "policy_note_vendor_v1",
        "policy",
        "idea",
        """
        Idea: Cobalt Scan might be acceptable if Cedar stays more than twelve percent above budget,
        because price pressure is still real.
        """,
        "2026-01-26",
    ),
    note(
        "policy_note_vendor_v2",
        "policy",
        "idea",
        """
        Idea: Cedar OCR should remain the preferred vendor because its audit export removes two hours from every customs review even with a nine percent premium.
        """,
        "2026-01-27",
    ),
    file_item(
        "policy_file_residency",
        "policy",
        "data_residency_memo.md",
        """
        Data residency memo

        Customer traces from EU harbors stay in the Helsinki region, and raw berth photos never leave that regional boundary.
        Derived embeddings may replicate to Dublin only after redaction removes berth-sensitive detail.

        The memo frames regional handling as a trust requirement, not just a legal box-checking exercise.
        """,
        "2026-01-28",
    ),
    file_item(
        "policy_file_ocr_review",
        "policy",
        "ocr_vendor_review.md",
        """
        OCR vendor review

        Cedar OCR beat Cobalt Scan on handwritten manifests sampled from Nuuk and Bergen.
        Elena Park preferred Cedar despite a 9 percent higher price because the audit export saved two hours in every customs review.

        The review concluded that explainable exports mattered more than lowest-cost scoring on messy forms.
        """,
        "2026-01-29",
        derived_from="policy_note_vendor_v2",
    ),
    url_item(
        "policy_url_retention",
        "policy",
        "retention_faq.html",
        "Retention FAQ",
        "2026-01-30",
        "Raw voice clips are deleted after 21 days unless an incident flag extends the window to 90 days.",
        "Transcript summaries can stay longer because they are treated as derived notes rather than raw recordings.",
    ),
    url_item(
        "policy_url_safety",
        "policy",
        "safety_brief.html",
        "Safety brief",
        "2026-02-02",
        "The roof-scan drone was canceled because winds exceeded 35 knots before launch.",
        "Harbor master Jonas Hale halted the roof scan before the team cleared the pad.",
    ),
    note(
        "policy_tweet_compliance",
        "policy",
        "tweet",
        """
        Tweet: Compliance wins rarely look glamorous; sometimes they are just proof that Dublin never sees an unredacted berth note.
        """,
        "2026-01-31",
    ),
    note(
        "policy_tweet_cedar",
        "policy",
        "tweet",
        """
        Tweet: Cedar's audit export is not flashy, but it erased two hours from every customs review.
        """,
        "2026-01-31",
    ),
    event(
        "policy_event_autorenew",
        "policy",
        """
        Procurement call on 2026-01-28: Elena Park asked legal to strike the Cobalt auto-renew clause.
        """,
        "2026-01-28",
    ),
    event(
        "policy_event_drone",
        "policy",
        """
        Safety review on 2026-02-02: the roof-scan drone was grounded after 38-knot gusts.
        """,
        "2026-02-02",
    ),
    note(
        "research_note_apprentices",
        "research",
        "idea",
        """
        Idea: let apprentices bookmark surprising tide shifts and narrate why they matter in their own words.
        """,
        "2026-03-01",
    ),
    note(
        "research_note_confusion",
        "research",
        "idea",
        """
        Idea: compare gull-noise confusion against crane squeal before retraining the acoustic model.
        """,
        "2026-03-01",
    ),
    file_item(
        "research_file_workshop",
        "research",
        "community_workshop_transcript.md",
        """
        Community workshop transcript

        Kaito Mori moderated the fishery cooperative workshop and collected twelve plain-language tide labels.
        Youth fellows preferred annotated maps over chat transcripts when they explained harbor changes to newcomers.

        The transcript closed by asking the team to keep community wording intact instead of translating everything into lab jargon.
        """,
        "2026-03-03",
        derived_from="research_note_apprentices",
    ),
    file_item(
        "research_file_acoustic",
        "research",
        "acoustic_experiment_log.md",
        """
        Acoustic experiment log

        The gull-noise classifier recall improved from 0.61 to 0.78 after adding foghorn negatives.
        Samir Bale accepted the precision dip because false positives still mostly came from crane squeal.

        The log recommended keeping the new negatives through the next harbor storm cycle before any additional pruning.
        """,
        "2026-03-07",
    ),
    url_item(
        "research_url_arrows",
        "research",
        "observation_deck_notes.html",
        "Observation deck notes",
        "2026-03-04",
        "Visitors remembered color-coded berth arrows better than numeric lane IDs during quick orientation tests.",
        "An orange arrow outperformed lane 7 in recall even when the briefing time was cut in half.",
    ),
    url_item(
        "research_url_accessibility",
        "research",
        "accessibility_page.html",
        "Accessibility page",
        "2026-03-05",
        "Captions default on for field video, and the reading interface starts at 115 percent font scale.",
        "A tactile keyboard shipped to Kirkenes for the next cold-weather accessibility round.",
    ),
    note(
        "research_tweet_storm_handwriting",
        "research",
        "tweet",
        """
        Tweet: The youth fellows ignored our tidy taxonomy and invented the phrase storm handwriting for messy tide logs.
        """,
        "2026-03-06",
    ),
    note(
        "research_tweet_arrows",
        "research",
        "tweet",
        """
        Tweet: Best note of the month: users trusted arrows before they trusted probabilities.
        """,
        "2026-03-06",
    ),
    event(
        "research_event_workshop",
        "research",
        """
        Cooperative workshop on 2026-03-03: Kaito Mori collected twelve examples of plain-language tide labels.
        """,
        "2026-03-03",
    ),
    event(
        "research_event_dataset",
        "research",
        """
        Acoustic review on 2026-03-07: Samir Bale approved the foghorn-negative dataset expansion.
        """,
        "2026-03-07",
    ),
    note(
        "launch_note_target_v1",
        "launch",
        "idea",
        """
        Idea: the public launch target is 2026-04-18 if invoice export clears final QA this week.
        """,
        "2026-04-05",
    ),
    note(
        "launch_note_target_v2",
        "launch",
        "idea",
        """
        Idea: revise the public launch target to 2026-04-26 because invoice export still rounds fuel surcharges incorrectly.
        """,
        "2026-04-12",
    ),
    file_item(
        "launch_file_checklist",
        "launch",
        "launch_checklist.md",
        """
        Launch checklist

        The public launch moved from 2026-04-18 to 2026-04-26 after the invoice export bug held the release train.
        The public demo speaker was Amina Sorensen, and the freeze window starts on 2026-04-24.

        The checklist warns against mixing live demo infrastructure with unfinished billing workflows.
        """,
        "2026-04-12",
        derived_from="launch_note_target_v2",
    ),
    file_item(
        "launch_file_incident",
        "launch",
        "orca7_incident_retrospective.md",
        """
        ORCA-7 incident retrospective

        ORCA-7 began when a stale customs cache replayed archived berth tags during a busy handoff.
        The durable fix keyed invalidation on manifest revision, not arrival slot.

        The support bridge stayed open for 47 minutes while the team validated fresh customs summaries.
        """,
        "2026-04-14",
    ),
    url_item(
        "launch_url_status",
        "launch",
        "status_page_digest.html",
        "Status page digest",
        "2026-04-14",
        "ORCA-7 affected Bergen and Nuuk, and user impact lasted 47 minutes before the first all-clear.",
        "The first all-clear was posted at 2026-04-14 19:22 UTC after cache invalidation was confirmed.",
    ),
    url_item(
        "launch_url_press",
        "launch",
        "press_faq.html",
        "Press FAQ",
        "2026-04-10",
        "Tideglass works offline for 72 hours before requiring a sync handshake.",
        "The press kit emphasizes local-first customs review and quiet offline continuity for harbor crews.",
    ),
    note(
        "launch_tweet_explanation",
        "launch",
        "tweet",
        """
        Tweet: Shipping the fix mattered, but shipping the explanation mattered more; users forgave ORCA-7 once we named the cache rule plainly.
        """,
        "2026-04-15",
    ),
    note(
        "launch_tweet_demo",
        "launch",
        "tweet",
        """
        Tweet: Demo prep lesson: never put the live invoice exporter on the same checklist as stage lighting.
        """,
        "2026-04-13",
    ),
    event(
        "launch_event_move",
        "launch",
        """
        Release meeting on 2026-04-12: Amina Sorensen moved launch to April 26 because invoice export still rounded fuel surcharges incorrectly.
        """,
        "2026-04-12",
    ),
    event(
        "launch_event_clear",
        "launch",
        """
        Incident bridge on 2026-04-14: Bergen and Nuuk cleared after the manifest-revision invalidation patch.
        """,
        "2026-04-14",
    ),
    note(
        "bridge_note_orchestration",
        "bridges",
        "idea",
        """
        Idea: adaptive orchestration should borrow from immune memory, jazz improvisation, and transit headway control;
        all three rely on feedback loops and adaptive handoffs instead of one central script.
        """,
        "2026-04-16",
    ),
    file_item(
        "bridge_file_cybernetics",
        "bridges",
        "cybernetics_bridge_memo.md",
        """
        Cybernetics bridge memo

        The adaptive orchestration idea borrows from immune memory, jazz improvisation, and transit headway control.
        Across organisms, ensembles, and control rooms, feedback loops and adaptive handoffs keep local actors coordinated.

        This memo is derived from the cross-discipline orchestration idea so the analogy trail stays inspectable.
        """,
        "2026-04-17",
        derived_from="bridge_note_orchestration",
    ),
    url_item(
        "bridge_url_energy_landscape",
        "bridges",
        "energy_landscape_note.html",
        "Energy landscape note",
        "2026-04-18",
        "Protein folding and planning search both move through energy landscapes rather than a single straight path.",
        "That analogy helps the orchestration project explain why search can settle into useful basins before it finds a final route.",
    ),
    note(
        "bridge_tweet_handoffs",
        "bridges",
        "tweet",
        """
        Tweet: The best orchestration metaphor is not pure software; immune memory, jazz improvisation,
        and transit headway control all teach adaptive handoffs.
        """,
        "2026-04-18",
    ),
    event(
        "bridge_event_roundtable",
        "bridges",
        """
        Cross-discipline roundtable on 2026-04-19: Elena Park linked immune memory, jazz improvisation,
        and transit headway control to explain adaptive orchestration.
        """,
        "2026-04-19",
    ),
]


QUERIES: list[dict] = [
    {"kind": "direct", "query_type": "lookup", "query": "Who approved the HarborCache rollout?", "expected_substrings": ["nadia wu"]},
    {"kind": "direct", "query_type": "lookup", "query": "Which engineer demonstrated the regression pack replay?", "expected_substrings": ["rafael gomez"]},
    {"kind": "direct", "query_type": "lookup", "query": "What cold query time did the team reach after pre-baking harbor dictionaries?", "expected_substrings": ["280ms"]},
    {"kind": "direct", "query_type": "lookup", "query": "What metric mattered during pilot week?", "expected_substrings": ["first useful answer under three seconds"]},
    {"kind": "direct", "query_type": "lookup", "query": "What graph expansion depth did the memo keep?", "expected_substrings": ["depth remains 2"]},
    {"kind": "direct", "query_type": "lookup", "query": "How many keywords does the parser fallback keep?", "expected_substrings": ["5 keywords"]},
    {"kind": "direct", "query_type": "lookup", "query": "Which dock hosted the Bergen pilot?", "expected_substrings": ["dock 14"]},
    {"kind": "direct", "query_type": "lookup", "query": "How often does Whispergrid batch updates?", "expected_substrings": ["every 17 minutes"]},
    {"kind": "direct", "query_type": "lookup", "query": "What fixed the freezer battery loss below minus twelve?", "expected_substrings": ["warm pocket sleeve"]},
    {"kind": "direct", "query_type": "lookup", "query": "Who posted the sensor cleaning bulletin?", "expected_substrings": ["imani cole"]},
    {"kind": "direct", "query_type": "lookup", "query": "Where must EU harbor traces stay?", "expected_substrings": ["helsinki region"]},
    {"kind": "direct", "query_type": "lookup", "query": "Which OCR vendor beat Cobalt Scan?", "expected_substrings": ["cedar ocr"]},
    {"kind": "direct", "query_type": "lookup", "query": "How long are raw voice clips kept without an incident flag?", "expected_substrings": ["21 days"]},
    {"kind": "direct", "query_type": "lookup", "query": "Why was the roof-scan drone canceled?", "expected_substrings": ["winds exceeded 35 knots", "38-knot gusts"]},
    {"kind": "direct", "query_type": "lookup", "query": "Who asked legal to strike the Cobalt auto-renew clause?", "expected_substrings": ["elena park"]},
    {"kind": "direct", "query_type": "lookup", "query": "Who moderated the fishery cooperative workshop?", "expected_substrings": ["kaito mori"]},
    {"kind": "direct", "query_type": "lookup", "query": "What recall gain did the gull-noise classifier achieve?", "expected_substrings": ["0.61 to 0.78"]},
    {"kind": "direct", "query_type": "lookup", "query": "What did users trust before probabilities?", "expected_substrings": ["users trusted arrows before they trusted probabilities", "color-coded berth arrows"]},
    {"kind": "direct", "query_type": "lookup", "query": "Where was the tactile keyboard shipped?", "expected_substrings": ["kirkenes"]},
    {"kind": "direct", "query_type": "lookup", "query": "Who approved the foghorn-negative dataset expansion?", "expected_substrings": ["samir bale"]},
    {"kind": "direct", "query_type": "lookup", "query": "What new public launch date replaced April 18?", "expected_substrings": ["2026-04-26", "april 26"]},
    {"kind": "direct", "query_type": "lookup", "query": "What caused ORCA-7?", "expected_substrings": ["stale customs cache replayed archived berth tags"]},
    {"kind": "direct", "query_type": "lookup", "query": "How long did ORCA-7 user impact last?", "expected_substrings": ["47 minutes"]},
    {"kind": "direct", "query_type": "lookup", "query": "Which cities were affected by ORCA-7?", "expected_substrings": ["bergen and nuuk"]},
    {"kind": "direct", "query_type": "lookup", "query": "How long can Tideglass stay offline before a handshake?", "expected_substrings": ["72 hours"]},
    {"kind": "direct", "query_type": "lookup", "query": "Who was the public demo speaker?", "expected_substrings": ["amina sorensen"]},
    {"kind": "direct", "query_type": "lookup", "query": "What patch cleared Bergen and Nuuk?", "expected_substrings": ["manifest-revision invalidation patch"]},
    {"kind": "direct", "query_type": "lookup", "query": "What launch target became outdated?", "expected_substrings": ["2026-04-18"]},
    {"kind": "direct", "query_type": "lookup", "query": "Which vendor preference is current after the procurement debate?", "expected_substrings": ["cedar ocr"]},
    {"kind": "direct", "query_type": "lookup", "query": "On what date did the parser patch test happen?", "expected_substrings": ["2026-03-16"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Who signed off once the regression pack replay convinced the architecture review?", "expected_substrings": ["nadia wu"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What changed query latency without buying bigger GPUs?", "expected_substrings": ["pre-baking harbor dictionaries", "280ms"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "If someone asks what success felt like in pilot week, what threshold should you quote?", "expected_substrings": ["under three seconds"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which memo says low-weight edges should be skipped and how low is too low?", "expected_substrings": ["0.35"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What phrasing broke fallback parsing before the normalizer fix?", "expected_substrings": ["after the crane outage"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Where did salt fog damage hardware during the drill?", "expected_substrings": ["antenna 3"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What feature kept syncing through tunnels and dead zones?", "expected_substrings": ["ferry mode"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Which alert color survived sleet better for the night shift?", "expected_substrings": ["amber alerts"]},
    {"kind": "indirect", "query_type": "relationship", "query": "When field crews lose connectivity, what paper workaround was proposed?", "expected_substrings": ["qr stickers"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What maintenance rhythm was proposed for dirty antennas after gull season?", "expected_substrings": ["every second tuesday"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "If a crew member asks why blue alerts disappeared, where was that observed?", "expected_substrings": ["northline night shift", "sleet"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What regional rule keeps Dublin from seeing unredacted berth notes?", "expected_substrings": ["redaction", "helsinki region"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which procurement memory justifies paying extra because reviews go faster?", "expected_substrings": ["audit export", "two hours"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What would extend voice clip retention from the default window?", "expected_substrings": ["incident flag", "90 days"]},
    {"kind": "indirect", "query_type": "lookup", "query": "Who halted the roof drone when the wind was unsafe?", "expected_substrings": ["jonas hale"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which statement suggests Cobalt only wins if the budget gap stays large?", "expected_substrings": ["cobalt scan might be acceptable"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What message summarized compliance work as proof about Dublin?", "expected_substrings": ["dublin never sees an unredacted berth note"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Which OCR choice stayed preferred even though it cost nine percent more?", "expected_substrings": ["cedar ocr"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What did youth fellows prefer over chat transcripts?", "expected_substrings": ["annotated maps"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which confusing sound should be compared with gull noise before retraining?", "expected_substrings": ["crane squeal"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What phrase did the youth fellows invent for messy tide logs?", "expected_substrings": ["storm handwriting"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What navigation cue beat numeric lane IDs in recall tests?", "expected_substrings": ["color-coded berth arrows", "orange arrow"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What accessibility defaults helped field video and reading size?", "expected_substrings": ["captions default on", "115 percent"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which idea asked apprentices to narrate surprising tide shifts?", "expected_substrings": ["bookmark surprising tide shifts"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What launch correction superseded the April 18 plan?", "expected_substrings": ["2026-04-26"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What cache rule did users forgive once the team explained it plainly?", "expected_substrings": ["manifest revision", "cache rule"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What part of demo prep should not share a checklist with stage lighting?", "expected_substrings": ["live invoice exporter"]},
    {"kind": "indirect", "query_type": "lookup", "query": "What freeze window starts before launch?", "expected_substrings": ["2026-04-24"]},
    {"kind": "indirect", "query_type": "lookup", "query": "Which content should never leave the regional boundary in the residency memo?", "expected_substrings": ["raw berth photos"]},
    {"kind": "indirect", "query_type": "lookup", "query": "What sample locations were used in the OCR vendor review?", "expected_substrings": ["nuuk and bergen"]},
    {"kind": "indirect", "query_type": "lookup", "query": "Which person said the offline map beat the laminated clipboard?", "expected_substrings": ["marta"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What kind of mode made sync boring in the best possible way?", "expected_substrings": ["ferry mode"]},
    {"kind": "indirect", "query_type": "lookup", "query": "What did the architecture team want session names to look like?", "expected_substrings": ["bergen-2026-03-cold-start"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What should happen to contradictory ship notices instead of overwriting them?", "expected_substrings": ["sibling notes", "supersede the earlier note"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What does the launch checklist say moved because of the invoice export bug?", "expected_substrings": ["public launch moved from 2026-04-18 to 2026-04-26"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Which handshake limit appears in the press FAQ rather than the incident retro?", "expected_substrings": ["72 hours"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What explanation fixed the stale customs cache problem?", "expected_substrings": ["manifest revision", "not arrival slot"]},
    {"kind": "indirect", "query_type": "lookup", "query": "Which harbor master appears in the safety materials?", "expected_substrings": ["jonas hale"]},
    {"kind": "indirect", "query_type": "timeline", "query": "Between 2026-02-10 and 2026-02-20, what went wrong or changed in Bergen field work?", "expected_substrings": ["antenna 3 failed", "amber alerts"]},
    {"kind": "indirect", "query_type": "timeline", "query": "Between 2026-03-01 and 2026-03-08, what research decisions were made?", "expected_substrings": ["plain-language tide labels", "foghorn-negative dataset expansion"]},
    {"kind": "indirect", "query_type": "timeline", "query": "After 2026-04-10, what change and fix defined launch week?", "expected_substrings": ["april 26", "manifest-revision invalidation patch"]},
    {"kind": "indirect", "query_type": "timeline", "query": "Before 2026-02-05, what procurement or safety action had already happened?", "expected_substrings": ["strike the cobalt auto-renew clause", "drone was grounded"]},
    {"kind": "indirect", "query_type": "timeline", "query": "From 2026-03-14 onward, what architecture memories mention rollout or parser reliability?", "expected_substrings": ["harborcache rollout", "date normalizer"]},
    {"kind": "indirect", "query_type": "timeline", "query": "Since 2026-04-12, which locations reached all-clear?", "expected_substrings": ["bergen and nuuk"]},
    {"kind": "indirect", "query_type": "timeline", "query": "What happened between 2026-01-28 and 2026-02-02 in policy and safety?", "expected_substrings": ["strike the cobalt auto-renew clause", "roof-scan drone"]},
    {"kind": "indirect", "query_type": "timeline", "query": "After 2026-03-03, who approved a dataset expansion?", "expected_substrings": ["samir bale"]},
    {"kind": "indirect", "query_type": "timeline", "query": "On 2026-04-14, what patch restored service and where?", "expected_substrings": ["manifest-revision invalidation patch", "bergen and nuuk"]},
    {"kind": "indirect", "query_type": "timeline", "query": "Between 2026-03-14 and 2026-03-16, what two architecture corrections show up?", "expected_substrings": ["harborcache rollout", "after the crane outage"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What document grew out of the revised Cedar preference?", "expected_substrings": ["ocr vendor review"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What source was derived from the revised launch target?", "expected_substrings": ["launch checklist"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which memory grew out of the apprentice-bookmark idea?", "expected_substrings": ["community workshop transcript", "plain-language tide labels"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What older launch plan was explicitly replaced by a newer note?", "expected_substrings": ["2026-04-18"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What earlier vendor idea lost out after Cedar stayed preferred?", "expected_substrings": ["cobalt scan might be acceptable"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which place shows up in both the OCR review sample set and the ORCA-7 impact report?", "expected_substrings": ["nuuk"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which person shows up in both launch planning and the public demo plan?", "expected_substrings": ["amina sorensen"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What evidence says provenance should outrank freshness when scores tie?", "expected_substrings": ["provenance before freshness"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What memory says stop words are dropped and ISO dates should stay explicit?", "expected_substrings": ["keep explicit dates in iso form", "5 keywords"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Which memory explains why warmer visual treatments worked better in weather?", "expected_substrings": ["amber alerts", "red"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What field hardware replacement followed salt fog corrosion?", "expected_substrings": ["ceramic mast"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What did the field report say about solar relays and weather?", "expected_substrings": ["solar relays survived sleet"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "Which issue involved archived berth tags rather than live manifests?", "expected_substrings": ["orca-7"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What customs-review time saving kept Cedar ahead?", "expected_substrings": ["two hours"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What prompt suggests history should stay readable when facts change?", "expected_substrings": ["history stays readable", "supersede the earlier note"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which memory ties crane squeal to false positives?", "expected_substrings": ["false positives still mostly came from crane squeal"]},
    {"kind": "indirect", "query_type": "lookup", "query": "How were attachment sizes treated in offline sync?", "expected_substrings": ["compacts attachments over 12 mb"]},
    {"kind": "indirect", "query_type": "negative", "query": "What did the Montevideo desalination pilot say about trawler beacons?", "expect_empty": True},
    {"kind": "indirect", "query_type": "negative", "query": "Who approved the Singapore rooftop drone waiver?", "expect_empty": True},
    {"kind": "indirect", "query_type": "negative", "query": "What happened at the Vancouver customs orchard exercise?", "expect_empty": True},
    {"kind": "indirect", "query_type": "negative", "query": "Which vendor won the lidar paint contract?", "expect_empty": True},
    {"kind": "indirect", "query_type": "negative", "query": "What did Sofia Lane say about satellite shrimp manifests?", "expect_empty": True},
    {"kind": "direct", "query_type": "lookup", "query": "Which three domains were linked in the adaptive orchestration idea?", "expected_substrings": ["immune memory", "jazz improvisation", "transit headway control"]},
    {"kind": "direct", "query_type": "lookup", "query": "What concept did the cybernetics bridge memo say spans organisms, ensembles, and control rooms?", "expected_substrings": ["feedback loops"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "If someone asks for the metaphor behind adaptive orchestration, what disciplines should you mention?", "expected_substrings": ["immune memory", "jazz improvisation", "transit headway control"]},
    {"kind": "indirect", "query_type": "relationship", "query": "What source was derived from the cross-discipline orchestration idea?", "expected_substrings": ["cybernetics bridge memo"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which event linked immune memory, jazz improvisation, and transit headway control?", "expected_substrings": ["cross-discipline roundtable", "adaptive orchestration"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What kind of handoffs did the orchestration metaphor praise?", "expected_substrings": ["adaptive handoffs"]},
    {"kind": "indirect", "query_type": "timeline", "query": "After 2026-04-16, what cross-discipline memories connected biology, music, and transit?", "expected_substrings": ["immune memory", "jazz improvisation", "transit headway control"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which memo says feedback loops and adaptive handoffs keep local actors coordinated?", "expected_substrings": ["cybernetics bridge memo", "feedback loops", "adaptive handoffs"]},
    {"kind": "indirect", "query_type": "paraphrase", "query": "What planning analogy compared protein folding with search?", "expected_substrings": ["energy landscapes", "planning search", "protein folding"]},
    {"kind": "indirect", "query_type": "relationship", "query": "Which source used energy landscapes to explain planning search?", "expected_substrings": ["energy landscape note"]},
]


SUPERSEDES = [
    ("policy_note_vendor_v1", "policy_note_vendor_v2"),
    ("launch_note_target_v1", "launch_note_target_v2"),
]


def ensure_layout() -> None:
    corpus_counts: dict[str, int] = {}
    for item in CORPUS:
        corpus_counts[item["category"]] = corpus_counts.get(item["category"], 0) + 1

    if len(CORPUS) != 55:
        raise ValueError(f"Expected 55 corpus items, found {len(CORPUS)}")
    expected_corpus = {"article": 11, "link": 11, "idea": 11, "tweet": 11, "event": 11}
    if corpus_counts != expected_corpus:
        raise ValueError(f"Unexpected corpus distribution: {corpus_counts}")

    if len(QUERIES) != 110:
        raise ValueError(f"Expected 110 queries, found {len(QUERIES)}")
    direct_count = sum(1 for query in QUERIES if query["kind"] == "direct")
    indirect_count = sum(1 for query in QUERIES if query["kind"] == "indirect")
    if direct_count != 32 or indirect_count != 78:
        raise ValueError(f"Expected 32 direct and 78 indirect queries, found {direct_count} and {indirect_count}")


def reset_run_root() -> None:
    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT)
    ARTICLES_ROOT.mkdir(parents=True, exist_ok=True)
    LINKS_ROOT.mkdir(parents=True, exist_ok=True)


def write_source_files() -> dict[str, str]:
    source_paths: dict[str, str] = {}
    for item in CORPUS:
        if item["ingest_kind"] == "file":
            path = ARTICLES_ROOT / item["filename"]
            path.write_text(item["text"], encoding="utf-8")
            source_paths[item["key"]] = str(path)
        elif item["ingest_kind"] == "url":
            path = LINKS_ROOT / item["filename"]
            path.write_text(item["text"], encoding="utf-8")
            source_paths[item["key"]] = path.resolve().as_uri()
    return source_paths


def run_cli(*args: str) -> str:
    completed = subprocess.run(
        [str(PYTHON), str(CLI), *args],
        cwd=RUN_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "CLI command failed: "
            + json.dumps(
                {
                    "args": list(args),
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
                ensure_ascii=True,
                indent=2,
            )
        )
    return completed.stdout.strip()


def create_sessions() -> dict[str, str]:
    session_ids: dict[str, str] = {}
    for session_name in sorted({item["session"] for item in CORPUS}):
        session_ids[session_name] = run_cli("session", "start").strip()
    return session_ids


def parse_node_id(output: str) -> str:
    for line in output.splitlines():
        match = NODE_ID_PATTERN.match(line.strip())
        if match:
            return match.group(1)
    raise ValueError(f"Unable to parse node id from output: {output!r}")


def ingest_corpus(source_paths: dict[str, str], session_ids: dict[str, str]) -> tuple[dict[str, str], list[dict]]:
    node_ids: dict[str, str] = {}
    ingest_records: list[dict] = []

    for item in CORPUS:
        args = ["add"]

        if item["ingest_kind"] in {"note", "event"}:
            args.extend([item["text"], "--type", item["ingest_kind"]])
        elif item["ingest_kind"] == "file":
            args.extend(["--file", source_paths[item["key"]]])
        elif item["ingest_kind"] == "url":
            args.extend(["--url", source_paths[item["key"]]])
        else:
            raise ValueError(f"Unknown ingest kind: {item['ingest_kind']}")

        args.extend(["--session", session_ids[item["session"]], "--at", item["at"]])

        derived_from = item.get("derived_from")
        if derived_from is not None:
            args.extend(["--derived-from", node_ids[derived_from]])

        output = run_cli(*args)
        node_id = parse_node_id(output)
        node_ids[item["key"]] = node_id
        ingest_records.append(
            {
                "key": item["key"],
                "node_id": node_id,
                "category": item["category"],
                "session": item["session"],
                "ingest_kind": item["ingest_kind"],
                "output": output,
            }
        )

    return node_ids, ingest_records


def apply_supersedes(node_ids: dict[str, str]) -> list[dict]:
    relationships: list[dict] = []
    for old_key, new_key in SUPERSEDES:
        output = run_cli("supersede", node_ids[old_key], node_ids[new_key])
        relationships.append(
            {
                "relation": "SUPERSEDES",
                "old_key": old_key,
                "new_key": new_key,
                "old_node_id": node_ids[old_key],
                "new_node_id": node_ids[new_key],
                "output": output,
            }
        )
    return relationships


def doctor_report() -> dict:
    return json.loads(run_cli("doctor", "--json"))


def flatten_payload(payload: dict) -> str:
    parts: list[str] = []
    for bucket in ["events", "entities", "notes", "sources"]:
        for node in payload.get(bucket, []):
            parts.extend(
                [
                    str(node.get("title", "")),
                    str(node.get("summary", "")),
                    str(node.get("content", "")),
                    str(node.get("status", "")),
                    str(node.get("type", "")),
                ]
            )
            metadata = node.get("metadata") or {}
            parts.extend(str(value) for value in metadata.values())
    for edge_fact in payload.get("edge_facts", []):
        parts.append(str(edge_fact.get("fact", "")))
    for relation_name in ["conflicts", "superseded"]:
        for item in payload.get(relation_name, []):
            parts.extend([str(item.get("source_id", "")), str(item.get("target_id", ""))])
    for group_name, values in (payload.get("session_groups") or {}).items():
        parts.append(str(group_name))
        parts.extend(str(value) for value in values)
    for value in (payload.get("query_meta") or {}).values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values() if item is not None)
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def parse_first_result_block(human_output: str) -> str:
    lines = human_output.splitlines()
    collected: list[str] = []
    in_first_block = False

    for line in lines:
        line_text = line.rstrip()
        match = FIRST_RESULT_PATTERN.match(line_text)
        if match:
            if in_first_block:
                break
            in_first_block = True
            collected.extend([match.group("node_type"), match.group("label")])
            continue

        if not in_first_block:
            continue

        stripped = line_text.strip()
        if not stripped:
            continue
        if re.match(r"^\d+\.\s+\[", stripped):
            break
        if stripped.startswith("Match:"):
            collected.append(stripped.split("Match:", 1)[1].strip())
            continue
        if stripped.startswith("Source:"):
            collected.append(stripped.split("Source:", 1)[1].strip())
            continue
        collected.append(stripped)

    return " ".join(collected).lower()


def node_count(payload: dict) -> int:
    return sum(len(payload.get(bucket, [])) for bucket in ["events", "entities", "notes", "sources"])


def evaluate_queries() -> tuple[list[dict], dict]:
    query_results: list[dict] = []

    for index, query_case in enumerate(QUERIES, start=1):
        human_output = run_cli("query", query_case["query"])
        payload = json.loads(run_cli("query", query_case["query"], "--json"))
        flat_text = flatten_payload(payload)
        first_block = parse_first_result_block(human_output)
        returned_count = node_count(payload)
        expect_empty = bool(query_case.get("expect_empty"))

        if expect_empty:
            passed = returned_count == 0
            top_pass = None
            expected = []
        else:
            expected = [value.lower() for value in query_case["expected_substrings"]]
            passed = any(value in flat_text for value in expected)
            top_pass = any(value in first_block for value in expected) if query_case["kind"] == "direct" else None

        query_results.append(
            {
                "index": index,
                "kind": query_case["kind"],
                "query_type": query_case["query_type"],
                "query": query_case["query"],
                "expected_substrings": expected,
                "expect_empty": expect_empty,
                "passed": passed,
                "top_pass": top_pass,
                "returned_count": returned_count,
                "top_result_preview": first_block,
                "human_output": human_output,
                "payload": payload,
            }
        )

    direct = [result for result in query_results if result["kind"] == "direct"]
    indirect = [result for result in query_results if result["kind"] == "indirect"]
    negatives = [result for result in indirect if result["expect_empty"]]
    timeline = [result for result in indirect if result["query_type"] == "timeline"]
    relationships = [result for result in indirect if result["query_type"] == "relationship"]

    summary = {
        "overall": {
            "passed": sum(1 for result in query_results if result["passed"]),
            "total": len(query_results),
        },
        "direct": {
            "passed": sum(1 for result in direct if result["passed"]),
            "total": len(direct),
            "top_passed": sum(1 for result in direct if result["top_pass"]),
        },
        "indirect": {
            "passed": sum(1 for result in indirect if result["passed"]),
            "total": len(indirect),
        },
        "negatives": {
            "passed": sum(1 for result in negatives if result["passed"]),
            "total": len(negatives),
        },
        "timeline": {
            "passed": sum(1 for result in timeline if result["passed"]),
            "total": len(timeline),
        },
        "relationships": {
            "passed": sum(1 for result in relationships if result["passed"]),
            "total": len(relationships),
        },
        "average_returned_count": round(sum(result["returned_count"] for result in query_results) / len(query_results), 2),
        "misses": [
            {
                "index": result["index"],
                "kind": result["kind"],
                "query_type": result["query_type"],
                "query": result["query"],
                "returned_count": result["returned_count"],
                "top_result_preview": result["top_result_preview"],
            }
            for result in query_results
            if not result["passed"]
        ],
    }
    return query_results, summary


def write_summary(summary: dict, doctor: dict, ingest_records: list[dict], relationships: list[dict], session_ids: dict[str, str]) -> None:
    corpus_counts: dict[str, int] = {}
    for item in CORPUS:
        corpus_counts[item["category"]] = corpus_counts.get(item["category"], 0) + 1

    misses = summary["misses"][:10]
    miss_lines = "\n".join(
        f"- #{item['index']} [{item['kind']}/{item['query_type']}] {item['query']} (returned {item['returned_count']})"
        for item in misses
    ) or "- none"
    sqlite_integrity_ok = doctor.get("integrity_check") == "ok"
    fts_rows_match_nodes = doctor.get("missing_fts_rows") == 0 and doctor.get("orphaned_fts_rows") == 0

    text = "\n".join(
        [
            "# Detailed PAM Evaluation",
            "",
            "## Corpus",
            "",
            f"- total items: {len(CORPUS)}",
            f"- article items: {corpus_counts['article']}",
            f"- link items: {corpus_counts['link']}",
            f"- idea items: {corpus_counts['idea']}",
            f"- tweet items: {corpus_counts['tweet']}",
            f"- event items: {corpus_counts['event']}",
            f"- sessions: {len(session_ids)}",
            f"- ingested nodes: {len(ingest_records)}",
            f"- supersede relationships applied: {len(relationships)}",
            "",
            "## Health",
            "",
            f"- schema version: {doctor.get('schema_version')}",
            f"- sqlite integrity ok: {sqlite_integrity_ok}",
            f"- fts rows match nodes: {fts_rows_match_nodes}",
            "",
            "## Query Results",
            "",
            f"- overall: {summary['overall']['passed']}/{summary['overall']['total']}",
            f"- direct any-hit: {summary['direct']['passed']}/{summary['direct']['total']}",
            f"- direct top-hit: {summary['direct']['top_passed']}/{summary['direct']['total']}",
            f"- indirect any-hit: {summary['indirect']['passed']}/{summary['indirect']['total']}",
            f"- negative empty-result checks: {summary['negatives']['passed']}/{summary['negatives']['total']}",
            f"- timeline queries: {summary['timeline']['passed']}/{summary['timeline']['total']}",
            f"- relationship queries: {summary['relationships']['passed']}/{summary['relationships']['total']}",
            f"- average returned nodes per query: {summary['average_returned_count']}",
            "",
            "## First Misses",
            "",
            miss_lines,
            "",
        ]
    )
    SUMMARY_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    ensure_layout()
    reset_run_root()
    source_paths = write_source_files()
    session_ids = create_sessions()
    node_ids, ingest_records = ingest_corpus(source_paths, session_ids)
    relationships = apply_supersedes(node_ids)
    doctor = doctor_report()
    query_results, summary = evaluate_queries()

    dataset_snapshot = {
        "corpus": CORPUS,
        "queries": QUERIES,
        "sessions": session_ids,
        "node_ids": node_ids,
        "source_paths": source_paths,
    }
    DATASET_PATH.write_text(json.dumps(dataset_snapshot, ensure_ascii=True, indent=2), encoding="utf-8")
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "summary": summary,
                "doctor": doctor,
                "ingest_records": ingest_records,
                "relationships": relationships,
                "query_results": query_results,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_summary(summary, doctor, ingest_records, relationships, session_ids)

    print(
        json.dumps(
            {
                "dataset_path": str(DATASET_PATH),
                "results_path": str(RESULTS_PATH),
                "summary_path": str(SUMMARY_PATH),
                "run_root": str(RUN_ROOT),
                "overall_passed": summary["overall"]["passed"],
                "overall_total": summary["overall"]["total"],
                "direct_passed": summary["direct"]["passed"],
                "direct_total": summary["direct"]["total"],
                "direct_top_passed": summary["direct"]["top_passed"],
                "indirect_passed": summary["indirect"]["passed"],
                "indirect_total": summary["indirect"]["total"],
                "negative_passed": summary["negatives"]["passed"],
                "negative_total": summary["negatives"]["total"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())