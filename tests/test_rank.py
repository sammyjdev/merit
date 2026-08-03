from pathlib import Path

from typer.testing import CliRunner

from merit import cli
from merit.profile import load_profile
from merit.rank import DEFAULT_TOP, extract_title, rank_dir, render, score_text
from merit.schemas import Profile, SkillEntry

FIXTURE = Path(__file__).parent / "fixtures" / "profile_rank.yaml"

runner = CliRunner()


def _profile():
    return load_profile(FIXTURE)


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- score_text ----------------------------------------------------------


def test_alias_hit_scores_as_strong():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "We build REST APIs all day.")
    assert (strong, partial, gap, score) == (1, 0, 0, 2)


def test_skill_name_hit_scores_as_strong():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "You will use FastAPI daily.")
    assert (strong, partial, gap, score) == (1, 0, 0, 2)


def test_alias_and_name_same_skill_counts_once():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "FastAPI and REST APIs are both used here.")
    assert (strong, partial, gap, score) == (1, 0, 0, 2)


def test_gap_penalty_alone():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "Experience with PyTorch required.")
    assert (strong, partial, gap, score) == (0, 0, 1, -1)


def test_gap_combined_with_strong_exact_score():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "FastAPI and PyTorch experience wanted.")
    assert (strong, partial, gap, score) == (1, 0, 1, 1)


def test_boundary_false_positive_does_not_match_substring():
    profile = _profile()
    strong, partial, gap, score = score_text(profile, "We use FastAPIish framework.")
    assert (strong, partial, gap, score) == (0, 0, 0, 0)


def test_partial_skill_name_hit_via_fixture():
    profile = _profile()
    strong, partial, gap, score = score_text(
        profile, "Our stack uses MCP (Model Context Protocol) heavily."
    )
    assert (strong, partial, gap, score) == (0, 1, 0, 1)


def test_partial_alias_hit_via_fixture():
    profile = _profile()
    strong, partial, gap, score = score_text(
        profile, "Experience with the Model Context Protocol is a plus."
    )
    assert (strong, partial, gap, score) == (0, 1, 0, 1)


def test_paren_terminated_name_matches_verbatim_boundary_regression():
    """Regression for the `\\b`-vs-lookaround trap: a name ending in ')' followed
    by a space is not a `\\b` boundary (`\\b` requires a word/non-word transition,
    and ')' then ' ' are both non-word), so a `\\b`-based scan misses it entirely.
    Lookarounds only assert the outer edge isn't a word char, so they still match.
    Uses a standalone profile (no overlapping alias) so nothing else can rescue
    the hit - this MUST fail under `\\b` and pass under lookarounds."""
    profile = Profile(skills=[SkillEntry(id="mcp", name="MCP (Model Context Protocol)", status="partial")])
    strong, partial, gap, score = score_text(
        profile, "Familiar with MCP (Model Context Protocol) tooling."
    )
    assert (strong, partial, gap, score) == (0, 1, 0, 1)


# --- extract_title ---------------------------------------------------------


def test_title_frontmatter_subject_wins_over_heading():
    text = "---\nsubject: Senior Backend Engineer\n---\n\n# A Different Heading\n\nBody.\n"
    assert extract_title(text, "fallback") == "Senior Backend Engineer"


def test_title_heading_used_when_no_frontmatter():
    text = "# Staff Engineer Role\n\nBody text.\n"
    assert extract_title(text, "fallback") == "Staff Engineer Role"


def test_title_filename_stem_fallback_when_neither():
    text = "Just some plain posting text with no heading.\n"
    assert extract_title(text, "posting-stem") == "posting-stem"


def test_title_subject_with_colon_parses_correctly():
    text = "---\nsubject: Re: Senior Engineer: Backend Team\n---\n\nBody.\n"
    assert extract_title(text, "fallback") == "Re: Senior Engineer: Backend Team"


def test_title_with_pipe_is_escaped_in_rendered_table(tmp_path):
    profile = _profile()
    _write(tmp_path, "a.md", "---\nsubject: Backend | Frontend Engineer\n---\n\nUses FastAPI.\n")
    rows, skipped = rank_dir(profile, tmp_path)
    out = render(rows, skipped, DEFAULT_TOP)
    assert not skipped
    assert "Backend \\| Frontend Engineer" in out


# --- rank_dir / render -------------------------------------------------------


def test_ranking_order_across_three_postings(tmp_path):
    profile = _profile()
    _write(tmp_path, "strong_only.md", "# Role A\n\nWe need FastAPI experience.\n")
    _write(tmp_path, "mixed.md", "# Role B\n\nFastAPI and PyTorch both required.\n")
    _write(tmp_path, "gap_only.md", "# Role C\n\nJust PyTorch, nothing else.\n")

    rows, skipped = rank_dir(profile, tmp_path)
    assert not skipped
    assert [r.file for r in rows] == ["strong_only.md", "mixed.md", "gap_only.md"]
    assert [r.score for r in rows] == [2, 1, -1]


def test_non_md_files_ignored(tmp_path):
    profile = _profile()
    _write(tmp_path, "real.md", "# Role\n\nFastAPI required.\n")
    (tmp_path / "state.seen").write_text("something", encoding="utf-8")
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")

    rows, skipped = rank_dir(profile, tmp_path)
    assert [r.file for r in rows] == ["real.md"]
    assert skipped == []


def test_skipped_unreadable_file_reported_and_others_still_rank(tmp_path):
    profile = _profile()
    _write(tmp_path, "good.md", "# Role\n\nFastAPI required.\n")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe invalid")

    rows, skipped = rank_dir(profile, tmp_path)
    assert [r.file for r in rows] == ["good.md"]
    assert len(skipped) == 1
    assert skipped[0].startswith("bad.md:")


def test_top_truncation_default_and_explicit(tmp_path):
    profile = _profile()
    for i in range(25):
        _write(tmp_path, f"posting_{i:02d}.md", "# Role\n\nFastAPI required.\n")

    rows, skipped = rank_dir(profile, tmp_path)
    assert len(rows) == 25

    default_out = render(rows, skipped, DEFAULT_TOP)
    assert default_out.count("| posting_") == 20

    truncated_out = render(rows, skipped, 5)
    assert truncated_out.count("| posting_") == 5


def test_top_non_positive_shows_everything(tmp_path):
    profile = _profile()
    for i in range(3):
        _write(tmp_path, f"posting_{i}.md", "# Role\n\nFastAPI required.\n")

    rows, skipped = rank_dir(profile, tmp_path)
    out = render(rows, skipped, 0)
    assert out.count("| posting_") == 3


# --- CLI ---------------------------------------------------------------


def test_cli_rank_happy_path(tmp_path):
    _write(tmp_path, "a.md", "# Role\n\nFastAPI required.\n")
    _write(tmp_path, "b.md", "# Role\n\nPyTorch only.\n")

    result = runner.invoke(cli.app, ["rank", str(tmp_path), "--profile", str(FIXTURE)])
    assert result.exit_code == 0, result.output
    assert "# MERIT rank" in result.output
    assert "a.md" in result.output and "b.md" in result.output


def test_cli_rank_missing_dir_exits_1():
    result = runner.invoke(cli.app, ["rank", "/no/such/dir", "--profile", str(FIXTURE)])
    assert result.exit_code == 1


def test_cli_rank_top_flag(tmp_path):
    for i in range(3):
        _write(tmp_path, f"p{i}.md", "# Role\n\nFastAPI required.\n")
    result = runner.invoke(
        cli.app, ["rank", str(tmp_path), "--profile", str(FIXTURE), "--top", "1"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("| p") == 1


def test_cli_rank_needs_no_llm_or_state_db(tmp_path, monkeypatch):
    # Deliberately do NOT monkeypatch build_extractor/build_judge/build_writer or
    # MERIT_DB: rank must be deterministic-only. If the command tried to build a
    # model or open a checkpoint DB it would raise here and this test would fail.
    monkeypatch.delenv("MERIT_DB", raising=False)
    _write(tmp_path, "a.md", "# Role\n\nFastAPI required.\n")

    result = runner.invoke(cli.app, ["rank", str(tmp_path), "--profile", str(FIXTURE)])

    assert result.exit_code == 0, result.output
    assert result.exception is None


def test_hit_names_groups_matched_skill_names_by_status():
    from merit.rank import hit_names

    text = "We use FastAPI and REST APIs daily; PyTorch required."
    names = hit_names(_profile(), text)

    assert names["strong"] == ["FastAPI"]  # alias dedups into one skill
    assert names["partial"] == []
    assert names["gap"] == ["PyTorch"]


def test_hit_names_empty_when_nothing_matches():
    from merit.rank import hit_names

    names = hit_names(_profile(), "Sales role, no tech stack.")

    assert names == {"strong": [], "partial": [], "gap": []}


def test_classify_workplace_detects_explicit_signals():
    from merit.rank import classify_workplace

    assert classify_workplace("100% remote role") == "remote"
    assert classify_workplace("Atuacao presencial em SP") == "onsite"
    assert classify_workplace("On-site, Sao Paulo office") == "onsite"
    assert classify_workplace("Modelo hibrido, 2x semana") == "hybrid"
    # hybrid postings mention the office too - hybrid wins over onsite
    assert classify_workplace("Hybrid: 2 days on-site") == "hybrid"
    assert classify_workplace("Great team, great pay") == "unknown"


def test_rank_dir_rows_carry_workplace_and_age(tmp_path):
    _write(
        tmp_path,
        "a.md",
        "---\nsubject: X\ndate: Tue, 28 Jul 2026 15:37:36 +0000\n---\n# X\n\nRemote FastAPI role.",
    )
    _write(tmp_path, "b.md", "# Y\n\nPresencial, REST APIs.")

    rows, _ = rank_dir(_profile(), tmp_path)
    by_file = {r.file: r for r in rows}

    assert by_file["a.md"].workplace == "remote"
    assert by_file["a.md"].age_days is not None and by_file["a.md"].age_days >= 0
    assert by_file["b.md"].workplace == "onsite"
    assert by_file["b.md"].age_days is None
