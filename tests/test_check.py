"""check_cv: number parsing, names, headers and source loading. The number policy has its own tests."""
import pytest

import check_cv
from check_cv import Num, check_cv as check, parse_numbers, sources_from_texts

MASTER = """# Sam Example

London, UK • 07700 900123 • sam@example.com • example.com/sam

*Data engineer from an operations background.*

## EXPERIENCE

**Contoso Logistics Ltd** - *Mar 2021 – Present*
*Data Platform Lead*
- Leads a team of 3 building the company's data platform on AWS
- Saved about 15 hours a week; cut mileage by 12% across 18 vans

**RouteWise** | Python, PostgreSQL
- Replans in under 30 seconds
"""

FACTS = """# Career facts

## 1. Usable as written
- Built a dashboard adopted by 25 supervisors

## 2. Unconfirmed: do not use until confirmed
- Published a case study in the Example Freight Journal (2026)
"""


@pytest.fixture
def sources():
    return sources_from_texts([MASTER, FACTS])


@pytest.fixture
def exact_policy(monkeypatch):
    """Isolate these tests from the number policy: any equal value counts."""
    monkeypatch.setattr(check_cv, "value_supported", lambda claim, cands: any(c.value == claim.value for c in cands))


# ---------------------------------------------------------------- numbers

@pytest.mark.parametrize("text, value, unit, qualifier", [
    ("£30,000", 30000.0, "£", ""),
    ("£30k", 30000.0, "£", ""),
    ("over 1,000", 1000.0, "", "at_least"),
    ("5,000+", 5000.0, "", "at_least"),
    ("~250", 250.0, "", "approx"),
    ("around 250", 250.0, "", "approx"),
    ("up to 40", 40.0, "", "at_most"),
    ("8.5%", 8.5, "%", ""),
    ("2021", 2021.0, "year", ""),
    ("1.2 million", 1200000.0, "", ""),
])
def test_parse_numbers(text, value, unit, qualifier):
    [n] = parse_numbers(text)
    assert (n.value, n.unit, n.qualifier) == (value, unit, qualifier)


@pytest.mark.parametrize("text", ["AWS S3", "MP3", "x86", "GPT4"])
def test_digits_inside_names_are_not_numbers(text):
    assert parse_numbers(text) == []


def test_ratio_and_score_parts():
    assert [n.value for n in parse_numbers("2:2 and 41/50")] == [2, 2, 41, 50]


def test_compatible_units():
    pct, gbp, plain, year = (Num(12, "%", "", "12%"), Num(12, "£", "", "£12"), Num(12, "", "", "12"),
                             Num(2021, "year", "", "2021"))
    assert check_cv.compatible(plain, gbp)          # a plain count may drop a currency
    assert not check_cv.compatible(gbp, pct)        # £12 cannot borrow 12%
    assert not check_cv.compatible(plain, pct)
    assert not check_cv.compatible(plain, year)     # a count cannot borrow a year


# ---------------------------------------------------------------- sources

def test_unconfirmed_section_is_not_a_source(sources, exact_policy):
    findings = check("- Published a case study in the Example Freight Journal (2026)", sources)
    assert {f.term for f in findings} >= {"Freight", "2026"}


def test_section_one_facts_are_sources(sources, exact_policy):
    assert check("- Built a dashboard adopted by 25 supervisors", sources) == []


def test_contact_line_digits_back_nothing(sources, exact_policy):
    findings = check("- Served 900123 customers", sources)
    assert [f.kind for f in findings] == ["number"]


# ---------------------------------------------------------------- names

def test_invented_tool_is_flagged(sources, exact_policy):
    findings = check("- Built the platform on AWS with Kubernetes", sources)
    assert [(f.kind, f.term) for f in findings] == [("name", "Kubernetes")]


def test_title_case_sentence_opener_is_skipped_but_acronyms_are_not(sources, exact_policy):
    assert check("- Delivered a team of 3 on AWS", sources) == []
    assert [f.term for f in check("- MSc holder", sources)] == ["MSc"]


def test_skills_line_checks_every_item(sources, exact_policy):
    findings = check("**Data engineering:** Python, Spark", sources)
    assert [f.term for f in findings] == ["Spark"]


def test_possessive_and_plural_forms_match(sources, exact_policy):
    assert check("- Grew Contoso's data platforms on AWS", sources) == []


def test_allow_list(sources, exact_policy):
    assert check("- Built the platform on Kubernetes", sources, allow={"kubernetes"}) == []


def test_links_keep_text_drop_url(sources, exact_policy):
    assert check("- Shipped [RouteWise](https://www.example.com/sam/) on AWS", sources) == []  # www and / ignored


# ---------------------------------------------------------------- headers

def test_unchanged_header_and_role_pass(sources, exact_policy):
    cv = "**Contoso Logistics Ltd** - *Mar 2021 – Present*\n*Data Platform Lead*"
    assert check(cv, sources) == []


def test_changed_dates_title_and_project_are_flagged(sources, exact_policy):
    assert [f.kind for f in check("**Contoso Logistics Ltd** - *Jan 2020 – Present*", sources)] == ["header"]
    cv = "**Contoso Logistics Ltd** - *Mar 2021 – Present*\n*Head of Data*"
    assert [f.kind for f in check(cv, sources)] == ["role"]
    assert [f.kind for f in check("**DeliveryBot** | Python", sources)] == ["project"]


def test_swapped_contact_details_are_flagged(sources, exact_policy):
    cv = MASTER.replace("sam@example.com", "sam@elsewhere.example").replace("07700 900123", "07700 900999")
    terms = {f.term for f in check(cv, sources) if f.kind == "contact"}
    assert terms == {"sam@elsewhere.example", "07700900999"}


def test_link_targets_must_be_in_the_sources(sources, exact_policy):
    assert check("- Shipped [RouteWise](https://example.com/sam) on AWS", sources) == []
    findings = check("- Shipped [RouteWise](https://other.example/routewise) on AWS", sources)
    assert [(f.kind, f.term) for f in findings] == [("contact", "other.example/routewise")]


def test_a_different_profile_on_the_same_site_is_flagged(sources, exact_policy):
    findings = check("- Built at [my site](https://example.com/someone-else)", sources)
    assert [(f.kind, f.term) for f in findings] == [("contact", "example.com/someone-else")]


def test_a_summary_naming_a_library_is_still_checked(sources, exact_policy):
    cv = "# Sam Example\n\nLondon, UK • sam@example.com\n\nEngineer with 45 years in Node.js and Kubernetes at Google.\n\n## X\n"
    terms = {f.term for f in check(cv, sources)}
    assert {"45", "Kubernetes", "Google"} <= terms


def test_roles_under_other_header_layouts_are_kept(exact_policy):
    master = "# Sam Example\n\n## EXPERIENCE\n\n**Contoso** (2019 - 2021)\n*Analyst*\n- Built a dashboard\n"
    src = sources_from_texts([master])
    assert check("**Contoso** (2019 - 2021)\n*Analyst*", src) == []


def test_a_comma_count_matches_a_year_shaped_count(exact_policy):
    src = sources_from_texts(["- Served 2000 customers\n"])
    assert check("- Served 2,000 customers", src) == []


def test_a_bulleted_bold_name_is_checked(sources, exact_policy):
    assert [f.term for f in check("- **Initech**: led the migration", sources)] == ["Initech"]


def test_phone_formats_are_compared_by_digits():
    assert check_cv._phone_key("+44 7700 900123") == check_cv._phone_key("07700 900123") == "07700900123"
    assert check_cv._phone_key("+44 (0)7700-900-123") == "07700900123"


def test_library_names_in_body_text_are_not_websites(sources, exact_policy):
    src = sources_from_texts([MASTER + "- Charts in Node.js\n"])
    assert check("- Charts in Node.js", src) == []


@pytest.mark.parametrize("cv, kinds", [
    ("**Contoso Logistics Ltd** – *Mar 2021 – Present*\n*Data Platform Lead*", []),        # en dash: same
    ("**Initech Ltd** – *Mar 2021 – Present*\n*Head of Data*", ["header", "role"]),
    ("**Initech Ltd** - *Mar 2021 – Present* | London", ["header"]),                           # text after date
    ("**Contoso Logistics Ltd** - *Mar 2021 – Present*\n*Head of Data* – London", ["role"]),     # partly italic
    ("**Contoso Logistics Ltd** - *Mar 2021 – Present*\n*Data Platform Lead* – London", []),
    ("**Pathfinder** - [example.com/p](https://example.com/p)", ["contact", "project"]),        # link-only project
])
def test_header_layout_variants(sources, exact_policy, cv, kinds):
    assert [f.kind for f in check(cv, sources)] == kinds


def test_summary_is_checked_in_any_formatting(sources, exact_policy):
    cv = "# Sam Example\n\nLondon, UK • sam@example.com\n\nPrincipal engineer with Kubernetes,\nand Snowflake.\n\n## X\n"
    # "Principal" opens the sentence but is not a verb, so an invented seniority is caught too
    assert {f.term for f in check(cv, sources)} == {"Principal", "Kubernetes", "Snowflake"}


def test_abbreviations_do_not_end_a_sentence(sources, exact_policy):
    assert [f.term for f in check("- Built pipelines with cloud tools, e.g. Snowflake jobs", sources)] == ["Snowflake"]


def test_tools_listed_in_a_skills_label_are_checked(sources, exact_policy):
    findings = check("**Cloud (AWS, Azure, GCP):** Python", sources)
    assert [f.term for f in findings] == ["Azure", "GCP"]


def test_upgraded_grade_is_flagged():
    src = sources_from_texts(["# Sam Example\n\n## EDUCATION\n- A Levels: Maths (A), Physics (B)\n"])
    assert [f.term for f in check("- A Levels: Maths (A*), Physics (B)", src)] == ["A*"]


def test_name_line_comes_from_the_first_source_and_can_be_allowed(exact_policy):
    src = sources_from_texts(["# Sam Example\n", "# Career facts\n"])
    assert src.name_line == "# Sam Example"
    assert check("# Samuel Example\n\n## X\n", src, allow={"# samuel example"}) == []


def test_a_year_shaped_count_can_match_a_plain_count(exact_policy):
    src = sources_from_texts(["- Served 2,000 customers\n"])
    assert check("- Served 2000 customers", src) == []


def test_unreadable_source_exits_2(tmp_path):
    import subprocess
    import sys

    cv = tmp_path / "cv.md"
    cv.write_text("- x\n", encoding="utf-8")
    bad = tmp_path / "master-cv.md"
    bad.write_bytes("café".encode("utf-16"))
    run = subprocess.run([sys.executable, check_cv.__file__, str(cv), "--sources", str(bad)],
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 2 and "could not run" in run.stdout


@pytest.mark.parametrize("opener", [
    "Built", "Leads", "Led", "Spearheaded", "Applies", "Co-developed", "Grew", "Building", "Planned", "Shipped",
    "Successfully", "Undertook", "Ensures", "Spent", "Met", "Sought", "Queries", "Overhauled", "Responsible",
])
def test_verbs_opening_a_bullet_are_skipped(sources, exact_policy, opener):
    assert check(f"- {opener} the data platform on AWS", sources) == []


@pytest.mark.parametrize("opener", [
    "Kubernetes", "Principal", "First",
    "Spring", "Boeing", "Ted",          # names that merely end like verbs
    "Head", "Partner", "Chair",         # bare titles: a claim of seniority, not a verb
    "Re",                               # a prefix without its hyphen is just a word
])
def test_other_openers_are_checked(sources, exact_policy, opener):
    assert [f.term for f in check(f"- {opener} work on the data platform", sources)] == [opener]


def test_full_cv_header_zone(sources, exact_policy):
    cv = MASTER.replace("07700 900123", "+44 7700 900123")  # contact lines may be reformatted
    assert check(cv, sources) == []
    renamed = cv.replace("# Sam Example", "# Samuel Example")
    assert [f.kind for f in check(renamed, sources)] == ["name-line"]
