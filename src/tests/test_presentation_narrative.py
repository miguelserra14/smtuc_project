"""Estrutura da narrativa da apresentação (presentation_content.py, decidida a 2026-11-26):
secções seguidas e na ordem de SECTIONS, um divisor no início de cada uma, cada slide de uma
secção diz que cenário(s) da escada mostra, ids resolvidos por dashboard._attach_narrative e
todos os kinds desenhados pelos dois templates (mockups e parede FeedNPlay)."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from visualizations.dashboard import (
    _attach_narrative,
    _default_presentation_tabs,
    create_feednplay_dashboard_html,
    create_presentation_dashboard_html,
)
from visualizations.presentation_content import PRESENTATION_TABS, SCENARIO_LADDER, SECTIONS

_TEMPLATES = Path(__file__).resolve().parents[1] / "visualizations" / "templates"


def test_sections_are_contiguous_and_in_order() -> None:
    # Abertura (sem secção) -> 1 -> 1.5 -> 2 -> 3 -> 4 -> fecho (sem secção), cada secção seguida.
    runs = [key for key, _ in itertools.groupby(tab.get("section") for tab in PRESENTATION_TABS)]
    assert runs == [None, *[section["id"] for section in SECTIONS], None]


def test_each_section_opens_with_its_divider() -> None:
    for section in SECTIONS:
        slides = [tab for tab in PRESENTATION_TABS if tab.get("section") == section["id"]]
        assert slides[0]["kind"] == "section"
        assert sum(tab["kind"] == "section" for tab in slides) == 1


def test_every_section_slide_declares_its_scenarios() -> None:
    for tab in PRESENTATION_TABS:
        if tab.get("section") is None or tab["kind"] == "section":
            assert "ladder" not in tab, tab["id"]
        else:
            assert tab.get("ladder"), f"slide {tab['id']!r} não diz que cenário mostra"


def test_ids_are_unique() -> None:
    for items in (PRESENTATION_TABS, SECTIONS, SCENARIO_LADDER):
        ids = [item["id"] for item in items]
        assert len(ids) == len(set(ids))


def test_narrative_is_resolved_and_planned_sections_are_flagged() -> None:
    tabs = {tab["id"]: tab for tab in _default_presentation_tabs()}
    planned = {s["id"]: tabs[f"secao_{s['number'].replace('.', '_')}"]["section_meta"]["planned"] for s in SECTIONS}
    # Só as secções 3 e 4 comparam cenários planeados (horário da Linha do Hospital assumido).
    assert planned == {"s1": False, "s1_5": False, "s2": False, "s3": True, "s4": True}
    assert [step["tag"] for step in tabs["s1_5_contributo"]["ladder_meta"]] == ["A′", "A"]
    assert tabs["cenarios"]["ladder_all"] == SCENARIO_LADDER
    assert [s["id"] for s in tabs["cenarios"]["sections_all"]] == [s["id"] for s in SECTIONS]


@pytest.mark.parametrize(
    "tab",
    [
        {"id": "x", "kind": "pending", "section": "s9"},
        {"id": "x", "kind": "pending", "section": "s1", "ladder": ["Z"]},
    ],
)
def test_unknown_ids_raise(tab: dict) -> None:
    with pytest.raises(ValueError):
        _attach_narrative([tab])


def test_both_templates_render_every_kind(tmp_path: Path) -> None:
    kinds = {tab["kind"] for tab in PRESENTATION_TABS}
    for template in ("presentation_dashboard.html", "feednplay_dashboard.html"):
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        missing = sorted(kind for kind in kinds if f"kind === '{kind}'" not in text)
        assert not missing, f"{template} não desenha: {missing}"

    for create in (create_presentation_dashboard_html, create_feednplay_dashboard_html):
        out = Path(create(tmp_path / f"{create.__name__}.html"))
        data = json.loads(re.search(r"const tabs = (\[.*?\]);\n", out.read_text(encoding="utf-8"), re.S).group(1))
        assert [tab["id"] for tab in data] == [tab["id"] for tab in PRESENTATION_TABS]
        assert all("section_meta" in tab for tab in data if tab.get("section"))
