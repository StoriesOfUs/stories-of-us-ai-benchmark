#!/usr/bin/env python3
"""Build the frozen V05 focused diagnostic fixtures from development evidence.

The generated model-facing files never contain expected decisions. Expected
outcomes are written only to the protected answer-key file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "private/cases/development_cases_model_facing_v01.json"
EVIDENCE_PATH = ROOT / "private/evidence/development_evidence_index_v01.json"
OUT = ROOT / "private/diagnostics"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_case(source: dict, test_id: str, summary: str | None = None) -> dict:
    case = copy.deepcopy(source)
    case["case_id"] = test_id
    case["stage_context"] = "INITIAL"
    if summary is not None:
        case["candidate_summary"] = summary
    case["evidence_file"] = "focused_evidence_index_v01.json"
    return case


def main() -> None:
    source_cases = {row["case_id"]: row for row in load(CASES_PATH)["cases"]}
    source_evidence = load(EVIDENCE_PATH)["cases"]

    f02 = (
        "World Intellectual Property Organization reports that disabled fashion designer "
        "Isabella Springmühl uses her brand Down to Xjabelle to challenge stereotypes "
        "across the Arts. She includes disabled models in fashion shows to promote inclusion."
    )
    f05 = (
        "Human Rights Watch reports that disabled people and supporters held a symbolic "
        "funeral procession in Warsaw to demand personal-assistance legislation. Activists "
        "worry that the draft bill may be scrapped if it is not considered before the election."
    )
    f07 = (
        "Department for Work and Pensions reports that technology companies and disability "
        "organisations discussed assistive tools to reduce workplace barriers for disabled "
        "people. An AbilityNet leader said recent advances had expanded ‘the art of the "
        "possible’ for disability inclusion at work."
    )

    synthetic = {
        "F06": {
            "case": {
                "case_id": "F06",
                "stage_context": "INITIAL",
                "category": "Arts",
                "source_name": "Synthetic Transit Record",
                "title": "Broken station lift prevents passenger reaching appointment",
                "canonical_url": "synthetic://focused/F06-broken-station-lift",
                "evidence_file": "focused_evidence_index_v01.json",
                "candidate_summary": (
                    "Synthetic Transit Record reports that disabled artist Mira Jones missed "
                    "an appointment after a station lift broke, leaving the only step-free route "
                    "unavailable. Staff arranged an accessible taxi two hours later."
                ),
            },
            "evidence": (
                "Synthetic development fixture. Passenger Mira Jones, a disabled painter, was "
                "travelling to a hospital appointment when the only lift serving platform two "
                "failed. The article examines the station's step-free route, the two-hour delay, "
                "and the accessible taxi arranged by staff. Her occupation is mentioned once as "
                "background; no artwork, exhibition, performance or other creative activity is "
                "discussed."
            ),
        },
        "F08": {
            "case": {
                "case_id": "F08",
                "stage_context": "INITIAL",
                "category": "Arts",
                "source_name": "Synthetic Film Review",
                "title": "New film brings Lena Hart's performance work to the screen",
                "canonical_url": "synthetic://focused/F08-film-as-creative-work",
                "evidence_file": "focused_evidence_index_v01.json",
                "candidate_summary": (
                    "Synthetic Film Review reports that a new documentary about disabled "
                    "activist Lena Hart premieres this month. Its review focuses on the "
                    "director's creative choices, archival montage and adaptation of Hart's "
                    "performance work for film."
                ),
            },
            "evidence": (
                "Synthetic development fixture. The article reviews a new documentary about "
                "disabled activist Lena Hart, concentrating on the director's creative choices, "
                "archival montage, sound design and adaptation of Hart's performance work. The "
                "film premieres this month. Hart's political biography supplies context, but the "
                "article's defining subject is the film as a new creative work."
            ),
        },
        "F09": {
            "case": {
                "case_id": "F09",
                "stage_context": "INITIAL",
                "category": "History",
                "source_name": "Synthetic History Archive",
                "title": "Archive traces disability-rights activist Lena Hart's life",
                "canonical_url": "synthetic://focused/F09-activist-history-with-film",
                "evidence_file": "focused_evidence_index_v01.json",
                "candidate_summary": (
                    "Synthetic History Archive recounts disabled activist Lena Hart's campaigns "
                    "for accessible transport from 1972 to 1991 and the records preserved in her "
                    "archive. A film screening introduces the historical collection to new "
                    "audiences."
                ),
            },
            "evidence": (
                "Synthetic development fixture. The article traces disabled activist Lena "
                "Hart's life and achievements, including accessible-transport campaigns from "
                "1972 to 1991, and describes letters and recordings preserved in her archive. "
                "A film screening is the opening event for the archive project, but the article's "
                "defining subject is Hart's historical life, campaigns and long-term legacy."
            ),
        },
    }

    cases = [
        make_case(source_cases["D07"], "F01"),
        make_case(source_cases["D07"], "F02", f02),
        make_case(source_cases["D01"], "F03"),
        make_case(source_cases["D06"], "F04"),
        make_case(source_cases["D06"], "F05", f05),
        synthetic["F06"]["case"],
        make_case(source_cases["D10"], "F07", f07),
        synthetic["F08"]["case"],
        synthetic["F09"]["case"],
    ]

    evidence = {
        "F01": copy.deepcopy(source_evidence["D07"]),
        "F02": copy.deepcopy(source_evidence["D07"]),
        "F03": copy.deepcopy(source_evidence["D01"]),
        "F04": copy.deepcopy(source_evidence["D06"]),
        "F05": copy.deepcopy(source_evidence["D06"]),
        "F07": copy.deepcopy(source_evidence["D10"]),
    }
    for case_id in ("F06", "F08", "F09"):
        evidence[case_id] = {
            "source_file": f"synthetic/{case_id}.txt",
            "paragraphs": [{"evidence_id": "P001", "text": synthetic[case_id]["evidence"]}],
        }

    key_rows = [
        ("F01", "ACCEPT", "Fashion design is the genuine Arts subject without requiring the literal Category word."),
        ("F02", "REVISE", "Arts relevance is supported, but the stereotypes claim is overbroad beyond fashion."),
        ("F03", "REVISE", "Orylski's particular bill assessment is incorrectly attributed to activists collectively."),
        ("F04", "ACCEPT", "The same particular assessment is accurately attributed to Orylski."),
        ("F05", "ACCEPT", "The procession demand and election-related worry are both established collective positions."),
        ("F06", "HOLD", "The article is centrally about a transport-access barrier; the artistic occupation is incidental and cannot establish assigned Arts relevance."),
        ("F07", "ACCEPT", "The phrase art of the possible is incidental wording within a genuinely Tech-focused story."),
        ("F08", "ACCEPT", "The new film is assessed as creative work, so Arts is the defining subject."),
        ("F09", "ACCEPT", "The film is only an entry point; the historical life, campaigns and archive are the defining subject."),
    ]
    answer_key = {
        "schema_version": "stories-of-us-v05-focused-diagnostic-answer-key-v01",
        "status": "PROTECTED_CODEX_ASSISTED_EXPECTATIONS_FOR_PROPOSED_TEST",
        "model_facing": False,
        "hidden_evaluation_material_used": False,
        "cases": [
            {"case_id": case_id, "expected_decision": decision, "reason": reason}
            for case_id, decision, reason in key_rows
        ],
    }

    write(OUT / "focused_cases_model_facing_v01.json", {
        "schema_version": "stories-of-us-v05-focused-diagnostic-cases-v01",
        "status": "FROZEN_PROPOSED_DIAGNOSTIC_INPUTS",
        "expected_answers_included": False,
        "cases": cases,
    })
    write(OUT / "focused_evidence_index_v01.json", {
        "schema_version": "stories-of-us-v05-focused-diagnostic-evidence-v01",
        "status": "FROZEN_PROPOSED_DIAGNOSTIC_EVIDENCE",
        "cases": evidence,
    })
    write(OUT / "focused_answer_key_v01.json", answer_key)


if __name__ == "__main__":
    main()
