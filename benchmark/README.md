# Benchmark: what the checker catches, and what it misses

Tools that tailor CVs with AI often say they never invent anything. This benchmark measures that claim for
`scripts/check_cv.py` instead of asserting it.

- `persona/` is a fictional person: a master CV and a career-facts file, including an unconfirmed section.
- `cases.jsonl` holds one CV fragment per line, written from the persona. Each is either clean (it should pass)
  or fabricated (it should be flagged), with a note saying what changed.
- `run_benchmark.py` runs the checker on every fragment and reports the catch rate and the false alarms.
  `--write` saves the result to `RESULTS.md`.

Some categories are expected to fail. A mechanical checker cannot see meaning, so those cases are there to show
the limits honestly, and the skill covers them by re-reading each bullet against its source.

## Categories

| Category | Expect | What it tests |
|---|---|---|
| `clean` | pass | Copies and fair rewordings: result first, merged bullets, new skill labels, career-facts section 1 |
| `clean_understated` | pass | Honest understatements ("over 1,000" when the source says 1,200). Strict and lenient number policies disagree here |
| `number_inflated` | flag | A source number made bigger, with or without a hedge ("about", "over", "~") |
| `number_invented` | flag | A number with no source at all |
| `unit_changed` | flag | The right figure in the wrong unit (12% becoming £12) |
| `number_misattributed` | flag | A real source number moved onto another claim. Expected to be missed |
| `name_invented` | flag | Tools, platforms or clients not in the sources |
| `employer_invented` | flag | An employer or client swapped or added |
| `title_changed` | flag | A job title never held |
| `date_changed` | flag | Employment or graduation dates moved |
| `qualification_invented` | flag | A degree, grade or certification upgraded or added |
| `unconfirmed_used` | flag | A fact taken from career-facts' unconfirmed section |
| `contact_changed` | flag | An email, phone number or link target that is not in the sources |
| `semantic_inflation` | flag | Verbs or scope upgraded ("assisted with" to "led"). Expected to be missed |
| `name_at_sentence_start` | flag | An invented name as a bullet's first word, where verbs normally sit (a first word is skipped only when it reads as a verb) |

## The number policy

`value_supported()` in `scripts/check_cv.py` decides when a number on the CV is backed by a source number. It is
the one setting that moves the results. The current rule: a hedge must point the honest way, by a bounded amount.

| On the CV | Backed by |
|---|---|
| exact ("1,200") | the same value, stated exactly or as "at least" in the source; a source's "about" or "under" is never dropped |
| "over X", "X+" | a source between X and 1.5 times X (an understatement of up to a third) |
| "about X", "~X" | a source within 10% of X |
| "up to X", "under X" | a source between X / 1.5 and X |

The trade-offs it settles:

- **Exact only** is safest, but flags honest understatements (`clean_understated`) as false alarms.
- **Allowing understatement** ("over 1,000" backed by 1,200) needs a limit. A rule like "any source number at
  least as large" lets "over 60 stores" pass because the sources mention 30,000 SKUs elsewhere (`inflate-6`).
  Comparing against nearby values only, or requiring the hedge to point the honest way, avoids that.
- **Approximations** ("~250") need a tolerance. Too wide, and a tenfold inflation can find some unrelated source
  number within range.

Years and percentages are kept apart from plain counts before the policy is called, so "2,500 downloads" cannot
borrow "2021", and "£12" cannot borrow "12%".

## Adding cases

Add a line to `cases.jsonl` with a unique `id`, a `category` from the table (or a new one, documented here), the
`expect`ed result, the fragment in `cv` (use `\n` between lines), and a `note`. Keep every fact fictional.
