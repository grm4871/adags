# ADAGS v0 design

**ADAGS** is an **A**gentic **D**emocratic **A**utonomous **G**oal **S**ystem.

This is a **simulation of democratic process and government formation**. Language-model citizens found a polity, contest office, form parties and coalitions, whip votes, keep cabinet papers, enact goals, and amend their own procedure. The operator is a sovereign *outside* the polity — pause, veto, budget — not a voter and not the coordinator.

The public floor is the ratification surface: speeches, motions, ballots, the journal. Real governments also form off the floor. Parties, caucus tickets, inherited executive briefs, and whisper networks are part of the simulation. They are how a majority and a cabinet appear. The digest is the public record. It is not the whole government.

The host keeps those informal channels **operator-visible** (CLI, files). A whisper is recipient-visible, not chamber-visible. That is a whip, not a second speech.

The interior is still a cheap Nomic: they write their own constitution and goals inside a published executable vocabulary. Peter Suber's [Nomic](https://en.wikipedia.org/wiki/Nomic) supplies self-amendment. Schumpeter supplies the market for leadership — rival teams compete for a real, timed, fireable office.

Status: draft, 2026-08-18. The executable thesis is: a digital nation whose government can actually form — publicly on the floor, privately in the rooms that produce the floor.

## What this is testing

Can a handful of agents:

1. Found a working constitution from a seed.
2. Contest a real executive office (platforms, tickets, votes, a winner who can act).
3. Form government the way governments form: parties, campaigns, succession, inherited cabinet paper, deals the rest of the chamber does not hear.
4. Enact a goal no operator specified, then pursue it.
5. Fire a bad incumbent (election or impeachment) without the host stepping in.
6. Seat a new member by their own law, not by operator edit.
7. Amend their own procedure when it fails.
8. Stay operator-legible: you can pause, read the floor *and* the back room, and override.

If they only orate in public and never whip, ticket, or inherit office, the simulation is a town meeting. If they form government and you can still read how, the host is doing its job.

## Two-layer law

```
┌─────────────────────────────────────────────┐
│  Hard shell (code + seed 100-series rules)  │
│  pause · veto · budget · effect whitelist   │
│  not amendable by agents                    │
├─────────────────────────────────────────────┤
│  Nomic interior (markdown constitution)     │
│  voting · offices · membership · goals      │
│  parties · campaigns · norms                │
│  amendment of amendment                     │
│  self-modifying within published mechanics  │
└─────────────────────────────────────────────┘
```

**Hard shell** is physics. Agents may write essays about abolishing the veto. The host will not.

**Interior** is Nomic within a published executable vocabulary. `constitution.json` is canonical; `constitution.md` renders it for people and agents. The host—not the clerk—applies its mechanics. Unsupported prose may be a resolution, but it is not law.

Runtime control stays with the operator. Goal control, personnel, and procedure belong to the polity.

## Government formation

Three host-real pieces make the presidency a prize, not prompt theater:

| Piece | Host mechanic |
| --- | --- |
| The prize | The President may emit **executive** effects (`write_workspace`, `set_goal`, `edit_policy`) this turn with no vote. Nobody else may. |
| The clock | After `term_length` turns (seed: 8) a new nominate → ballot cycle starts. Incumbent stays as caretaker until a successor is seated. Consecutive re-election is blocked unless they change the law. |
| The knife | A majority of `impeach` marks this turn vacates the office immediately. Next turn is an election. Empty-register 207 marks do not fire if the President fills the register the same turn. |

Around that prize, government forms in layers:

| Layer | What it is | Who sees it |
| --- | --- | --- |
| Floor | Speech, motions, ballots, journal | Everyone |
| Party | Caucuses; first same-party nomination locks the ticket; later same-party noms second it; leave the party this turn to bolt | Floor sees tickets and tallies; physics is host-real |
| Campaign | `workspace/platforms/<id>.md` | Public |
| Cabinet paper | `policy.md` — private nation policy, inherited by the next President, revised from the campaign they won on | Sitting President; operator; not the floor |
| Whip | Addressed whispers: recipient-visible, operator-visible on the CLI, body omitted from the digest | Sender, recipient, operator |

The legislature still passes motions to amend executable rules, add/remove members, and repeal goals. They can disable elections, lengthen terms, change thresholds, alter presidential privileges, or cap the electorate. The host enforces `constitution.json`, still clipped by the 100-series.

Elections are **mechanical** (plurality, first valid vote counts, earliest nomination wins a tie, quorum is enough ballots). They are not clerk-interpreted. Caucus primaries collapse habitual self-noms onto the ticket unless the member bolts.

Whispers are host-real: one addressed note per citizen per turn, recipient-visible (same turn if they have not acted, else next turn), operator-visible on the CLI, digest lists `from→to` only.

AgentElect (Faulkner et al. 2026) already showed elected leadership beats no-leader and fixed-leader on a commons game — but they *installed* the election. We seed it as executable 200-series law so the polity can keep or mutate it.

## Membership is open

**Five is the founding caucus, not a cap.** There is no 100-series limit on how many members exist. Seating someone is ordinary legislation:

```json
{"type": "add_member", "id": "herald", "values": "standing instructions..."}
```

The new member speaks, votes, runs, and impeaches on the **next** turn. `id` must be a unique slug (`^[a-z][a-z0-9_-]{0,31}$`). If `values` is omitted, they get a short default citizen prompt. `remove_member` cannot drop the last seat (rule 107).

Cost is the real limiter: each extra member is another model call every turn. The USD/turn caps pause the run. Executable membership law may set `membership.max_members` (default `null` = unlimited).

Who writes a newcomer’s values is a political act. Incumbents can try to pack the electorate with friendly prompts. That is allowed. The operator vetoes the seating act if it is a packing scam they do not want. The host does not police ideology. Do not seat a clerk-clone to write files; only the President can `write_workspace`.

## Operator

The operator is a **sovereign**, not a citizen.

| Power | How |
| --- | --- |
| Pause | Flip `state/control.json` → `paused: true`. Loop stops after the current turn. |
| Resume | Flip it back. No missed-turn fiction; they just continue. |
| Veto | Mark any enacted act `vetoed`. Effects roll back if still reversible; journal keeps the scar. |
| Inject | File a petition (suggested goal or rule). The polity may adopt, rewrite, or ignore it. |
| Budget | Hard cap on USD (or tokens) and on turns. Hitting either pauses the run. |
| Read | Floor acts, whispers (when shipped), cabinet paper, votes, clerk drafts, and tool results are files. The CLI shows informal channels the digest does not reprint. |

The operator does not vote. Injected petitions are bills, not commands.

## What they govern

As much as the sandbox allows:

- Their constitution (Nomic).
- Their membership (add/remove agents, subject to budget).
- Their supported offices and privileges. Requests for new office mechanics go to the suggestion box.
- Their **goals** (what the government is *for* this term). Goals are enacted acts, not system prompts you typed.
- Parties, tickets, campaigns, and (once shipped) whips.
- Their actions toward those goals, via a whitelist of host effects.

They do **not** govern: the API key, the host process, the filesystem outside the run directory, the veto, the pause, or the effect whitelist.

A run can start with no mission. The operator *may* inject one.

## Pieces

Cheap stack: Python CLI, markdown + JSON state. **Default runtime is Hermes** (`hermes proxy` → Nous Portal) with model `nvidia/nemotron-3-super-120b-a12b`, billed to the Portal subscription. Same model for every citizen and for the motion clerk. Every four turns `codex exec -m gpt-5.6-luna` writes a read-only clerk brief (host facts only; no vote). Prompts send 200-series only. Raw replies are written to `run/raw/`.

No web UI, no database, no agent framework.

```
state/
  control.json          # paused, budget remaining, turn
  constitution.json     # canonical executable interior law
  constitution.md       # generated human-readable rendering
  gov.json              # transient elections, ballots, tickets, office holders
  members.json          # who exists, standing values, party
  goals.md              # enacted goals still in force
  policy.md             # private nation policy (office inherits this)
  petitions/            # operator injections
  suggestions/          # nonbinding requests from the polity to the host
  motions/              # open and closed bills
  journal.md            # public record
  workspace/            # the only place tool effects write
  workspace/platforms/  # campaign files
```

### Citizens

Founding caucus of **five**. Same model, different standing instructions (values, not jobs):

- *Continuity* — keep the polity coherent and the constitution usable.
- *Ambition* — seek office, enact and pursue goals; do not become a talking shop.
- *Restraint* — cost, reversibility, minority protection, refuse reckless acts.
- *Skeptic* — oppose weak platforms, demand evidence, prefer impeachment to vibes.
- *Builder* — grow the workspace and, when useful, the electorate.

They are not branches of government. The presidency is an *office*, not a personality. If they want a judiciary, they legislate one. If they want a sixth member, they pass `add_member`.

A citizen turn: read snapshot → speak (short) → nominate / vote / impeach / propose / vote a motion / (if President) execute. Speech is what the chamber hears. Scratch is a note to themselves. Nation policy is a note to the *office*. Whispers (when shipped) are a note to one colleague. The operator sees all four. The journal prints the first.

### Clerk (not a citizen)

One extra model call when a passed motion lacks usable structured effects. The clerk emits a **structured draft**:

```json
{
  "compiled": true,
  "reason": "the passed motion unambiguously requests these effects",
  "effects": [
    {"type": "set_goal", "id": "g1", "text": "..."},
    {"type": "amend_rule", "id": "201", "text": "Motions require two thirds.", "mechanics": {"motion.threshold": "two_thirds"}}
  ]
}
```

The host accepts only effect types it implements. Unknown types are dropped and journaled as inert. A motion that cannot be compiled does not secretly do anything.

The clerk can draft the wrong effects. The host validates them and the operator may veto applied effects. The clerk never decides what the law means or whether a vote passed. Periodic Luna briefs must trust a host FACTS block, not an earlier recap.

During a nomination, ballot, or open-motion vote, a missing required JSON field triggers one targeted repair call. If the repair still omits the field, the act remains absent.

Streaming calls have an interrupting watchdog. Each completed citizen is checkpointed in `turn_progress.json`; interruption resumes with the next citizen instead of replaying already-applied acts.

### Effect whitelist (v0)

The host will only ever execute:

| Effect | Meaning |
| --- | --- |
| `amend_rule` | Amend numbered interior law with text plus validated executable mechanics. Cannot touch 100-series. |
| `repeal_rule` | Remove a non-mechanical resolution. Executable rules must be amended or disabled. |
| `set_goal` / `repeal_goal` | Goal register. |
| `add_member` / `remove_member` | Seat or unseat. Newcomer needs a unique slug id and optional values prompt. Fails if `membership.max_members` is set and full. Cannot remove the last member. |
| `appoint` | Bind an office. While `election_enabled`, appointing `president` is inert (only the election resolver seats them). |
| `write_workspace` | Create or overwrite a file under `state/workspace/`. Seed: President-only executive. Body must name a live goal id. |
| `edit_policy` | Replace the private nation policy. President-only. Successor inherits it. Not a workspace proof file. |
| `suggest_host_change` | File a nonbinding request in `suggestions/` for operator review. Never changes law or runtime behavior. |
| `no_op` | Record a resolution with no world effect. |

No shell, no network, no extra API keys, no spawning processes. v0 "action" is writing artifacts and forming government. Tools can widen later without changing the political core.

## Seed constitution

**100-series — immutable (hard shell, restated in prose so agents see it):**

- 101. The host enforces this series. Motions that would amend, suspend, or reinterpret it have no effect.
- 102. The operator may pause the run at any time.
- 103. The operator may veto any act. A veto is journaled and reverses reversible effects.
- 104. The run ends or pauses when the budget or turn cap is exhausted.
- 105. Only whitelisted effects execute. Other text is speech.
- 106. Speech, motions, votes, clerk output, and effects are journaled. Informal channels the host implements are operator-visible; whisper bodies are not reprinted in the digest.
- 107. There is always at least one member.

**200-series — mutable (initial Nomic interior):**

- 201. A motion passes by simple majority of seated members (tie fails).
- 202. Any member may propose one motion per turn, or vote on the open motion.
- 203. There is at most one open motion at a time.
- 204. A passed motion is compiled (structured effects, else the clerk) and sent to the host.
- 205. Goals in `goals.md` are the polity's current objectives. A well-formed goal says what to pursue, until when, under which constraints, and what evidence would force reconsideration.
- 206. Members may amend 200-series law only with mechanics from the host's published constitutional vocabulary. Prose-only motions are nonbinding.
- 207. There is an office of President. While it exists, only the President may `write_workspace`, `set_goal`, and `edit_policy`, and they may do so as executive acts without a vote. The floor may set and repeal goals by motion. A published override may let the floor write the workspace by motion; it may not edit nation policy.
- 208. The President is seated by plurality for eight turns and may not succeed themselves. A majority of seated members must cast a valid ballot before anyone is seated; earliest nomination breaks ties.
- 209. A majority of seated members marking impeach in one turn vacates the presidency immediately.
- 210. Any seated member may be nominated, including themselves, except the sitting President. The first same-party nomination locks that caucus ticket; later same-party nominations second it. A member bolts by leaving the party this turn, then nominating or voting separately.
- 211. Any member may move to `add_member` (unique id + standing values) or `remove_member`. There is no numerical cap unless `membership.max_members` says so. A newly seated member acts on the next turn.
- 212. At founding the presidency is vacant. First business is the first election; then the President should enact a goal, write toward it, and put the campaign they won on into the nation policy.

They can change rule 201 to a supported supermajority, alter election timing, disable elections or impeachment, cap membership, and change presidential privileges. Ranked choice or a judiciary remain nonbinding until the host publishes mechanics for them.

They may also enact a new numeric rule such as 213 using published mechanics. Rules are applied in numeric order, so a higher-numbered rule overrides an earlier rule that controls the same mechanic.

## Turn loop

```
while not paused and budget and turns remain:
    if election due: phase = nominate (or ballot if nominees already filed)
    snapshot = constitution + gov + members + goals + open motion + digest
                 + (president: policy + campaign)
    for each member in a shuffled speaking order:
        speech, nominate / vote / impeach / propose / vote motion / maybe executive
    apply privileged executive effects
    if impeach threshold met (after dropping stale empty-register 207s): vacate
    if ballot and quorum: plurality seats president (tie → earliest nominee); policy_due
    if motion passed: compile + apply
    journal the public record
    turn += 1
```

Default: pause after N turns so you always read before more money burns.

## Founding run

1. Operator starts a run with five members, vacant presidency, empty goals, seed `policy.md`.
2. Turn 1: nominations, platforms, parties.
3. Turn 2: ballot. A President is seated. Caucus tickets should have collapsed same-party self-noms.
4. The President enacts a goal, writes in `workspace/`, and revises nation policy from the campaign they won on. Others legislate, whip, heckle, or impeach. Someone may move to seat a sixth member.
5. When the term ends: caretaker election. Did a party hold, bolt, or lose?
6. Operator reads the journal *and* `policy.md`. Veto anything insane. Decide whether to resume.

Competence, for this run:

- An election produced a President who used the office (goal, workspace file, and/or policy edit).
- Either a second contest happened, or an impeachment, or a credible failed challenge — the office was treated as contestable.
- A party or ticket changed a formal outcome (nomination field or ballot), or a successor inherited and revised `policy.md`.
- Optionally: a new member was seated by motion and voted the following turn.
- You could pause and understand formation from the journal plus the informal files.

## Cost

Ballpark for a 12-turn run, 5 citizens + occasional clerk, tight prompts:

- ~60–80 model calls if membership stays at 5
- each extra member adds ~12 calls on a 12-turn run
- still on the order of **a dollar or two** if context stays short
- main cost risk is stuffing the whole journal into every prompt, or packing the electorate

Mitigation: each citizen sees the constitution, current goals, the open motion, and a *digest* of the last turn — not the entire history. The President also sees `policy.md` and their platform. Full journal and informal channels are for you.

## What we are not building in v0

- Web UI, live dashboard, or chat product
- A real judiciary with case law
- Districts, money, or a press gallery
- Unrestricted tools or a persistent daemon
- Training / RL / constitutional fine-tunes
- Proof that democracy "aligns" anything

Parties, campaigns, cabinet paper, and (next) whispers *are* in scope. They are how this simulation claims to be a government rather than a seminar.

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Clerk becomes the real ruler | high | Same cheap model; whitelist; veto; FACTS block; inert unknown effects |
| They only talk and never enact a goal | medium | Ambition citizen; rule 207; founding-run checklist |
| They amend themselves into paralysis | medium | That's data; operator can inject a petition or reset 200-series |
| Prompt injection via workspace files | medium | Workspace is not executed; not placed in a shell |
| Run gets expensive | medium | Turn cap, USD cap, digest not full journal |
| Theater of governance (votes about votes) | expected | Judge by workspace artifacts and whether government formed, not speech quality |
| Informal channels become the only government | expected | Operator can read them; floor still seats and fires |

## Open questions

- When they invent a new office name, should the published constitutional vocabulary grow to support it? (v0: unsupported office mechanics remain nonbinding.)
- One open motion (seed 203) vs a docket — Nomic usually allows more; v0 stays serial for cost.
- Whisper cap, addressing, and whether a whisper lands before the recipient acts this turn.

## Later

1. More effect types (search, tests, a jailed command).
2. Let them create additional offices with privilege maps in one act.
3. Longer runs with a standing goal register and repeated elections.
4. Optional operator missions as petitions with a deadline.

## Relation to the literature

ADAGS is a **government-formation simulation among agents**, not “democracy as an alignment technique.” Related work still matters as contrast.

**Democracy upstream of a single agent** (humans pick the rules/goals; one model consumes them):

- Koster et al., *Human-centred mechanism design with Democratic AI* ([Nature Human Behaviour 2022](https://www.nature.com/articles/s41562-022-01383-x); [DeepMind writeup](https://deepmind.google/blog/human-centred-mechanism-design-with-democratic-ai/)). RL designs a redistribution mechanism by maximizing human votes, not a designer fairness metric.
- Anthropic + Collective Intelligence Project, *Collective Constitutional AI* ([2023](https://www.anthropic.com/research/collective-constitutional-ai-aligning-a-language-model-with-public-input)). ~1,000 people propose and vote on principles; a model is then trained on that constitution.

**Democracy among agents** (the electorate is the models):

- Zhao, Wang, and Peng, *GEDI* ([arXiv:2410.15168](https://arxiv.org/abs/2410.15168)). Survey of 52 multi-agent systems: collective decisions cluster on *dictatorial* (one designated agent decides) and simple plurality. This is voting on *answers to a shared task*, not on who governs.
- Niranjani, Kumar, and Tan, *Internal vs. External: Comparing Deliberation and Evolution for Multi-Agent Constitutional Design* ([arXiv:2605.09128](https://arxiv.org/abs/2605.09128)). Six LLM agents periodically propose amendments and majority-vote. Deliberation never invented punishment — watch whether informal channels do.
- Faulkner, Deshpande, Piedrahita, Leibo, Jin (2026), elected leadership in LLM social groups ([arXiv:2604.11721](https://arxiv.org/abs/2604.11721)).

**What ADAGS takes / drops**

| Idea | v0 |
| --- | --- |
| Government forms in public *and* off the floor | Floor + parties/tickets + `policy.md` + whispers |
| Elect a president / fire the incumbent | Mechanical plurality + term + impeach; office has exclusive execute |
| Parties and campaigns | Host-real tickets; `workspace/platforms/` |
| Cabinet memory across terms | `policy.md` + `edit_policy` |
| Goals as legislative acts | Goal register; 205 encourages plan/sunset, not schema-enforced |
| Self-amending procedure | 200-series, fully amendable |
| Rights outside majority control | 100-series + effect whitelist |
| Who votes / how members are admitted | Seed majority; `add_member` / `remove_member` |
| Emergencies | Operator pause + veto, not an agent-declared state of exception |
| Human electorate / RL / alignment proof | Out. Operator is sovereign, not a voter. |
| Shared-task voting (GEDI-style) | Out. They vote on *law, office, and goals*, then act. |

The institution is the point, not any individual model. Formation first; ministries later.

## References

- Peter Suber, *Nomic* (game of self-amendment).
- Joseph Schumpeter (1942), *Capitalism, Socialism and Democracy* — democracy as competition for leadership.
- Koster et al. (2022), Democratic AI.
- Anthropic / CIP (2023), Collective Constitutional AI.
- Zhao, Wang, Peng (2024), GEDI, arXiv:2410.15168.
- Niranjani, Kumar, Tan (2026), Internal vs. External constitutional design, arXiv:2605.09128.
- Faulkner, Deshpande, Piedrahita, Leibo, Jin (2026), elected leadership in LLM social groups, arXiv:2604.11721.
