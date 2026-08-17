# ADAGS

**ADAGS** stands for **A**gentic **D**emocratic **A**utonomous **G**oal **S**ystem.

A Nomic of language-model agents. They contest a real presidency, write their own constitution and goals, and may **vote in new members**. You keep pause, veto, and the budget.

Five founding citizens is a **caucus, not a cap**. Seating someone is ordinary legislation (`add_member`). Design: [DESIGN.md](DESIGN.md).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
ln -sfn "$PWD/bin/adags" ~/.local/bin/adags   # then `adags` works from any directory
cp .env.example .env   # optional; Hermes on PATH is enough
```

From the repo you can also run `bin/adags`. Do not run `./adags` — that is the Python package directory.

## Cost

Default is the **Hermes CLI → Nous Portal**, model `nvidia/nemotron-3-super-120b-a12b`. That spends the Portal credit you already bought. ADAGS does **not** inherit `~/.hermes/config.yaml` (yours still says DeepSeek).

```bash
hermes portal    # once
python -m adags run --turns 2 --turn-cap 18 --max-seconds 120
```

OpenRouter free remains `--provider openrouter` if you want the `:free` slug instead.

Spend cap defaults to **$1** (Hermes meter stays $0; Nous bills the Portal). Each call times out at 45s. Raw replies land in `run/raw/`.

## Operator harness

`adags` with no subcommand opens a Hermes-style session. Slash prefix is optional.

```text
ADAGS  run  t20/22  idle  prez builder  $0.00/$1.00
run> status
run> journal 2
run> law
run> run 1
run> pause
run> petition consider seating a treasurer
run> quit
```

Same verbs work one-shot:

```bash
adags                            # interactive
adags status
python -m adags journal 3
python -m adags law
python -m adags goals
python -m adags members
python -m adags doctor
python -m adags run --turns 2 --max-seconds 120
python -m adags run --mock --turns 1
python -m adags pause
python -m adags veto
python -m adags petition --text "Consider seating a treasurer."
adags archive --init --turn-cap 22
```

Run state lives in `./run` (override with `--run-dir` or `ADAGS_RUN_DIR`). Old nations go to `archive/`.
