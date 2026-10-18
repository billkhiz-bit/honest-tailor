# The Honest Tailor (honest-tailor): notes for Claude

A Claude Code plugin: skills `tailor-cv` and `track-applications`, scripts `render_cv.py` (Markdown CV to
HTML/PDF/Word) and `check_cv.py` (traces CV claims to sources), and a benchmark of fictional fragments.

## The one rule

**No personal data in this repo, ever.** It is public. All examples and test data use the fictional persona in
`benchmark/persona/` (Ofcom drama-range phone numbers, example.com addresses, Contoso/Fabrikam employers). The
maintainer's real CV lives in a separate workspace outside this folder; never copy from it, quote it in tests, or
name its employers, projects or applications here. `dev/check_private_data.py` enforces this (generic patterns plus
the gitignored `.private-terms`), through the pre-commit hook (`git config core.hooksPath dev/hooks`) and
`tests/test_private_data.py`.

## Commands

- Tests: `python -m pytest`
- Benchmark: `python benchmark/run_benchmark.py` (`--write` updates `benchmark/RESULTS.md`)
- Leak check: `python dev/check_private_data.py` (`--staged` also checks the commit author email)
- Try the plugin: `claude --plugin-dir <path to this repo>`, started in a CV workspace

## Conventions

- Python 3.10+, stdlib only in `check_cv.py`; `render_cv.py` uses pypdf and python-docx optionally.
- British English everywhere except the US region profile's own rules.
- Skill files use `${CLAUDE_PLUGIN_ROOT}` for script paths.
- A new benchmark category must be documented in `benchmark/README.md` (a test enforces it).
- `.gitignore` denies everything at the top level by default. A new top-level file or folder must be added to its
  allowlist on purpose; that is what keeps a CV workspace or export from being committed by accident.
- `docs/readout-example.png` is a screenshot of `docs/readout-example.html` (headless Edge, 956x745). Edit the HTML,
  never the image, so the leak check scans the text behind it.
