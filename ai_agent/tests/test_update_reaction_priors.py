from __future__ import annotations

import json
from pathlib import Path

from ai_agent.tools import update_reaction_priors as urp

FIXTURE_HTML = """
<div class="card-stat-item" data-presence="99.79" style="box-shadow:0 4px 12px rgba(0,0,0,0.5);">
  <a href="/cards/details-defy"><img alt="Defy"></a>
  <span title="Average copies per deck">×3.0</span>
</div>
<div class="card-stat-item" data-presence="95.81" style="box-shadow:0 4px 12px rgba(0,0,0,0.5);">
  <a href="/cards/details-en-garde"><img alt="En Garde"></a>
  <span title="Average copies per deck">×2.2</span>
</div>
<div class="card-stat-item" data-presence="90.15">
  <a href="/cards/details-master-yi-tempered"><img alt="Master Yi, Tempered"></a>
  <span title="Average copies per deck">×1.0</span>
</div>
<div class="card-stat-item" data-presence="84.49">
  <a href="/cards/details-sabotage"><img alt="Sabotage"></a>
  <span title="Average copies per deck">×2.0</span>
</div>
<div class="card-stat-item" data-presence="43.61">
  <a href="/cards/details-unknown-spell"><img alt="Unknown"></a>
  <span title="Average copies per deck">×1.1</span>
</div>
Understanding the Stats
"""

LOCAL_CARDS = {
    "defy": {"id": "defy", "is_action": False, "is_reaction": True, "card_type": "spell"},
    "en-garde": {"id": "en-garde", "is_action": False, "is_reaction": True, "card_type": "spell"},
    "master-yi-tempered": {
        "id": "master-yi-tempered",
        "is_action": False,
        "is_reaction": False,
        "card_type": "unit",
    },
    "sabotage": {"id": "sabotage", "is_action": True, "is_reaction": False, "card_type": "spell"},
}


def test_parse_card_stat_items_ignores_css_px_before_copies_badge():
    html = """
    <div class="card-stat-item" data-presence="99.0" style="box-shadow:0 4px 12px;">
      <a href="/cards/details-defy"></a>
      <span title="Average copies per deck">×3.0</span>
    </div>
    """
    items = urp.parse_card_stat_items(html)
    assert items[0]["avg_copies"] == 3.0


def test_parse_card_stat_items_preserves_decimal_copies():
    html = """
    <div class="card-stat-item" data-presence="96.0" style="box-shadow:0 4px 12px;">
      <a href="/cards/details-defy"></a>
      <span title="Average copies per deck">×2.6</span>
    </div>
    """
    items = urp.parse_card_stat_items(html)
    assert items[0]["avg_copies"] == 2.6


def test_parse_card_stat_items_caps_avg_copies_at_three():
    html = """
    <div class="card-stat-item" data-presence="50.0">
      <a href="/cards/details-defy"></a>
      <span title="Average copies per deck">×3.6</span>
    </div>
    """
    items = urp.parse_card_stat_items(html)
    assert items[0]["avg_copies"] == 3.0


def test_parse_card_stat_items_extracts_presence_copies_and_slug():
    items = urp.parse_card_stat_items(FIXTURE_HTML)
    assert [row["slug"] for row in items] == [
        "defy",
        "en-garde",
        "master-yi-tempered",
        "sabotage",
        "unknown-spell",
    ]
    assert items[0]["presence"] == 99.79
    assert items[0]["avg_copies"] == 3.0
    assert items[1]["avg_copies"] == 2.2


def test_filter_top_action_reactions_keeps_spells_and_skips_unknown():
    items = urp.parse_card_stat_items(FIXTURE_HTML)
    kept, skipped = urp.filter_top_action_reactions(items, LOCAL_CARDS, top_n=30)
    assert skipped == ["unknown-spell"]
    assert [row["card_id"] for row in kept] == ["defy", "en-garde", "sabotage"]
    assert kept[0]["play_rate"] == 0.9979
    assert kept[0]["avg_copies"] == 3.0


def test_build_generic_reactions_requires_two_legends():
    legend_priors = {
        "legend-a": [
            {"card_id": "defy", "play_rate": 0.9, "avg_copies": 3},
            {"card_id": "stupefy", "play_rate": 0.4, "avg_copies": 2},
        ],
        "legend-b": [
            {"card_id": "defy", "play_rate": 0.8, "avg_copies": 2},
            {"card_id": "en-garde", "play_rate": 0.5, "avg_copies": 2},
        ],
    }
    generic = urp.build_generic_reactions(legend_priors)
    assert [row["card_id"] for row in generic] == ["defy"]
    assert generic[0]["play_rate"] == 0.85


def test_build_generic_reactions_falls_back_to_existing_ids():
    legend_priors = {
        "legend-a": [{"card_id": "defy", "play_rate": 0.9, "avg_copies": 3}],
    }
    existing = [{"card_id": "defy", "play_rate": 0.1, "avg_copies": 1}]
    generic = urp.build_generic_reactions(legend_priors, existing)
    assert generic == [{"card_id": "defy", "play_rate": 0.9, "avg_copies": 3}]


def test_discover_legend_slugs_from_legends_page():
    html = """
    <a href="/legends/master-yi-wuju-bladesman">Master Yi</a>
    <a href="/legends/kennen-heart-of-the-tempest/stats">Kennen stats</a>
    <a href="/legends/constructed">Constructed</a>
    """
    assert urp.discover_legend_slugs(html) == [
        "kennen-heart-of-the-tempest",
        "master-yi-wuju-bladesman",
    ]


def test_build_stats_url_includes_metagame_id_only_by_default():
    url = urp.build_stats_url("master-yi-wuju-bladesman", metagame_id=1)
    assert url.endswith("/legends/master-yi-wuju-bladesman/stats?metagame_id=1")
    assert "date_range" not in url
    assert "board" not in url


def test_build_stats_url_includes_optional_filters():
    url = urp.build_stats_url(
        "master-yi-wuju-bladesman",
        metagame_id=1,
        date_range="last_month",
        board="main",
    )
    assert "metagame_id=1" in url
    assert "date_range=last_month" in url
    assert "board=main" in url


def test_write_json_atomic(tmp_path: Path):
    out = tmp_path / "reaction_priors.json"
    payload = {
        "generic_reactions": [{"card_id": "defy", "play_rate": 0.5, "avg_copies": 2}],
        "master-yi-wuju-bladesman": [{"card_id": "defy", "play_rate": 0.9, "avg_copies": 3}],
    }
    urp.write_json_atomic(out, payload)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["generic_reactions"][0]["card_id"] == "defy"
    assert loaded["master-yi-wuju-bladesman"][0]["avg_copies"] == 3


def test_load_local_cards_reads_repo_cards():
    cards_dir = Path(__file__).resolve().parents[2] / "Data" / "Cards"
    cards = urp.load_local_cards(cards_dir)
    assert "defy" in cards
    assert cards["defy"]["is_reaction"] is True
