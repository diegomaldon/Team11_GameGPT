# TM11-70 explanation quality: before and after the prompt change

Run 2026-11-17T15:47:06+00:00 with `gemini-3-flash-preview` on the 167-game seed catalogue, against the 5 TM11-63 benchmark prompts. Written by `scripts/eval_explanations.py`; the review is `docs/explanation-quality.md`.

Both prompts ranked the same 20 candidates per prompt (local `sentence-transformers/all-MiniLM-L6-v2`, query parser, hybrid merge) and returned 3 picks each. **Passes** = uses a word from the request, restates fewer than two of the game's genre/tag labels, and has no stock phrase (`api/services/explanation_quality.py`).

| | passes | uses the request | tag lists | stock phrases | mean words |
|---|---|---|---|---|---|
| Before, every pick | 6/12 | 9/12 | 3 | 1 | 31.9 |
| After, every pick | 9/9 | 9/9 | 0 | 0 | 30.6 |
| Before, top pick | 1/4 | 3/4 | 1 | 1 | 33.0 |
| After, top pick | 3/3 | 3/3 | 0 | 0 | 31.0 |

## Top pick per prompt

| Id | Prompt | Before | After |
|---|---|---|---|
| genre-04 | roguelike deckbuilder where each run I build a new deck | **Slay the Spire**: This is the definitive roguelike deckbuilder where you start with a basic set of cards and draft new ones after every encounter to create powerful synergies. Every run requires adapting your strategy to the specific cards and relics you find along the way. *(labels: Deckbuilder, Roguelike, strategy, roguelike)* | **Slay the Spire**: Every card choice you make ripples through your run as you climb the spire. You will build a new deck of abilities each time to overcome this deceptively deep and challenging experience. *(pass)* |
| mood-01 | something calm and low stress to unwind with after a long day | **A Short Hike**: Climbing a mountain at your own pace and chatting with birds along the way offers a delightful, pressure-free exploration experience. It is specifically designed to be a quick and charming relaxer for any player. *(no request words)* | **Unpacking**: This meditative experience lets you unpack boxes into new homes across someone's life. It provides a soothing way to unwind by turning the simple act of unpacking into a moving story. *(pass)* |
| mood-05 | brutally hard but rewarding when I finally beat it | **Super Meat Boy**: This game is the definition of brutally hard, featuring instant death and pixel-perfect platforming that makes every successful level feel like a massive victory. *(pass)* | *failed* |
| comparison-03 | I finished Hades, what other fast action roguelikes should I try | *failed* | *failed* |
| platform-05 | survive on a remote island and build a base with friends, on Steam | **Raft**: This game perfectly matches your request as you and your friends survive in the middle of the ocean, visiting remote islands to scavenge resources for your expanding floating base. *(stock: "perfectly match")* | **Raft**: You and your friends start on a tiny raft, scavenging debris to build a massive floating base and eventually your own island empire in the middle of the ocean. *(pass)* |

Every pick, with its checks, is in the `.json` next to this file.
