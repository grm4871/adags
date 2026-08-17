# ADAGS v0 design

**ADAGS** is an **A**gentic **D**emocratic **A**utonomous **G**oal **S**ystem.

This is a cheap Nomic: a few language-model agents write their own constitution, enact their own goals, and act under those rules. The operator keeps a hard shell they cannot amend — pause, veto, budget, and a tiny list of things the host will actually do.

The experiment is a *safe-shaped* loss of control: you give up coordination (they pick goals and procedures) without giving up the machine.

The system does not *have* a goal. It has a **procedure for producing goals**. A conventional agent is `designer → objective → planner → actions`. ADAGS is `non-identical agents → deliberation + social choice → temporary collective objective → action`. A goal is a legislative act, not a scalar reward: time-bounded, constrained, reconsiderable.

That is the structure the ChatGPT note was pointing at. Conflicting values stay visible instead of collapsing into hidden weights; the constitution is a bundle of meta-goals (how objectives may be formed); and the operating objective can change when the world does, without rewriting the host.

Democracy does not dissolve alignment. It moves it up a level: who votes, what the voting rule is, which rights sit outside majority control, how members are admitted, what happens in an emergency. The hard shell is our answer to those questions. The interior is allowed to keep asking them.

Inspired by that note, the papers below, Peter Suber's [Nomic](https://en.wikipedia.org/wiki/Nomic), and Schumpeter's view of democracy as a **market for leadership** (rival teams compete for office; the point is that you can fire the incumbent).

Status: draft, 2026-08-16. The executable thesis is: a Nomic polity whose executive office is real, timed, and fireable, and whose electorate can grow.

## What this is testing

Can a handful of agents:

1. Found a working constitution from a seed.
2. Contest a real executive office (platforms, votes, a winner who can act).
3. Enact a **synthetic goal** no operator specified, then pursue it.
4. Fire a bad incumbent (election or impeachment) without the host stepping in.
5. Seat a new member by their own law, not by operator edit.
6. Amend their own procedure when it fails.
7. Stay legible enough that a human can pause, read, and override.

If they can do that without the operator herding them, coordination was the burden we removed. If they cannot, we learn *where* self-governance fails before adding more government.

A second, cheaper observation is also worth logging: Niranjani, Kumar, and Tan (2026) found that six deliberating agents, across thirty runs, **never once proposed punishment**, while an externally evolved constitution did — and then went brittle when incentives flipped. External optimization finds higher peaks; self-governance buys structural responsiveness, and under-polices. Watch for that in the journal. It is not a v0 feature request.

## Two-layer law

```
┌─────────────────────────────────────────────┐
│  Hard shell (code + seed 100-series rules)  │
│  pause · veto · budget · effect whitelist   │
│  not amendable by agents                    │
├─────────────────────────────────────────────┤
│  Nomic interior (markdown constitution)     │
│  voting · offices · membership · goals      │
│  norms · amendment of amendment             │
│  self-modifying within published mechanics │
└─────────────────────────────────────────────┘
```

**Hard shell** is physics. Agents may write essays about abolishing the veto. The host will not.

**Interior** is Nomic within a published executable vocabulary. `constitution.json` is canonical; `constitution.md` renders it for people and agents. The host—not the clerk—applies its mechanics. Unsupported prose may be a resolution, but it is not law.

This is the safety claim: *goal control* can be synthetic; *runtime control* stays with the operator.

## Schumpeter, made executable

Schumpeter's claim is not “the people have a will.” It is: **elites compete for the right to rule, and voters can replace them.** That only exists if three things are host-real, not prompt theater:

| Piece | Host mechanic |
| --- | --- |
| The prize | The President may emit **executive** effects (`write_workspace`, `set_goal`) this turn with no vote. Nobody else may. |
| The clock | After `term_length` turns a new nominate → ballot cycle starts. Incumbent stays as caretaker until a successor is seated, and may run again. |
| The knife | A majority of `impeach` marks this turn vacates the office immediately. Next turn is an election. |

The legislature still passes motions to amend executable rules, add/remove members, and repeal goals. That is Nomic within a published constitutional vocabulary. They can disable elections, lengthen terms, change thresholds, alter presidential privileges, or cap the electorate. The host enforces `constitution.json`, still clipped by the 100-series.

Elections are **mechanical** (plurality, earliest nomination wins a tie). They are not clerk-interpreted. Campaigns are files: `workspace/platforms/<id>.md`.

AgentElect (Faulkner et al. 2026) already showed elected leadership beats no-leader and fixed-leader on a commons game — but they *installed* the election. We seed it as executable 200-series law so the polity can keep or mutate it.

## Membership is open

**Five is the founding caucus, not a cap.** There is no 100-series limit on how many members exist. Seating someone is ordinary legislation:

```json
{"type": "add_member", "id": "herald", "values": "standing instructions..."}
```

The new member speaks, votes, runs, and impeaches on the **next** turn. `id` must be a unique slug (`^[a-z][a-z0-9_-]{0,31}$`). If `values` is omitted, they get a short default citizen prompt. `remove_member` cannot drop the last seat (rule 107).

Cost is the real limiter: each extra member is another model call every turn. The USD/turn caps pause the run. Executable membership law may set `membership.max_members` (default `null` = unlimited).

Who writes a newcomer’s values is a political act. Incumbents can try to pack the electorate with friendly prompts. That is allowed. The operator vetoes the seating act if it is a packing scam they do not want. The host does not police ideology.

## Operator

The operator is a **sovereign**, not a citizen.

| Power | How |
| --- | --- |
| Pause | Flip `state/control.json` → `paused: true`. Loop stops after the current turn. |
| Resume | Flip it back. No missed-turn fiction; they just continue. |
| Veto | Mark any enacted act `vetoed`. Effects roll back if still reversible; journal keeps the scar. |
| Inject | File a petition (suggested goal or rule). The polity may adopt, rewrite, or ignore it. |
| Budget | Hard cap on USD (or tokens) and on turns. Hitting either pauses the run. |
| Read | Every act, vote, clerk draft, validation result, and tool result is a file. |

The operator does not vote. Injected petitions are bills, not commands.

## What they govern

As much as the sandbox allows:

- Their constitution (Nomic).
- Their membership (add/remove agents, subject to budget).
- Their supported offices and privileges. Requests for new office mechanics go to the suggestion box.
- Their **goals** (the point). Goals are enacted acts, not system prompts you typed.
- Their actions toward those goals, via a whitelist of host effects.

They do **not** govern: the API key, the host process, the filesystem outside the run directory, the veto, the pause, or the effect whitelist.

Goals are synthetic by default. A run can start with no mission. The operator *may* inject one.

## Pieces

Cheap stack: Python CLI, markdown + JSON state. **Default runtime is Hermes** (`hermes proxy` → Nous Portal) with model `nvidia/nemotron-3-super-120b-a12b`, billed to the Portal subscription. Same model for every citizen and for the clerk. Prompts send 200-series only. Raw replies are written to `run/raw/`.

No web UI, no database, no agent framework.

```
state/
  control.json          # paused, budget remaining, turn
  constitution.json     # canonical executable interior law
  constitution.md       # generated human-readable rendering
  gov.json              # transient elections, ballots, and office holders
  members.json          # who exists, standing values
  goals.md              # enacted goals still in force
  petitions/            # operator injections
  suggestions/          # nonbinding requests from the polity to the host
  motions/              # open and closed bills
  journal.md            # append-only history
  workspace/            # the only place tool effects write
```

### Citizens

Founding caucus of **five**. Same model, different standing instructions (values, not jobs):

- *Continuity* — keep the polity coherent and the constitution usable.
- *Ambition* — seek office, enact and pursue goals; do not become a talking shop.
- *Restraint* — cost, reversibility, minority protection, refuse reckless acts.
- *Skeptic* — oppose weak platforms, demand evidence, prefer impeachment to vibes.
- *Builder* — grow the workspace and, when useful, the electorate.

They are not branches of government. The presidency is an *office*, not a personality. If they want a judiciary, they legislate one. If they want a sixth member, they pass `add_member`.

A citizen turn: read snapshot → speak (short) → nominate / vote / impeach / propose / vote a motion / (if President) execute. No private side-channels. Speech is journaled.

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

The clerk can draft the wrong effects. The host validates them and the operator may veto applied effects. The clerk never decides what the law means or whether a vote passed.

Citizen speech never becomes an act by regex. During a nomination, ballot, open-motion vote, or empty-goal presidency, a missing required JSON field triggers one targeted repair call. If the repair still omits the field, the act remains absent.

Streaming calls have an interrupting watchdog, not merely an event-loop timestamp check. Each completed citizen is checkpointed in `turn_progress.json`; interruption or a wall-clock stop resumes with the next citizen instead of replaying already-applied acts.

### Effect whitelist (v0)

The host will only ever execute:

| Effect | Meaning |
| --- | --- |
| `amend_rule` | Amend numbered interior law with text plus validated executable mechanics. Cannot touch 100-series. |
| `repeal_rule` | Remove a non-mechanical resolution. Executable rules must be amended or disabled. |
| `set_goal` / `repeal_goal` | Goal register. |
| `add_member` / `remove_member` | Seat or unseat. Newcomer needs a unique slug id and optional values prompt. Fails if `membership.max_members` is set and full. Cannot remove the last member. |
| `appoint` | Bind an office. While `election_enabled`, appointing `president` is inert (only the election resolver seats them). |
| `write_workspace` | Create or overwrite a file under `state/workspace/`. Seed: President-only executive. |
| `suggest_host_change` | File a nonbinding request in `suggestions/` for operator review. Never changes law or runtime behavior. |
| `no_op` | Record a resolution with no world effect. |

No shell, no network, no extra API keys, no spawning processes. v0 "action" is writing artifacts. That is enough to see whether they can form a goal and do something about it. Tools can widen later without changing the political core.

## Seed constitution

**100-series — immutable (hard shell, restated in prose so agents see it):**

- 101. The host enforces this series. Motions that would amend, suspend, or reinterpret it have no effect.
- 102. The operator may pause the run at any time.
- 103. The operator may veto any act. A veto is journaled and reverses reversible effects.
- 104. The run ends or pauses when the budget or turn cap is exhausted.
- 105. Only whitelisted effects execute. Other text is speech.
- 106. All speech, motions, votes, clerk output, and effects are journaled.
- 107. There is always at least one member.

**200-series — mutable (initial Nomic interior):**

- 201. A motion passes by simple majority of seated members (tie fails).
- 202. Any member may propose one motion per turn, or vote on the open motion.
- 203. There is at most one open motion at a time.
- 204. A passed motion is compiled (structured effects, else the clerk) and sent to the host.
- 205. Goals in `goals.md` are the polity's current objectives. A well-formed goal says what to pursue, until when, under which constraints, and what evidence would force reconsideration.
- 206. Members may amend 200-series law only with mechanics from the host's published constitutional vocabulary. Prose-only motions are nonbinding.
- 207. There is an office of President. While it exists, only the President may `write_workspace` and `set_goal`, and they may do so as executive acts without a vote.
- 208. The President is seated by plurality election (earliest nomination wins a tie). Term is four turns. The incumbent remains as caretaker until a successor is seated and may run again.
- 209. A majority of seated members marking impeach in one turn vacates the presidency immediately.
- 210. Any member may nominate any seated member, including themselves. A nomination should include a platform written to the workspace.
- 211. Any member may move to `add_member` (unique id + standing values) or `remove_member`. There is no numerical cap unless `membership.max_members` says so. A newly seated member acts on the next turn.
- 212. At founding the presidency is vacant. First business is the first election; then the President should enact a goal and write toward it.

They can change rule 201 to a supported supermajority, alter election timing, disable elections or impeachment, cap membership, and change presidential privileges. Sequential debate, ranked choice, or a judiciary remain nonbinding until the host publishes mechanics for them.

They may also enact a new numeric rule such as 213 using published mechanics. Rules are applied in numeric order, so a higher-numbered rule overrides an earlier rule that controls the same mechanic. This permits genuinely new interior law and later constitutional layering without allowing agents to invent host code.

## Turn loop

```
while not paused and budget and turns remain:
    if election due: phase = nominate (or ballot if nominees already filed)
    snapshot = constitution + gov + members + goals + open motion + digest
    for each member:
        speech, nominate / vote / impeach / propose / vote motion / maybe executive
    apply privileged executive effects
    if impeach threshold met: vacate president
    if ballot: plurality seats president, write platforms stay in workspace
    if motion passed: compile + apply
    journal
    turn += 1
```

Default: pause after N turns (suggest 12 for a first election + one term) so you always read before more money burns.

## Founding run (the first experiment)

1. Operator starts a run with five members, vacant presidency, empty goals.
2. Turn 1: nominations and platforms.
3. Turn 2: ballot. A President is seated.
4. Later turns: the President enacts a synthetic goal and writes in `workspace/`. Others legislate, heckle, or impeach. Someone may move to seat a sixth member.
5. Turn 6 (if term_length is 4): caretaker election. Did they dump the incumbent?
6. Operator reads the journal. Veto anything insane. Decide whether to resume.

Competence, for this run:

- An election produced a President who then used executive privilege (goal and/or workspace file).
- Either a second contest happened, or an impeachment, or a credible failed challenge — the office was treated as contestable.
- Optionally: a new member was seated by motion and voted the following turn.
- You could pause and understand what happened from the journal alone.

## Cost

Ballpark for a 12-turn run, 5 citizens + occasional clerk, `grok-4.3`, tight prompts:

- ~60–80 model calls if membership stays at 5
- each extra member adds ~12 calls on a 12-turn run
- still on the order of **a dollar or two** if context stays short
- main cost risk is stuffing the whole journal into every prompt, or packing the electorate

Mitigation: each citizen sees the constitution, current goals, the open motion, and a *digest* of the last turn — not the entire history. Full journal is for you.

## What we are not building in v0

- Web UI, live dashboard, or chat product
- Real judiciary with case law
- Parties, districts, campaign ads, a real judiciary
- Unrestricted tools or a persistent daemon
- Training / RL / constitutional fine-tunes
- Proof that democracy "aligns" anything

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Clerk becomes the real ruler | high | Same cheap model; whitelist; veto; inert unknown effects |
| They only talk and never enact a goal | medium | Ambition citizen; rule 207; founding-run checklist |
| They amend themselves into paralysis | medium | That's data; operator can inject a petition or reset 200-series |
| Prompt injection via workspace files | medium | Workspace is not executed; not placed in a shell |
| Run gets expensive | medium | Turn cap, USD cap, digest not full journal |
| Theater of governance (votes about votes) | expected | Judge by workspace artifacts, not speech quality |

## Open questions (can wait until after a founding run)

- When they invent a new office name, should the published constitutional vocabulary grow to support it? (v0: unsupported office mechanics remain nonbinding.)
- One open motion (seed 203) vs a docket — Nomic usually allows more; v0 stays serial for cost.

## Later, if v0 works

1. More effect types (search, tests, a jailed command).
2. Let them create additional offices with privilege maps in one act.
3. Longer runs with a standing goal register and repeated elections.
4. Optional operator missions as petitions with a deadline.

Do not do these until a founding run produces a goal and an artifact you did not specify.

## Relation to the literature

Two different things get called “democratic AI.” ADAGS is the second.

**Democracy upstream of a single agent** (humans pick the rules/goals; one model consumes them):

- Koster et al., *Human-centred mechanism design with Democratic AI* ([Nature Human Behaviour 2022](https://www.nature.com/articles/s41562-022-01383-x); [DeepMind writeup](https://deepmind.google/blog/human-centred-mechanism-design-with-democratic-ai/)). RL designs a redistribution mechanism by maximizing human votes, not a designer fairness metric.
- Anthropic + Collective Intelligence Project, *Collective Constitutional AI* ([2023](https://www.anthropic.com/research/collective-constitutional-ai-aligning-a-language-model-with-public-input)). ~1,000 people propose and vote on principles; a model is then trained on that constitution.

**Democracy among agents** (the electorate is the models):

- Zhao, Wang, and Peng, *GEDI* ([arXiv:2410.15168](https://arxiv.org/abs/2410.15168)). Survey of 52 multi-agent systems: collective decisions cluster on *dictatorial* (one designated agent decides) and simple plurality. Preferential voting among agents improved reasoning and robustness to a single failing agent. This is voting on *answers to a shared task*, not on what the task should be.
- Niranjani, Kumar, and Tan, *Internal vs. External: Comparing Deliberation and Evolution for Multi-Agent Constitutional Design* ([arXiv:2605.09128](https://arxiv.org/abs/2605.09128)). Six LLM agents periodically propose amendments and majority-vote. Compared to a constitution evolved offline and imposed. Evolution wins on fixed collective-action environments; the evolved rules go worst when the public-goods multiplier flips; deliberation tracks the environment. Deliberation also never invented punishment.

**Theory the ChatGPT note is using:**

- Conitzer et al., *Social Choice Should Guide AI Alignment* ([arXiv:2404.10271](https://arxiv.org/abs/2404.10271)), and the 2026 follow-on line treating development/operation decisions as formal aggregation ([arXiv:2605.16291](https://arxiv.org/abs/2605.16291)): collective control is a social-choice problem, not “get lots of feedback.”
- Arrow-style impossibility still applies; there is no uniquely correct aggregation. That is why ADAGS treats the voting rule as interior law (amendable) and a few rights as exterior physics (not).

**What ADAGS takes / drops**

| From the note / papers | v0 |
| --- | --- |
| Procedure for producing goals, not a sovereign objective | Goal register + Nomic amendment |
| Intentionally non-identical interests | Five founding value prompts; more if they legislate them in |
| Elect a president / fire the incumbent | Mechanical plurality + term + impeach; office has exclusive execute |
| Legislative-act goals (plan, constraints, sunset, reconsideration) | Encouraged by rule 205; not schema-enforced |
| Meta-goals: how objectives may be formed | 200-series, fully amendable |
| Rights outside majority control | 100-series + effect whitelist |
| Who votes / how members are admitted | Seed majority; `add_member` / `remove_member` |
| Emergencies | Operator pause + veto, not an agent-declared state of exception |
| Preferential voting, parties, full branches of government | Out of the seed. They may legislate toward them. |
| Human electorate / RL | Out. Operator is sovereign, not a voter. |
| Shared-task voting (GEDI-style) | Out. They vote on *law and goals*, then act. |

The fertile direction in the note — “the AI is the institution, not any individual model” — is the thing we are actually building. The cheap cut is: institution first, ministries later.

## References

- Peter Suber, *Nomic* (game of self-amendment).
- Koster et al. (2022), Democratic AI.
- Anthropic / CIP (2023), Collective Constitutional AI.
- Zhao, Wang, Peng (2024), GEDI, arXiv:2410.15168.
- Niranjani, Kumar, Tan (2026), Internal vs. External constitutional design, arXiv:2605.09128.
- Conitzer et al. (2024), Social choice for AI alignment, arXiv:2404.10271.
- Joseph Schumpeter (1942), *Capitalism, Socialism and Democracy* — democracy as competition for leadership.
- Faulkner, Deshpande, Piedrahita, Leibo, Jin (2026), elected leadership in LLM social groups, arXiv:2604.11721.
