from ogoh.pipeline.dedupe import assign_clusters
from ogoh.pipeline.digest import render_console, render_telegram, top_entries


def test_a_story_takes_one_slot_however_many_outlets_ran_it(
    session, make_item, make_enrichment, make_source
):
    primary = make_source("Primary", trust_tier=1)
    press = make_source("Press", trust_tier=3)

    first = make_item("Introducing GPT-Live", source=primary, age_hours=5)
    rerun = make_item("Introducing GPT‑Live", source=press, age_hours=2)
    make_enrichment(first, importance=8)
    make_enrichment(rerun, importance=8)
    assign_clusters(session)

    entries = top_entries(session, min_importance=5, limit=10)

    assert len(entries) == 1
    assert entries[0].also_covered_by == 1


def test_the_authoritative_source_speaks_for_the_story(
    session, make_item, make_enrichment, make_source
):
    # OpenAI's own announcement outranks a blog post about it, whoever published
    # first. Getting this wrong is quiet — it just credits the wrong outlet.
    primary = make_source("OpenAI News", trust_tier=1)
    secondary = make_source("A Blog", trust_tier=2)

    make_enrichment(make_item("Introducing GPT-Live", source=primary, age_hours=5), importance=8)
    make_enrichment(make_item("Introducing GPT‑Live", source=secondary, age_hours=1), importance=8)
    assign_clusters(session)

    entries = top_entries(session, min_importance=5, limit=10)

    assert entries[0].item.source.name == "OpenAI News"


def test_between_equal_sources_the_one_who_broke_it_wins(
    session, make_item, make_enrichment, make_source
):
    early = make_source("Early", trust_tier=2)
    late = make_source("Late", trust_tier=2)

    make_enrichment(make_item("Introducing GPT-Live", source=early, age_hours=8), importance=8)
    make_enrichment(make_item("Introducing GPT‑Live", source=late, age_hours=1), importance=8)
    assign_clusters(session)

    entries = top_entries(session, min_importance=5, limit=10)

    assert entries[0].item.source.name == "Early"


def test_importance_orders_the_digest(session, make_item, make_enrichment):
    make_enrichment(make_item("Routine thing"), importance=5)
    make_enrichment(make_item("A launch"), importance=10)
    make_enrichment(make_item("Notable thing"), importance=7)

    entries = top_entries(session, min_importance=5, limit=10)

    assert [e.item.title for e in entries] == ["A launch", "Notable thing", "Routine thing"]


def test_the_floor_is_applied(session, make_item, make_enrichment):
    make_enrichment(make_item("Below"), importance=4)
    make_enrichment(make_item("Above"), importance=6)

    entries = top_entries(session, min_importance=5, limit=10)

    assert [e.item.title for e in entries] == ["Above"]


def test_the_window_follows_when_the_news_happened(session, make_item, make_enrichment):
    # Not when we fetched it. Everything looks fresh by fetched_at on a first
    # run, which is how a 2015 archive post ends up leading today's digest.
    make_enrichment(make_item("Old news", age_hours=100), importance=10)
    make_enrichment(make_item("Today", age_hours=1), importance=6)

    entries = top_entries(session, min_importance=5, limit=10, within_hours=48)

    assert [e.item.title for e in entries] == ["Today"]


def test_a_widely_covered_story_does_not_crowd_out_the_rest(
    session, make_item, make_enrichment, make_source
):
    # Four outlets on one story must cost one slot, not four.
    for i in range(4):
        source = make_source(f"Outlet {i}", trust_tier=2)
        make_enrichment(make_item("Introducing GPT-Live", source=source), importance=9)
    make_enrichment(make_item("A separate story"), importance=6)
    assign_clusters(session)

    entries = top_entries(session, min_importance=5, limit=2)

    assert [e.item.title for e in entries] == ["Introducing GPT-Live", "A separate story"]


def test_limit_is_honoured(session, make_item, make_enrichment):
    for i in range(10):
        make_enrichment(make_item(f"Story {i}"), importance=6)

    assert len(top_entries(session, min_importance=5, limit=3)) == 3


def test_unenriched_items_never_reach_a_digest(session, make_item):
    make_item("Not yet judged")
    assert top_entries(session, min_importance=0, limit=10) == []


def test_renderers_survive_an_empty_digest(session):
    assert render_telegram([])
    assert render_console([])


def test_telegram_render_escapes_markup(session, make_item, make_enrichment):
    # A headline with an ampersand or a bracket must not break parse_mode=HTML.
    item = make_item("Fish & <chips> \"quoted\"")
    make_enrichment(item, importance=8)

    html = render_telegram(top_entries(session, min_importance=5, limit=10))

    assert "&amp;" in html
    assert "&lt;chips&gt;" in html
    assert "<chips>" not in html


def test_extra_coverage_is_shown(session, make_item, make_enrichment, make_source):
    for i in range(3):
        make_enrichment(
            make_item("Introducing GPT-Live", source=make_source(f"Outlet {i}")), importance=8
        )
    assign_clusters(session)

    html = render_telegram(top_entries(session, min_importance=5, limit=10))

    assert "+2 manba" in html
