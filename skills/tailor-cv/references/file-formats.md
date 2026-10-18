# File formats

## The Markdown CV layout

`render_cv.py` and `check_cv.py` both read this layout. `templates/master-cv.md` is a complete example.

```
# Full Name

City, Country • phone • email • website

*One- to three-line summary, in italics.*

## SECTION NAME

**Label:** comma-separated items          (skills lines, in any section whose name contains "SKILL")

**Project name** | stack - [link text](https://link)
- Bullet

**Employer** - *Mon YYYY – Mon YYYY*
*Role title – City*
- Bullet
```

- Everything between `# Name` and the first `## ` heading is the header: contact lines (parts separated by `•`),
  then the summary as one italic Markdown line (it wraps on the page; do not break it across lines).
- Italics need the asterisk to touch a word on the inside only (`*like this*`), so grades such as `A*` stay
  literal.
- A dated header (`**Employer** - *dates*`) followed by a whole-italic line is a job or education entry; the
  italic line is the role or degree. `check_cv.py` requires both to match the sources exactly.
- A bold line followed by `|` is a project; its bold name must exist in the sources.
- Bullets start with `- `. Bold, italics and links work inside them.

## career-facts.md

Three sections, matched by `check_cv.py` through the heading text:

1. **Usable as written.** Facts the master CV does not hold (older bullets, side projects). A source.
2. **Unconfirmed: do not use until confirmed.** The heading must contain "unconfirmed": `check_cv.py` skips the
   whole section, so anything taken from it is flagged. The user moves an item to section 1 once confirmed.
3. **Personal details.** Right to work, sponsorship, notice period, languages, nationality and the like, used only
   where a region profile expects them. A blank means leave it out.

## notes.md (one per application)

- the region profile and role family used, and the section order
- the keywords used, and where
- what changed from the master, and why
- the checker's result, and every `--allow` term with the source line that supports it
- the gaps, and how to handle each honestly in a cover letter or interview
- the screening questions, if any, with the honest answer to each from the sources
- 5-8 likely interview questions drawn from the posting, each with the entry that answers it
- a `## History` list starting `YYYY-MM-DD: tailored`
