"""Tests for the PRMS result-code citation resolver and linkifier.

Marc Schut, 2026-09-25: "the system ALWAYS includes the URLs that direct back to
the source of the information (for example:
https://reporting.cgiar.org/reports/result-details/1003?phase=6)".

Verified 2026-09-26 in an anonymous browser: that page is PUBLIC (it renders
the one-result PDF report without a login), ``1003`` is the result CODE and
``phase`` is ``result.version_id``; IPSR-module results use ``ipsr-details``.
The logged-in PRMS application (``reporting.cgiar.org/result/...``,
``prms.cgiar.org``) stays session-gated and must never be emitted as a source.

The tests run against a tiny synthetic snapshot (``result`` + ``version``), so
they are independent of the real PRMS file.
"""

import sqlite3

import pytest

from synapsis.tools import result_code_citation as rcc
from synapsis.tools.result_code_citation import (
    PUBLIC_IPSR_REPORT_TEMPLATE,
    PUBLIC_RESULT_REPORT_TEMPLATE,
    PUBLIC_RESULTS_DASHBOARD,
    GATED_LINK_NOTE,
    REPORT_UNAVAILABLE_NOTE,
    UNKNOWN_CODE_NOTE,
    assert_no_session_gated_url,
    get_result_link,
    is_public_prms_report_url,
    is_session_gated_url,
    linkify_result_codes,
    linkify_result_codes_report,
    normalize_result_code,
    resolve_result_code_url,
    result_code_in_url,
    result_code_status,
    use_citation_db_path,
)

R = "https://reporting.cgiar.org/reports/result-details/{}?phase={}"
I = "https://reporting.cgiar.org/reports/ipsr-details/{}?phase={}"

# version: (id, phase_name, phase_year, status[0 closed / 1 open], app_module_id)
_VERSIONS = [
    (1, "Reporting 2022", 2022, 0, 1),
    (2, "IPSR 2023", 2023, 0, 2),
    (3, "Reporting 2023", 2023, 0, 1),
    (4, "Reporting 2024", 2024, 0, 1),
    (5, "IPSR 2024", 2024, 0, 2),
    (6, "Reporting 2025", 2025, 0, 1),
    (7, "IPSR 2025", 2025, 0, 2),
    (8, "Reporting 2026", 2026, 1, 1),
    (9, "IPSR 2026", 2026, 1, 2),
]

# result: (id, result_code, version_id, result_type_id, source, status_id, is_active)
_RESULTS = [
    # 1003: Marc's example — reported every year, latest published = phase 6.
    (1021, 1003, 1, 7, "Result", 2, 1),
    (4780, 1003, 3, 7, "Result", 2, 1),
    (12741, 1003, 4, 7, "Result", 2, 1),
    (22506, 1003, 6, 7, "Result", 2, 1),
    # result.id 1003 belongs to a DIFFERENT code (985): the id must never be used.
    (1003, 985, 1, 7, "Result", 2, 1),
    # 17: QA'd in 2025, still being edited in the open 2026 phase → link 2025.
    (22383, 17, 6, 7, "Result", 2, 1),
    (30001, 17, 8, 7, "Result", 1, 1),
    # 188: QA'd in 2024, the 2025 row is inactive → link 2024.
    (12652, 188, 4, 7, "Result", 2, 1),
    (22419, 188, 6, 7, "Result", 2, 0),
    # 11855: Innovation Package in the IPSR module → ipsr-details.
    (24001, 11855, 7, 10, "Result", 2, 1),
    # 25665: complementary innovation (IPSR module), never QA'd.
    (25000, 25665, 7, 11, "Result", 1, 1),
    # 26115: W3/bilateral, approved (status 6).
    (29094, 26115, 6, 6, "API", 6, 1),
    # 28814: exists only in the open 2026 phase.
    (40000, 28814, 8, 7, "Result", 2, 1),
    # 42: two-digit code.
    (42, 42, 1, 7, "Result", 2, 1),
    # KNOWN PRMS BUG: IPSR 2023 (v2) / IPSR 2024 (v5) reports fail publicly.
    # 14935: QA'd package in IPSR 2024, still edited in IPSR 2025 → link v7.
    (16597, 14935, 5, 10, "Result", 2, 1),
    (29600, 14935, 7, 10, "Result", 1, 1),
    # 16106 / 8271: exist ONLY in the broken phases → dashboard fallback.
    (17803, 16106, 5, 11, "Result", 2, 1),
    (8869, 8271, 2, 11, "Result", 1, 1),
]


@pytest.fixture()
def snapshot(tmp_path):
    db = tmp_path / "prms_snapshot.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE version (id INTEGER PRIMARY KEY, phase_name TEXT, phase_year INT, "
            "status INT, app_module_id INT)"
        )
        conn.execute(
            "CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INT, version_id INT, "
            "result_type_id INT, source TEXT, status_id INT, is_active INT, title TEXT)"
        )
        conn.executemany("INSERT INTO version VALUES (?,?,?,?,?)", _VERSIONS)
        conn.executemany(
            "INSERT INTO result VALUES (?,?,?,?,?,?,?, 'x')", _RESULTS
        )
    use_citation_db_path(str(db))
    yield db
    use_citation_db_path(None)


@pytest.fixture()
def no_snapshot(tmp_path):
    use_citation_db_path(str(tmp_path / "missing.sqlite"))
    yield
    use_citation_db_path(None)


# ---------------------------------------------------------------------------
# URL format and the deterministic code → (code, phase) mapping
# ---------------------------------------------------------------------------

def test_templates_are_the_verified_public_patterns():
    assert PUBLIC_RESULT_REPORT_TEMPLATE.format(code=1003, phase=6) == (
        "https://reporting.cgiar.org/reports/result-details/1003?phase=6"
    )
    assert PUBLIC_IPSR_REPORT_TEMPLATE.format(code=11855, phase=7) == (
        "https://reporting.cgiar.org/reports/ipsr-details/11855?phase=7"
    )


def test_marc_example_resolves_to_his_exact_url(snapshot):
    assert resolve_result_code_url(1003) == "https://reporting.cgiar.org/reports/result-details/1003?phase=6"
    assert resolve_result_code_url("R1003") == resolve_result_code_url("1003")


def test_uses_result_code_not_result_id(snapshot):
    # result.id 1003 is code 985; code 985's link must carry 985, not 1003.
    assert resolve_result_code_url(985) == R.format(985, 1)


def test_latest_published_phase_wins_over_open_editing_row(snapshot):
    assert resolve_result_code_url(17) == R.format(17, 6)


def test_inactive_rows_are_not_linked_when_an_active_one_exists(snapshot):
    assert resolve_result_code_url(188) == R.format(188, 4)


def test_ipsr_module_uses_ipsr_details(snapshot):
    assert resolve_result_code_url(11855) == I.format(11855, 7)
    assert resolve_result_code_url(25665) == I.format(25665, 7)
    link = get_result_link(11855)
    assert link.module == "ipsr" and link.phase_name == "IPSR 2025"


def test_bilateral_and_open_phase_only_codes(snapshot):
    assert resolve_result_code_url(26115) == R.format(26115, 6)
    assert resolve_result_code_url(28814) == R.format(28814, 8)


def test_broken_ipsr_phase_is_skipped_for_a_later_working_phase(snapshot):
    # QA'd in IPSR 2024 (broken report) but also present in IPSR 2025 → v7.
    assert resolve_result_code_url(14935) == I.format(14935, 7)
    assert get_result_link(14935).report_unavailable is False


def test_code_only_in_broken_ipsr_phases_is_not_linked_and_never_to_the_dashboard(snapshot):
    for code in (16106, 8271):
        assert resolve_result_code_url(code) is None
        assert result_code_status(code) == ("report_unavailable", None)
        link = get_result_link(code)
        assert link.report_unavailable is True and link.url is None
        # the canonical PRMS address is still known (for QA / when PRMS fixes it)
        assert link.report_url == I.format(code, 5 if code == 16106 else 2)


def test_unavailable_codes_get_an_honest_note_once_and_no_link(snapshot):
    report = linkify_result_codes_report(
        "Packages [R16106] and R8271 and R14935; again R16106 and result code 8271."
    )
    t = report.text
    assert f"R16106 ({REPORT_UNAVAILABLE_NOTE}) and R8271 ({REPORT_UNAVAILABLE_NOTE})" in t
    assert t.count(REPORT_UNAVAILABLE_NOTE) == 2          # first mention only
    assert "again R16106 and result code 8271." in t
    assert f"[R14935]({I.format(14935, 7)})" in t
    assert "results-dashboard" not in t and "](" in t
    assert report.unknown == [] and UNKNOWN_CODE_NOTE not in t
    assert sorted(report.unavailable) == ["16106", "8271"]
    assert linkify_result_codes(t) == t  # idempotent


def test_unavailable_code_as_link_target_and_in_a_table(snapshot):
    out = linkify_result_codes(
        "A [seed package](R16106) here.\n\n| Result code | Name |\n|---|---|\n| 16106 | Seed |\n| 1003 | Dairy |\n"
    )
    assert f"A seed package (R16106, {REPORT_UNAVAILABLE_NOTE}) here." in out
    assert "| R16106 | Seed |" in out                       # already noted above: no repeat
    assert f"| [R1003]({R.format(1003, 6)}) | Dairy |" in out
    assert linkify_result_codes(out) == out


def test_env_override_clears_the_broken_phases(snapshot, monkeypatch):
    monkeypatch.setenv(rcc.BROKEN_PHASES_ENV, "")
    assert resolve_result_code_url(16106) == I.format(16106, 5)
    assert resolve_result_code_url(8271) == I.format(8271, 2)
    monkeypatch.setenv(rcc.BROKEN_PHASES_ENV, "2, 5")
    assert resolve_result_code_url(16106) is None
    monkeypatch.setenv(rcc.BROKEN_PHASES_ENV, "garbage")
    assert rcc.broken_report_phases() == rcc.PRMS_BROKEN_IPSR_REPORT_PHASES


def test_no_link_ever_targets_a_known_broken_prms_report_or_the_dashboard(snapshot):
    from synapsis.tools.result_code_citation import PRMS_BROKEN_IPSR_REPORT_PHASES

    for code in {str(r[1]) for r in _RESULTS}:
        url = resolve_result_code_url(code)
        if url is None:
            continue
        assert is_public_prms_report_url(url), url
        assert "results-dashboard" not in url
        for phase in PRMS_BROKEN_IPSR_REPORT_PHASES:
            assert not url.endswith(f"ipsr-details/{code}?phase={phase}"), url


def test_every_code_in_the_snapshot_is_a_report_link_or_honestly_unavailable(snapshot):
    for code in {str(r[1]) for r in _RESULTS}:
        status, url = result_code_status(code)
        assert status in ("linked", "report_unavailable"), (code, status)
        assert (url is not None) == (status == "linked")


def test_unknown_code_is_never_guessed(snapshot):
    assert resolve_result_code_url(999999) is None
    assert get_result_link("R999999") is None
    assert result_code_status(999999) == ("unknown", None)


def test_snapshot_unavailable_never_falls_back_to_the_dashboard(no_snapshot):
    assert resolve_result_code_url(1003) is None
    assert result_code_status(1003) == ("no_snapshot", None)


def test_normalize():
    assert normalize_result_code("R123") == "123"
    assert normalize_result_code(" 456 ") == "456"
    assert normalize_result_code("R017") == "17"
    assert normalize_result_code("not-a-code") is None
    assert normalize_result_code(None) is None


def test_malformed_code_degrades_to_none(snapshot):
    assert resolve_result_code_url("") is None
    assert resolve_result_code_url("abc") is None
    assert resolve_result_code_url(None) is None


def test_index_is_cached_per_snapshot_file(snapshot):
    first = rcc.citation_index()
    assert rcc.citation_index() is first  # same object: lru-cached, no re-read


# ---------------------------------------------------------------------------
# NEGATIVE TESTS — never emit a login-gated page as if it were public
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "gated_url",
    [
        "https://reporting.cgiar.org/",
        "https://reporting.cgiar.org/result/result-detail/1003/general-information?phase=6",
        "https://reporting.cgiar.org/result-details/28583?phase=1",
        "https://reporting.cgiar.org/reports/result-details/1003",  # no phase: not the public report
        "https://prms.cgiar.org/result/28583",
        "https://www.cgiar.org/food-security-impact/results-dashboard/result-details/28583",
    ],
)
def test_session_gated_patterns_detected(gated_url):
    assert is_session_gated_url(gated_url) is True
    with pytest.raises(ValueError):
        assert_no_session_gated_url(gated_url)


@pytest.mark.parametrize(
    "public_url",
    [
        "https://reporting.cgiar.org/reports/result-details/1003?phase=6",
        "https://reporting.cgiar.org/reports/ipsr-details/11855?phase=7",
        PUBLIC_RESULTS_DASHBOARD,
    ],
)
def test_public_report_pages_are_not_gated(public_url):
    assert is_session_gated_url(public_url) is False


def test_is_public_prms_report_url():
    assert is_public_prms_report_url(R.format(1003, 6))
    assert not is_public_prms_report_url("https://reporting.cgiar.org/reports/result-details/1003?phase=x")
    assert not is_public_prms_report_url("https://evil.example/reports/result-details/1003?phase=6")


def test_resolver_never_emits_session_gated_url(snapshot):
    for code, *_ in [(r[1],) for r in _RESULTS]:
        url = resolve_result_code_url(code)
        if code in (16106, 8271):  # only broken IPSR phases: no link at all
            assert url is None
            continue
        assert url is not None
        assert not is_session_gated_url(url), f"gated URL for {code}: {url}"


def test_hand_written_gated_link_is_defused(snapshot):
    text = (
        "See [the record](https://reporting.cgiar.org/result/result-detail/1003/general-information?phase=6) "
        "or https://prms.cgiar.org/result/1003 for details."
    )
    out = linkify_result_codes(text)
    assert "](https://reporting.cgiar.org/result/" not in out
    assert "PRMS login required" in out
    assert "`https://prms.cgiar.org/result/1003`" in out  # visible, not clickable


# ---------------------------------------------------------------------------
# Linkifier — every code the agent mentions becomes a clickable public link
# ---------------------------------------------------------------------------

def test_bracket_tokens(snapshot):
    out = linkify_result_codes("This innovation [R1003] reached IRL 9.")
    assert out == f"This innovation [R1003]({R.format(1003, 6)}) reached IRL 9."


def test_bracket_group_of_several_codes(snapshot):
    out = linkify_result_codes("Examples [R17, R42; R188].")
    assert f"[R17]({R.format(17, 6)}), [R42]({R.format(42, 1)}), [R188]({R.format(188, 4)})" in out


def test_bare_codes_in_prose_parentheses_and_punctuation(snapshot):
    text = "Dairy (R1003), yams R17; tools: R188. Also **R42**, and R26115!"
    out = linkify_result_codes(text)
    assert f"([R1003]({R.format(1003, 6)}))" in out
    assert f"yams [R17]({R.format(17, 6)});" in out
    assert f"tools: [R188]({R.format(188, 4)})." in out
    assert f"**[R42]({R.format(42, 1)})**" in out
    assert f"[R26115]({R.format(26115, 6)})!" in out


def test_codes_in_lists(snapshot):
    text = "- R1003 dairy genomics\n- R17 yams\n1. R11855 package"
    out = linkify_result_codes(text)
    assert f"- [R1003]({R.format(1003, 6)}) dairy" in out
    assert f"- [R17]({R.format(17, 6)}) yams" in out
    assert f"1. [R11855]({I.format(11855, 7)}) package" in out


def test_result_code_phrases(snapshot):
    text = "Result codes: 1003, 188 and 17 are incremental; result code 26115 is bilateral."
    out = linkify_result_codes(text)
    assert f"Result codes: [1003]({R.format(1003, 6)}), [188]({R.format(188, 4)}) and [17]({R.format(17, 6)})" in out
    assert f"result code [26115]({R.format(26115, 6)}) is" in out


def test_table_code_column_and_inline_codes(snapshot):
    text = (
        "| Result code | Innovation | Year |\n"
        "|---|---|---|\n"
        "| 1003 | Dairy genomics | 2025 |\n"
        "| R188 | Breeding tools (see R17) | 2024 |\n"
        "| 999999 | Unknown | 2024 |\n"
    )
    out = linkify_result_codes(text)
    lines = out.split("\n")
    assert lines[2] == f"| [R1003]({R.format(1003, 6)}) | Dairy genomics | 2025 |"
    assert f"| [R188]({R.format(188, 4)}) |" in lines[3]
    assert f"(see [R17]({R.format(17, 6)}))" in lines[3]
    # years in other columns are never touched; unknown code left as written
    assert lines[2].endswith("| 2025 |")
    assert lines[4] == "| 999999 | Unknown | 2024 |"


def test_already_linked_codes_are_not_double_linked(snapshot):
    text = f"Already linked [R1003]({R.format(1003, 6)}) stays as-is."
    assert linkify_result_codes(text) == text


def test_idempotent(snapshot):
    text = "[R1003] and R17, result code 188, and\n| Code |\n|---|\n| 42 |\n"
    once = linkify_result_codes(text)
    assert linkify_result_codes(once) == once
    assert once.count("](https://") == 4


def test_legacy_dashboard_links_are_upgraded(snapshot):
    text = "[R188](https://www.cgiar.org/food-security-impact/results-dashboard/?result_code=188) radical"
    assert linkify_result_codes(text) == f"[R188]({R.format(188, 4)}) radical"


DASH = "https://www.cgiar.org/food-security-impact/results-dashboard"


@pytest.mark.parametrize(
    "written, expected",
    [
        # model-written dashboard deep link (the dashboard ignores the parameter)
        (f"[R1003]({DASH}/?result_code=1003)", f"[R1003]({R.format(1003, 6)})"),
        (f"[Dairy genomics]({DASH}?result_code=1003)", f"[Dairy genomics]({R.format(1003, 6)})"),
        # dashboard HOME linked from a code
        (f"[R11855]({DASH}/)", f"[R11855]({I.format(11855, 7)})"),
        (f"[11855]({DASH})", f"[11855]({I.format(11855, 7)})"),
        # hand-written report URL with the wrong route / a phase where the code is not
        (f"[R11855]({R.format(11855, 7)})", f"[R11855]({I.format(11855, 7)})"),
        (f"[R1003]({R.format(1003, 8)})", f"[R1003]({R.format(1003, 6)})"),
        # no phase (would be gated) → resolved
        ("[R1003](https://reporting.cgiar.org/reports/result-details/1003)", f"[R1003]({R.format(1003, 6)})"),
        # IPSR 2024 (broken) for a code that has IPSR 2025 → v7
        (f"[R14935]({I.format(14935, 5)})", f"[R14935]({I.format(14935, 7)})"),
        # code with no working report at all → honest note, no link
        (f"[R16106]({DASH}/?result_code=16106)", f"R16106 ({REPORT_UNAVAILABLE_NOTE})"),
        (f"[Seed package]({I.format(16106, 5)})", f"Seed package (R16106, {REPORT_UNAVAILABLE_NOTE})"),
        # bare URLs in prose
        (f"See {DASH}/?result_code=1003 now", f"See {R.format(1003, 6)} now"),
        (f"See <{DASH}/?result_code=11855>", f"See <{I.format(11855, 7)}>"),
        (f"See {DASH}/?result_code=16106.", f"See R16106 ({REPORT_UNAVAILABLE_NOTE})."),
        # unknown code on the dashboard → flagged, no dashboard link
        (f"[R77777]({DASH}/?result_code=77777)", f"R77777 ({UNKNOWN_CODE_NOTE})"),
    ],
)
def test_model_written_result_urls_are_rewritten_to_the_prms_report(snapshot, written, expected):
    out = linkify_result_codes(written)
    assert out == expected
    assert linkify_result_codes(out) == out


def test_hand_written_link_to_another_working_phase_is_kept(snapshot):
    # the 2024 edition of R1003 is a real, working PRMS report: keep it
    text = f"The 2024 report [R1003]({R.format(1003, 4)})."
    assert linkify_result_codes(text) == text


def test_portal_link_without_a_result_is_left_alone(snapshot):
    text = f"Cross-check with the [CGIAR Results Dashboard]({DASH}/) and {DASH}."
    assert linkify_result_codes(text) == text


def test_marc_example_11180_in_a_real_snapshot_shape(snapshot, tmp_path):
    # 11180: Innovation Package reported in IPSR 2023, 2024 and 2025 (as in the
    # 13-Sep snapshot) → Marc's exact URL, never the broken 2023/2024 report.
    import sqlite3 as _sq
    with _sq.connect(snapshot) as conn:
        conn.executemany("INSERT INTO result VALUES (?,?,?,?,?,?,?, 'x')", [
            (11809, 11180, 2, 10, "Result", 2, 1),
            (19913, 11180, 5, 10, "Result", 2, 1),
            (29633, 11180, 7, 10, "Result", 2, 1),
        ])
    use_citation_db_path(str(snapshot))
    assert resolve_result_code_url("R11180") == "https://reporting.cgiar.org/reports/ipsr-details/11180?phase=7"
    out = linkify_result_codes(f"[R11180]({DASH}/?result_code=11180) and [R11180]({I.format(11180, 5)})")
    assert out == f"[R11180]({I.format(11180, 7)}) and [R11180]({I.format(11180, 7)})"


def test_result_code_in_url():
    assert result_code_in_url(f"{DASH}/?result_code=1003") == "1003"
    assert result_code_in_url(R.format(1003, 6)) == "1003"
    assert result_code_in_url("https://reporting.cgiar.org/reports/ipsr-details/11180") == "11180"
    assert result_code_in_url(DASH) is None
    assert result_code_in_url("https://example.org/?result_code=1003") is None
    assert result_code_in_url("https://reporting.cgiar.org/result/result-detail/1003/general-information") is None


def test_gated_urls_are_never_emitted_even_when_the_code_is_known(snapshot):
    gated = "https://reporting.cgiar.org/result/result-detail/1003/general-information?phase=6"
    for text in (f"[R1003]({gated})", f"See {gated}", "https://prms.cgiar.org/result/1003"):
        out = linkify_result_codes(text)
        assert f"]({gated})" not in out and "](https://prms." not in out
        assert GATED_LINK_NOTE in out


def test_code_as_link_target_for_funder_prose(snapshot):
    out = linkify_result_codes("A [dairy genomics programme](R1003) in East Africa.")
    assert out == f"A [dairy genomics programme]({R.format(1003, 6)}) in East Africa."


def test_unknown_codes_left_untouched_but_flagged(snapshot):
    report = linkify_result_codes_report("Real R1003, invented R77777 and a cited [R88888].")
    assert "R77777" in report.text and "[R77777]" not in report.text  # prose: untouched
    assert f"R88888 ({UNKNOWN_CODE_NOTE})" in report.text               # citation: visibly flagged
    assert sorted(report.unknown) == ["77777", "88888"]
    assert report.linked == ["1003"]
    assert report.index_available is True


def test_unknown_link_target_is_flagged(snapshot):
    out = linkify_result_codes("A [made-up innovation](R77777).")
    assert out == f"A made-up innovation (R77777 {UNKNOWN_CODE_NOTE})."


def test_non_codes_are_never_linked(snapshot):
    text = (
        "In [2024] and [1] the R2 score was 0.8; IR64 rice; R1-nj marker; "
        "R&D spend; version R17.5; path /data/R1003; id=R1003."
    )
    assert linkify_result_codes(text) == text


def test_code_after_a_slash_separator_is_linked(snapshot):
    """QA-4 D7: "[R26008](…)/R28583" left the second code bare."""
    out = linkify_result_codes("Pair: [R1003]/R17 and R188/R42; also (R1003) /R17.")
    assert f"[R1003]({R.format(1003, 6)})/[R17]({R.format(17, 6)})" in out
    assert f"[R188]({R.format(188, 4)})/[R42]({R.format(42, 1)})" in out
    assert f"/[R17]({R.format(17, 6)})." in out
    linked = linkify_result_codes(f"[R1003]({R.format(1003, 6)})/R17")
    assert linked == f"[R1003]({R.format(1003, 6)})/[R17]({R.format(17, 6)})"


def test_path_segments_with_codes_stay_unlinked(snapshot):
    for text in ("path /data/R1003", "see data/R1003/R17 here", "x/R1003", "IR64/R1003"):
        assert linkify_result_codes(text) == text, text


def test_code_spans_fences_charts_and_urls_are_protected(snapshot):
    text = (
        "Inline `R1003` stays.\n"
        "```sql\nSELECT * FROM result WHERE result_code = 1003; -- R1003\n```\n"
        '<chart>{"chartType":"bar","data":[{"name":"R1003","v":1}]}</chart>\n'
        "Source: https://example.org/R1003/result_code=1003\n"
    )
    assert linkify_result_codes(text) == text


def test_no_snapshot_mode_leaves_codes_plain_and_does_not_flag(no_snapshot):
    report = linkify_result_codes_report("See [R1003] and R17.")
    assert report.index_available is False
    assert report.text == "See R1003 and R17."
    assert UNKNOWN_CODE_NOTE not in report.text and "results-dashboard" not in report.text


def test_no_snapshot_mode_drops_dashboard_links_for_results(no_snapshot):
    out = linkify_result_codes(
        "[R1003](https://www.cgiar.org/food-security-impact/results-dashboard/?result_code=1003)"
    )
    assert out == "R1003"


def test_linkify_empty_and_none():
    assert linkify_result_codes("") == ""
    assert linkify_result_codes(None) == ""


def test_output_never_contains_gated_link(snapshot):
    out = linkify_result_codes("[R1003] R17 [R11855] result code 26115")
    import re
    for href in re.findall(r"\]\((https?://[^)]+)\)", out):
        assert not is_session_gated_url(href)


# ---------------------------------------------------------------------------
# Call site: the chat handler persists AND shows the linked text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [True, False])
async def test_chat_handler_links_persisted_and_live_text(snapshot, streamed):
    from unittest.mock import AsyncMock, patch

    from claude_agent_sdk import TextBlock

    from synapsis import message_handlers

    sent: list[dict] = []

    async def send_json(payload, sid=None):
        sent.append(payload)

    raw = "Dairy genomics R1003 is at IRL 9."
    linked = f"Dairy genomics [R1003]({R.format(1003, 6)}) is at IRL 9."
    with patch.object(message_handlers, "save_message", new=AsyncMock()) as save:
        await message_handlers.handle_assistant_block(
            TextBlock(text=raw), "sid-1", streamed_text=streamed,
            streamed_thinking=False, send_json=send_json,
        )
    save.assert_awaited_once_with("sid-1", "text", {"content": linked})
    if streamed:
        assert sent == [{"type": "text_links", "original": raw, "content": linked}]
    else:
        assert sent == [{"type": "text", "content": linked}]


@pytest.mark.asyncio
async def test_chat_handler_sends_no_extra_frame_when_nothing_to_link(snapshot):
    from unittest.mock import AsyncMock, patch

    from claude_agent_sdk import TextBlock

    from synapsis import message_handlers

    sent: list[dict] = []

    async def send_json(payload, sid=None):
        sent.append(payload)

    with patch.object(message_handlers, "save_message", new=AsyncMock()):
        await message_handlers.handle_assistant_block(
            TextBlock(text="No codes here."), "sid-1", streamed_text=True,
            streamed_thinking=False, send_json=send_json,
        )
    assert sent == []


@pytest.mark.asyncio
async def test_result_text_is_linked_like_the_text_rows(snapshot):
    """QA-4 D1: the ``result`` row repeats the final answer. It must be linked
    exactly like the ``text`` row, so a reopened chat can de-duplicate it and
    never shows a second, unlinked copy of the answer."""
    from unittest.mock import AsyncMock, patch

    from claude_agent_sdk import ResultMessage, TextBlock

    from synapsis import message_handlers

    sent: list[dict] = []

    async def send_json(payload, sid=None):
        sent.append(payload)

    raw = "Top result: [R1003] and R17."
    with patch.object(message_handlers, "save_message", new=AsyncMock()) as save, \
            patch.object(message_handlers, "save_claude_session_id", new=AsyncMock()):
        await message_handlers.handle_assistant_block(
            TextBlock(text=raw), "sid-1", streamed_text=True,
            streamed_thinking=False, send_json=send_json,
        )
        await message_handlers.handle_result_message(
            ResultMessage(subtype="success", duration_ms=10, duration_api_ms=5,
                          is_error=False, num_turns=1, session_id="sdk-1",
                          total_cost_usd=0.01, result=raw),
            "sid-1", send_json,
        )
    text_row = save.await_args_list[0].args[2]["content"]
    result_row = save.await_args_list[1].args[2]["result_text"]
    assert result_row == text_row
    assert f"[R1003]({R.format(1003, 6)})" in result_row
    frame = next(p for p in sent if p.get("type") == "result")
    assert frame["result_text"] == text_row


@pytest.mark.asyncio
async def test_empty_result_text_stays_empty(snapshot):
    from unittest.mock import AsyncMock, patch

    from claude_agent_sdk import ResultMessage

    from synapsis import message_handlers

    async def send_json(payload, sid=None):
        pass

    with patch.object(message_handlers, "save_message", new=AsyncMock()) as save, \
            patch.object(message_handlers, "save_claude_session_id", new=AsyncMock()):
        await message_handlers.handle_result_message(
            ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                          is_error=False, num_turns=1, session_id="sdk-1", result=None),
            "sid-1", send_json,
        )
    assert save.await_args.args[2]["result_text"] == ""


@pytest.mark.parametrize(
    "text",
    ["`" * 5000 + " R1003", "[" * 5000 + "R1003", ("[abc " * 3000) + "] (x", "|" * 10000],
)
def test_pathological_input_stays_fast(snapshot, text):
    import time

    t0 = time.perf_counter()
    linkify_result_codes(text)
    assert time.perf_counter() - t0 < 1.0
