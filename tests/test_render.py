from pathlib import Path

import pytest

import render_cv

ROOT = Path(__file__).resolve().parent.parent
PERSONA = ROOT / "benchmark" / "persona" / "master-cv.md"


def test_parse_finds_every_block_type():
    blocks = render_cv.parse(PERSONA.read_text(encoding="utf-8"))
    kinds = {b["type"] for b in blocks}
    assert {"name", "contact", "tagline", "section", "skill", "project", "job"} <= kinds
    job = next(b for b in blocks if b["type"] == "job")
    assert job["title"] == "Contoso Logistics Ltd" and job["role"] == "Data Platform Lead"


def test_html_uses_bundled_style_and_title():
    html = render_cv.to_html(render_cv.parse(PERSONA.read_text(encoding="utf-8")), False, "Sam Example CV")
    assert "<title>Sam Example CV</title>" in html and "size: A4" in html and 'lang="en-GB"' in html
    assert '<a href="mailto:sam@example.com">' in html


def test_letter_switches_paper_and_language():
    html = render_cv.to_html([], True, "x")
    assert "size: Letter" in html and 'lang="en-US"' in html


def test_missing_explicit_browser_is_none(tmp_path):
    assert render_cv.find_browser(str(tmp_path / "no-such-browser.exe")) is None


def test_only_web_and_mail_links_become_anchors():
    html = render_cv.inline_html("[safe](https://example.com) [mail](mailto:sam@example.com) [bad](javascript:alert)")
    assert '<a href="https://example.com">safe</a>' in html and '<a href="mailto:sam@example.com">' in html
    assert "javascript:" not in html and "bad" in html


def test_no_browser_still_writes_html_and_exits_3(tmp_path):
    import os
    import subprocess
    import sys

    md = tmp_path / "Sam Example CV.md"
    md.write_text(PERSONA.read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "CV_BROWSER": str(tmp_path / "no-such-browser")}
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_cv.py"), str(md)], env=env,
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 3, run.stdout + run.stderr
    assert (tmp_path / "Sam Example CV.html").exists() and not (tmp_path / "Sam Example CV.pdf").exists()
    assert "PDF:  not produced" in run.stdout


@pytest.mark.skipif(render_cv.find_browser() is None, reason="no Edge, Chrome or Chromium installed")
def test_renders_persona_pdf(tmp_path):
    md = tmp_path / "Sam Example CV.md"
    md.write_text(PERSONA.read_text(encoding="utf-8"), encoding="utf-8")
    blocks = render_cv.parse(md.read_text(encoding="utf-8"))
    html_path = tmp_path / "Sam Example CV.html"
    html_path.write_text(render_cv.to_html(blocks, False, md.stem), encoding="utf-8")
    produced, pages = render_cv.print_pdf(html_path, tmp_path / "Sam Example CV.pdf", render_cv.find_browser())
    assert produced and pages in (None, 1)


def test_grades_with_asterisks_stay_literal():
    assert render_cv.inline_html("Maths (A*), Physics (A*), Chemistry (A)") == "Maths (A*), Physics (A*), Chemistry (A)"
    assert render_cv.inline_html("*Data Lead* and **AWS**") == "<em>Data Lead</em> and <strong>AWS</strong>"


def test_emphasis_never_reaches_into_a_link():
    html = render_cv.inline_html("[docs](https://example.com/a*b*c) and *more*")
    assert '<a href="https://example.com/a*b*c">docs</a>' in html and "<em>more</em>" in html


def test_summary_without_italics_is_still_the_summary():
    blocks = render_cv.parse("# Sam Example\n\nLondon, UK • sam@example.com\n\nData engineer.\n\n## SKILLS\n")
    assert [b["type"] for b in blocks[:3]] == ["name", "contact", "tagline"]


def test_partly_bold_summary_keeps_its_markup_and_grade():
    blocks = render_cv.parse("# Sam Example\n\nsam@example.com\n\n**Senior engineer** with grade A*\n\n## X\n")
    tagline = next(b for b in blocks if b["type"] == "tagline")
    assert render_cv.inline_html(tagline["text"]) == "<strong>Senior engineer</strong> with grade A*"


def test_en_dash_header_and_partly_italic_role_stay_one_job():
    md = "# Sam\n\n## EXPERIENCE\n\n**Contoso** – *Mar 2021 – Present*\n*Analyst* – London\n- Built a dashboard\n"
    [job] = [b for b in render_cv.parse(md) if b["type"] == "job"]
    assert job["role"] == "*Analyst* – London" and job["bullets"] == ["Built a dashboard"]


def test_only_known_browser_executables_are_accepted(tmp_path):
    impostor = tmp_path / "evil.bat"
    impostor.write_text("echo hi", encoding="utf-8")
    assert render_cv.find_browser(str(impostor)) is None
    assert render_cv.find_browser(str(tmp_path)) is None  # a folder is not a browser
