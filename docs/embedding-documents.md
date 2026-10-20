# Per-game embedding documents (TM11-38, REQ011)

Each game is embedded from one short text document. Retrieval can only match
what that text says, so the template is written down here and versioned.

- Code: `api/services/game_document.py` (`build_game_document`, `TEMPLATE_VERSION`)
- Used by: `api/services/embedding_pipeline.py` (`scripts/embed_catalogue.py`)
  and the legacy `scripts/embed_games.py`
- Stored: `public.game_embeddings.template_version` on every row, and
  `template_version` in each run's `embedding_report.json`

## v1 (current)

```text
Title: <title>
Genres: <genre>, <genre>, ...
Tags: <tag>, <tag>, ...
Description: <description>
```

Rules:

| Part | Source | Rule |
|------|--------|------|
| Title | `games.title` | Whitespace tidied. |
| Genres | `games.genres` | Blanks and case-insensitive duplicates dropped, first spelling kept. |
| Tags | `games.tags` | As genres, and a tag that repeats a genre is dropped. At most 15 (`MAX_TAGS`), in stored order. |
| Description | `games.description` | HTML tags removed, entities decoded, whitespace tidied. |

A part with nothing in it is left out, line and label both. Lines are joined
with `\n`.

Why this shape:

- **Short, high-signal parts first.** all-MiniLM-L6-v2 reads only the first
  256 word pieces. Title, genres and tags say the most about how a game feels
  and are short, so they come first. When a document is too long, the end of
  the description is what gets cut, never the tags.
- **Labels.** `Genres:` and `Tags:` tell the model what a list of words is,
  so "Horror" in a tag list reads as a mood.
- **Tags capped.** Store tags are ordered by votes; past about 15 they turn
  into noise like "Great Soundtrack" that every game has.

Example (Half-Life 2, from `scripts/fixtures/games.json`):

```text
Title: Half-Life 2
Genres: Shooter, Action
Tags: story-rich, sci-fi, singleplayer, classic
Description: A physics-driven sci-fi shooter where you fight an alien occupation with the gravity gun and a crowbar. Tense, story-rich, and still a masterclass in pacing.
```

## v0 (TM11-39, retired)

`title description genres`, joined with spaces. No tags, no labels.
Rows embedded before TM11-38 were backfilled as `v0` by
`20261020120000_game_embeddings_template_version.sql`.

## Changing the template

1. Change `build_game_document` in `api/services/game_document.py`.
2. Bump `TEMPLATE_VERSION` (`v1` to `v2`) and update the module docstring.
3. Add a `## v2` section above and move the old one down as retired.
   `api/tests/test_game_document.py` fails until the current version is here.
4. Run `python scripts/embed_catalogue.py`. Every row from an older version
   counts as changed and is re-embedded; nothing else is needed. The run
   report records the version it embedded with.

To see which template a vector came from:

```sql
select template_version, count(*) from public.game_embeddings
where model = 'sentence-transformers/all-MiniLM-L6-v2'
group by template_version;
```

## Review

`python scripts/sample_game_documents.py` writes 20 sample documents, spread
across the catalogue, to `artifacts/sprint6/tm11-38/sample-documents.md` with a
checklist and a sign-off line. Add `--from-db` to sample `public.games` instead
of the fixture. A second team member reviews them before the template ships.
