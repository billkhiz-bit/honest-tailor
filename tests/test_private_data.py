"""The repo must never contain personal data. These run the same scan the pre-commit hook runs."""
import pytest

import check_private_data as guard


def test_repo_contains_no_personal_data():
    terms = guard.load_terms()
    findings = []
    for path in guard.candidate_files(staged=False):
        findings += [f"{path} (file name): {p}" for p in guard.scan_text(path, terms)]
        text = guard.read_candidate(path, staged=False)
        if text:
            findings += [f"{path}: {p}" for p in guard.scan_text(text, terms)]
    assert findings == []


def test_fictional_contact_details_pass():
    assert guard.scan_text("07700 900123 • +44 7700 900456 • sam@example.com", []) == []


def test_real_looking_contact_details_fail():
    # Built at run time so this file never contains a real-looking number or address itself
    mobile = "07" + "123 456789"
    email = "someone" + "@" + "gmail.com"
    postcode = "SW1A" + " 1AA"
    problems = guard.scan_text(f"{mobile} {email} {postcode}", [])
    assert len(problems) == 3


def test_mobile_numbers_in_other_formats_fail():
    for written in ("+44 (0)7" + "123 456789", "07" + "123-456-789"):
        assert guard.scan_text(written, []), written
    assert guard.scan_text("+44 (0)7700 900123", []) == []  # still the drama range


def test_terms_file_is_never_committed():
    assert not guard.terms_file_committed(staged=False)


def test_commit_message_mode(tmp_path):
    import subprocess
    import sys

    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("Contact " + "someone" + "@" + "gmail.com about the fix\n", encoding="utf-8")
    run = subprocess.run([sys.executable, str(guard.ROOT / "dev" / "check_private_data.py"), "--message",
                          str(message)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 1 and "commit message" in run.stdout


def test_a_term_wrapped_across_lines_is_found():
    assert guard.scan_text("worked at Acme\nWidgets for years", ["Acme Widgets"])


@pytest.mark.parametrize("text", ["examples/jo_bloggs_cv.md", "jo-bloggs", "JoBloggsCV", "Jo\nBloggs"])
def test_terms_are_found_in_file_names_slugs_and_camel_case(text):
    assert guard.scan_text(text, ["Jo Bloggs"]), text


def test_documents_are_refused_outright():
    assert guard.blocked_document("examples/cv.pdf") and guard.blocked_document("Notes.DOCX")
    assert not guard.blocked_document("docs/readout-example.png")


@pytest.mark.parametrize("number", ["0044 7" + "123 456789", "+44-7" + "123-456-789", "071" + " 2345 6789"])
def test_more_mobile_formats_fail(number):
    assert guard.scan_text(number, []), number


def test_drama_numbers_pass_in_every_format():
    for number in ("07700 900123", "+44 7700 900123", "+44 (0)7700 900123", "0044 7700 900123", "077 0090 0123"):
        assert guard.scan_text(number, []) == [], number


def test_unspaced_postcode_fails():
    assert guard.scan_text("SW1A" + "1AA", [])


def test_hooks_exist_for_files_and_messages():
    for hook in ("pre-commit", "commit-msg"):
        assert (guard.ROOT / "dev" / "hooks" / hook).is_file()


def test_private_terms_match_whole_words_case_insensitively():
    assert guard.scan_text("worked at ACME Widgets", ["Acme Widgets"])
    assert guard.scan_text("acmewidgets.example", ["Acme Widgets"])        # joined up, still the name
    assert not guard.scan_text("acmewidgetsplus", ["Acme Widgets"])        # part of a longer word
    assert not guard.scan_text("Zorbaville", ["Zorba"])
