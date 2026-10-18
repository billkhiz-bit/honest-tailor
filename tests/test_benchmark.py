from pathlib import Path

import run_benchmark

README = Path(run_benchmark.__file__).with_name("README.md").read_text(encoding="utf-8")


def test_cases_are_well_formed():
    cases = run_benchmark.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cases:
        assert c["expect"] in {"pass", "flag"}, c["id"]
        assert c["cv"].strip() and c["note"].strip(), c["id"]


def test_every_category_is_documented():
    for category in {c["category"] for c in run_benchmark.load_cases()}:
        assert f"`{category}`" in README, f"benchmark/README.md does not describe {category}"
