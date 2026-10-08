# Rift Unbound

A local, playable two-player match of [Riftbound](https://playriftbound.com/en-us/), the League of Legends trading card game. You play units and spells, move units onto shared locations, and score points for holding them. First to 8 points wins.

This repo is that match: a Godot window with the board on top and a command line underneath, a rules engine that accepts or rejects every move, and an optional computer opponent. The card pool is a working subset — starter lists plus a few champion decks — enough to play, test the rules, and add cards.

## What you can do

- **Play a match.** Two people on one computer, or you against the computer.
- **Watch the computer play itself.** Both seats move on a short delay so you can follow the game.
- **Review a finished computer game.** Step through the moves it chose and put the board back to an earlier moment.
- **Change decks and cards.** Card text and deck lists are JSON. The engine reads them when a match starts.
- **Check the rules.** A headless test suite sets up a situation, plays commands, and checks the result.
- **Plug in a language model.** Optional. The computer still plays if you skip this; it uses a simple built-in player.

## Play a game

You need [Godot 4.6](https://godotengine.org/download).

1. Open this folder in Godot (the project file is `project.godot`).
2. Press Play (F5). The main menu is titled **Rift Unbound**.
3. Pick a deck for each seat. Decks already in the repo include Master Yi (Shanghai Open), Master Yi (Calm/Body), Kai'Sa (Fury/Mind), and two starter lists.
4. Start a mode:

| Mode | What happens |
|---|---|
| **Player vs Player** | Both people type into the same command line. The prompt shows whose turn it is. |
| **Player vs AI** | You are player 1. Player 2 is the computer. |
| **AI vs AI** | Both seats are the computer. Moves are spaced a few seconds apart. |
| **Post-Game Analysis** | Browse decisions saved by the language-model service and restore the board. |

Two menu options only matter when a seat is the computer:

- **AI Scoring Profile** chooses how that seat judges the board. Leave the default unless you are comparing strategies. Files live in `Data/AI/`.
- **Enable Human AI Evaluation** asks you to rate the computer's play after a Player vs AI match.

### Commands

The log prints the card names you can type. Names are lowercase with hyphens, such as `void-seeker`. A second copy of the same card is `void-seeker-2`. Type `help` to see which commands are legal right now.

| Command | What it does |
|---|---|
| `hand` | Print your hand |
| `board` | Print the table |
| `score` | Print the score |
| `play <card>` | Play a card from your hand |
| `play <card> to battlefield-a` | Play a unit onto a location (`battlefield-a`, `battlefield-b`, or `base`) |
| `move <unit> to battlefield-a` | Move a unit you control |
| `pass` | Decline to act, or leave the main part of your turn |
| `end turn` | End your turn |
| `choose <card>` | Answer a prompt. Also `choose yes`, `choose no`, or `choose none` |

When the game needs a decision it prints a line starting with `[PROMPT]`. A rejected move starts with `[ERROR]` and says why.

The full command list, including resources, reactions, and combat damage, is in [Docs/Game Rules/riftbound-implementation-rules.md](Docs/Game%20Rules/riftbound-implementation-rules.md) (section 19). A short rules summary is in the same file.

## Optional: a language-model opponent

Player vs AI works with no extra setup. The computer uses a simple built-in player that only looks at the current board.

To have a language model choose the moves, run a small local service first. The game sends it the board and plays the command it returns, through the same rules checks as a typed command.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...
uvicorn ai_agent.main:app --port 8765 --reload
```

Leave that process running, then press Play in Godot and choose **Player vs AI** or **AI vs AI**. The game looks for the service at `http://localhost:8765`. If nothing is listening there, it uses the built-in player instead.

**Post-Game Analysis** reads the log that service writes (`ai_agent/agent_memory.db`). Play at least one match with the service running before opening that screen.

Model choice, other providers, logging, and how the computer looks ahead at sequences of moves are documented in [ai_agent/README.md](ai_agent/README.md). Unattended matches that compare two computer strategies are documented in [Data/AI/Baseline/README.md](Data/AI/Baseline/README.md).

## Run the tests

Rules tests run headless in Godot. The script looks for Godot at `/Applications/Godot.app` or as `godot` on your `PATH`. Point `GODOT` at the binary if yours is somewhere else.

```bash
./Scripts/run_tcg_tests.sh
# GODOT=/path/to/Godot ./Scripts/run_tcg_tests.sh
```

Tests for the language-model service live in `ai_agent/tests`. Most of them stub the model, so they do not need an API key. `pytest` is not in `requirements.txt`; install it once alongside those dependencies.

```bash
pip install -r requirements.txt pytest
pytest ai_agent/tests
```

## Change a card or a deck

| Path | What it is |
|---|---|
| `Data/Cards/` | Card definitions, split by kind (units, spells, gear, locations, and so on) |
| `Data/Decks/` | Which cards each player brings, including their champion |

Add a card by editing the matching JSON file, then list it in a deck. If the card does something the engine has never implemented, that behavior also needs a handler in `Scripts/Game/`. The JSON shape and the list of known behaviors are in [Docs/Game Rules/riftbound-card-data-schema.md](Docs/Game%20Rules/riftbound-card-data-schema.md). Known gaps in the simulation are tracked in [Docs/Game Rules/simulation-gaps-implementation-plan.md](Docs/Game%20Rules/simulation-gaps-implementation-plan.md).

## Where the code lives

| Path | What it is |
|---|---|
| `Scenes/` | Menu, match, and post-game analysis screens |
| `Scripts/UI/` | Board and command line |
| `Scripts/Game/` | Rules engine: turns, costs, combat, scoring, card effects |
| `Scripts/AI/` | How the match talks to the computer opponent |
| `Scripts/Tests/` | Scripted rules checks |
| `ai_agent/` | Optional language-model service |
| `Docs/Game Rules/` | Rules and card-data notes the engine is written against |

## If a match plays wrong

File a bug with the command that failed and a console log:

```bash
python3 Scripts/bugs/report_bug.py new
```

Details are in [Docs/bugs/README.md](Docs/bugs/README.md).

## License

[GNU GPL v3](LICENSE).
