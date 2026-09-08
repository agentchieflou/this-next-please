"""The link rail: what a tile may show, and above all what it must refuse to show.

Every case here is a way to build a URL that looks clickable and is not. A missing `ws_id` composing
`app.powerbi.com/groups//reports/`, an `active_ticket` holding a sentence, a `jira_url` pasted
without a scheme, a Cloud board path on a Data Center site -- all of them open, none of them lands
where the operator expected, and each one costs a window switch to find that out. So the rule the
whole module is built on gets the widest test in the file: no combination of half-filled facts may
produce a URL with a hole in it.
"""
from __future__ import annotations
import itertools

import pytest

from agentdata.fleet import links as L
from agentdata.fleet.registry import Repo

WS = "11111111-2222-3333-4444-555555555555"
DS = "66666666-7777-8888-9999-000000000000"
REPORT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

CLOUD = "https://acme.atlassian.net"
DC = "https://jira.acme.local"

FULL_FACTS = {
    "jira_url": CLOUD,
    "jira_project": "RDSD",
    "jira_board_id": "3",
    "ws_id": WS,
    "ds_id": DS,
    "report_id": REPORT,
    "pbi_workspace": "Reporting PRD",
    "bitbucket_repo": "acme/rdsd-reporting",
    "confluence_space": "RDSD",
    "confluence_parent": "98765",
}

FULL_STATE = {
    "active_ticket": "RDSD-101",
    "pr_url": "https://bitbucket.org/acme/rdsd-reporting/pull-requests/42",
    "confluence_url": "https://acme.atlassian.net/wiki/spaces/RDSD/pages/12345/Velocity",
}


def repo_at(tmp_path, name: str = "rdsd") -> Repo:
    return Repo(name=name, path=str(tmp_path / name))


def by_name(rows: list[dict]) -> dict:
    return {r["name"]: r for r in rows}


# ------------------------------------------------------------------------------ the structure


def test_every_name_has_a_builder_a_kind_and_a_row(tmp_path):
    """The three tables have to agree, or a name is a link nobody builds or a row with no icon."""
    rows = L.links_for(repo_at(tmp_path), FULL_FACTS, FULL_STATE, cfg={})
    assert [r["name"] for r in rows] == list(L.NAMES)
    assert set(L.KINDS) == set(L.NAMES)
    assert set(L.MISSING_KEYS_HINT) <= set(L.NAMES)
    assert all(set(r) == {"name", "url", "kind", "why_missing"} for r in rows)


def test_the_agent_supplied_links_name_no_agents_md_key(tmp_path):
    """`active_ticket`, `pr_url` and `confluence_url` are written by `ad-state`. Telling a human to
    add them to AGENTS.md would be telling them to hand-maintain machine state."""
    assert "ticket" not in L.MISSING_KEYS_HINT
    assert "pr" not in L.MISSING_KEYS_HINT
    assert "confluence" not in L.MISSING_KEYS_HINT

    rows = by_name(L.links_for(repo_at(tmp_path), {}, {}, cfg={}))
    assert ".agent/state.json" in rows["ticket"]["why_missing"]
    assert "pr_url" in rows["pr"]["why_missing"]


# --------------------------------------------------------------------------------- the links


def test_a_fully_declared_project_renders_the_whole_rail(tmp_path):
    rows = by_name(L.links_for(repo_at(tmp_path), FULL_FACTS, FULL_STATE, cfg={}))
    assert rows["ticket"]["url"] == f"{CLOUD}/browse/RDSD-101"
    assert rows["board"]["url"] == f"{CLOUD}/jira/software/c/projects/RDSD/boards/3"
    assert rows["report"]["url"] == f"https://app.powerbi.com/groups/{WS}/reports/{REPORT}"
    assert rows["dataset"]["url"] == f"https://app.powerbi.com/groups/{WS}/datasets/{DS}/details"
    assert rows["workspace"]["url"] == f"https://app.powerbi.com/groups/{WS}"
    assert rows["repo"]["url"] == "https://bitbucket.org/acme/rdsd-reporting"
    assert rows["pr"]["url"] == FULL_STATE["pr_url"]
    assert rows["confluence"]["url"] == FULL_STATE["confluence_url"]
    assert rows["folder"]["url"].startswith("file:///")
    assert all(r["why_missing"] == "" for r in rows.values())


def test_a_bare_registration_renders_only_the_folder_and_names_the_keys(tmp_path):
    """A repo registered and never filled in. The rail is one link, and the doctor has a list."""
    rows = L.links_for(repo_at(tmp_path), {}, {}, cfg={})
    assert [r["name"] for r in L.present(rows)] == ["folder"]
    assert L.missing_keys(rows) == ["jira_board_id", "report_id", "ds_id", "ws_id", "bitbucket_repo"]
    assert all(r["why_missing"] for r in rows if not r["url"])


def test_the_board_url_follows_the_flavour(tmp_path):
    """Cloud's board path answers with the dashboard on Data Center, and vice versa. Guessing is
    exactly the broken link this module exists to prevent."""
    dc = dict(FULL_FACTS, jira_url=DC)
    rows = by_name(L.links_for(repo_at(tmp_path), dc, FULL_STATE, cfg={}))
    assert rows["board"]["url"] == f"{DC}/secure/RapidBoard.jspa?rapidView=3"

    # ...and the flavour ad-jira recorded wins over the guess from the hostname.
    rows = by_name(L.links_for(repo_at(tmp_path), dc, FULL_STATE, cfg={"jira": {"flavor": "cloud"}}))
    assert rows["board"]["url"] == f"{DC}/jira/software/c/projects/RDSD/boards/3"


def test_the_jira_site_comes_from_the_project_before_the_machine(tmp_path):
    """One operator, two tenants: the config holds whichever `ad-jira whoami` ran last, which is not
    a property of this repository."""
    cfg = {"jira": {"base_url": DC}}
    rows = by_name(L.links_for(repo_at(tmp_path), FULL_FACTS, FULL_STATE, cfg=cfg))
    assert rows["ticket"]["url"] == f"{CLOUD}/browse/RDSD-101"

    rows = by_name(L.links_for(repo_at(tmp_path), {"jira_project": "RDSD"}, FULL_STATE, cfg=cfg))
    assert rows["ticket"]["url"] == f"{DC}/browse/RDSD-101"


def test_a_pasted_site_without_a_scheme_still_resolves_to_the_site(tmp_path):
    """`jira_url: acme.atlassian.net` is what a paste looks like. Left alone it would produce a
    relative link that resolves against the dashboard's own origin -- a link to the fleet server."""
    facts = dict(FULL_FACTS, jira_url="acme.atlassian.net/")
    rows = by_name(L.links_for(repo_at(tmp_path), facts, FULL_STATE, cfg={}))
    assert rows["ticket"]["url"] == f"{CLOUD}/browse/RDSD-101"


def test_bitbucket_takes_a_url_or_a_slug(tmp_path):
    """Both spellings are in use -- a URL is what a paste gives, `owner/slug` is what the CLI wants
    -- and refusing either means the fact is filled in and the link is still missing."""
    url = "https://bitbucket.acme.local/projects/RDSD/repos/reporting"
    rows = by_name(L.links_for(repo_at(tmp_path), {"bitbucket_repo": url}, {}, cfg={}))
    assert rows["repo"]["url"] == url

    rows = by_name(L.links_for(repo_at(tmp_path), {"bitbucket_repo": "acme/reporting"}, {}, cfg={}))
    assert rows["repo"]["url"] == "https://bitbucket.org/acme/reporting"

    on_prem = {"bitbucket_repo": "acme/reporting", "bitbucket_url": "https://bb.acme.local"}
    rows = by_name(L.links_for(repo_at(tmp_path), on_prem, {}, cfg={}))
    assert rows["repo"]["url"] == "https://bb.acme.local/acme/reporting"


def test_confluence_prefers_the_published_page_and_falls_back_to_the_parent(tmp_path):
    facts = {"jira_url": CLOUD, "confluence_space": "RDSD", "confluence_parent": "98765"}
    rows = by_name(L.links_for(repo_at(tmp_path), facts, {}, cfg={}))
    assert rows["confluence"]["url"] == f"{CLOUD}/wiki/spaces/RDSD/pages/98765"

    # A Data Center wiki is a different host entirely, so the Jira base is not enough for it.
    rows = by_name(L.links_for(repo_at(tmp_path), dict(facts, jira_url=DC), {}, cfg={}))
    assert rows["confluence"]["url"] == ""
    assert "confluence_base" in rows["confluence"]["why_missing"]


def test_the_folder_link_is_a_file_url_with_the_spaces_encoded(tmp_path):
    """`C:/Users/Luna/My Repos` is the path that is always wrong by hand: `file://C:/...` reads the
    drive as a hostname, and a raw space is not a URL."""
    row = by_name(L.links_for(Repo(name="a", path="C:\\Users\\Luna\\My Repos\\rdsd"), {}, {}, cfg={}))
    assert row["folder"]["url"] == "file:///C:/Users/Luna/My%20Repos/rdsd"


def test_show_shaped_input_works_as_well_as_a_repo(tmp_path):
    """`catalogue.show()` hands the tile a dict, the registry hands it a `Repo`. Both are callers."""
    row = by_name(L.links_for({"name": "a", "path": "/srv/rdsd"}, {}, {}, cfg={}))
    assert row["folder"]["url"] == "file:///srv/rdsd"


# --------------------------------------------------------------- never render a broken link


def test_a_ticket_that_is_not_a_key_is_never_browsed_to(tmp_path):
    """`active_ticket` is a free string in `.agent/state.json`. `/browse/refactor the query` is a
    broken link that answers 200 with a "no such issue" page."""
    state = {"active_ticket": "refactor the query"}
    rows = by_name(L.links_for(repo_at(tmp_path), FULL_FACTS, state, cfg={}))
    assert rows["ticket"]["url"] == ""
    assert "not a Jira key" in rows["ticket"]["why_missing"]


def test_a_placeholder_guid_is_not_a_workspace(tmp_path):
    """`project_facts` drops `<workspace guid>` but not `TODO`, and `groups/TODO` opens."""
    for junk in ("TODO", "tbc", "0", "Reporting PRD"):
        rows = by_name(L.links_for(repo_at(tmp_path), {"ws_id": junk, "ds_id": junk}, {}, cfg={}))
        assert rows["workspace"]["url"] == "", junk
        assert rows["dataset"]["url"] == "", junk


def test_a_relative_pr_url_is_refused(tmp_path):
    """A relative `pr_url` would resolve against the dashboard's own origin."""
    rows = by_name(L.links_for(repo_at(tmp_path), {}, {"pr_url": "/pull-requests/42"}, cfg={}))
    assert rows["pr"]["url"] == ""


def test_no_half_filled_fact_block_can_produce_a_url_with_a_hole(tmp_path):
    """The widest test in the file, and the one the module exists for.

    Every subset of the facts, crossed with every subset of the state, and not one rendered URL may
    contain an empty path segment, a leftover placeholder or the word None. A builder that forgets
    to check one of its inputs fails here rather than on the laptop.
    """
    keys = sorted(FULL_FACTS)
    state_keys = sorted(FULL_STATE)
    for drop in itertools.chain.from_iterable(
            itertools.combinations(keys, n) for n in range(len(keys) + 1)):
        facts = {k: v for k, v in FULL_FACTS.items() if k not in drop}
        for state_drop in itertools.chain.from_iterable(
                itertools.combinations(state_keys, n) for n in range(len(state_keys) + 1)):
            state = {k: v for k, v in FULL_STATE.items() if k not in state_drop}
            for row in L.present(L.links_for(repo_at(tmp_path), facts, state, cfg={})):
                url = row["url"]
                after = url.split("://", 1)[1] if "://" in url else url.split(":", 1)[1]
                assert "//" not in after, (row["name"], url)
                assert not after.endswith("/"), (row["name"], url)
                assert "None" not in url and "<" not in url, (row["name"], url)


@pytest.mark.parametrize("name", L.NAMES)
def test_a_missing_link_always_says_why(name, tmp_path):
    rows = by_name(L.links_for(repo_at(tmp_path), {}, {}, cfg={}))
    row = rows[name]
    assert row["url"] or row["why_missing"], name
