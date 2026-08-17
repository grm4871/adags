import time

from adags.citizens import _interior_law, snapshot_user
from adags.llm import extract_json, resolve_provider
from adags.seed import CONSTITUTION, FOUNDING_MEMBERS, default_gov


def test_resolve_provider_aliases(monkeypatch):
    monkeypatch.delenv("ADAGS_PROVIDER", raising=False)
    assert resolve_provider("openai") == "openai"
    assert resolve_provider("nous") == "hermes"
    assert resolve_provider("portal") == "hermes"


def test_resolve_provider_defaults_hermes(monkeypatch):
    monkeypatch.delenv("ADAGS_PROVIDER", raising=False)
    assert resolve_provider(None) == "hermes"


def test_complete_timeout_returns_error():
    from adags.llm import ChatLLM, LLMResult

    class Boom:
        def __init__(self, *a, **k):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(**k):
                    raise TimeoutError("took too long")

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "x"
    llm.json_mode = False
    llm.timeout = 1
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = Boom()
    result = ChatLLM.complete(llm, system="s", user="u")
    assert result.error
    assert result.text == ""


def test_paid_call_is_refused_when_cap_cannot_cover_prompt():
    from adags.llm import ChatLLM

    class MustNotCall:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise AssertionError("provider call should have been refused")

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "paid"
    llm.json_mode = False
    llm.timeout = 10
    llm.deadline = None
    llm.remaining_usd = 0.000001
    llm._in_rate = 10.0
    llm._out_rate = 10.0
    llm.client = MustNotCall()
    result = llm.complete(system="s" * 1000, user="u" * 1000)
    assert result.error == "spend cap has insufficient room for another call"


def test_call_is_refused_after_wall_clock_deadline():
    from adags.llm import ChatLLM

    class MustNotCall:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise AssertionError("provider call should have been refused")

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "free"
    llm.json_mode = False
    llm.timeout = 10
    llm.deadline = time.monotonic() - 1
    llm.remaining_usd = None
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = MustNotCall()
    result = llm.complete(system="s", user="u")
    assert result.error == "wall-clock deadline reached"


def test_blocked_stream_is_interrupted_and_partial_output_survives():
    from types import SimpleNamespace

    from adags.llm import ChatLLM

    class StalledStream:
        def __iter__(self):
            yield SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=SimpleNamespace(content='{"speech":"hi', reasoning="", reasoning_content=None, model_extra={}))],
            )
            time.sleep(1)

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return StalledStream()

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "free"
    llm.json_mode = False
    llm.timeout = 0.03
    llm.deadline = None
    llm.remaining_usd = None
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = Client()
    started = time.monotonic()
    result = llm.complete(system="s", user="u")
    assert time.monotonic() - started < 0.5
    assert result.error
    assert "timeout" in result.error.lower() or "deadline" in result.error.lower()
    assert result.text.endswith('{"speech":"hi')


def test_think_budget_cuts_planning_and_keeps_partial_text():
    from types import SimpleNamespace

    from adags.llm import ChatLLM

    class ThinkForever:
        def __iter__(self):
            for i in range(50):
                yield SimpleNamespace(
                    usage=None,
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="",
                                reasoning=f"plan {i} ",
                                reasoning_content=None,
                                model_extra={},
                            )
                        )
                    ],
                )
                time.sleep(0.02)

        def close(self):
            self.closed = True

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return ThinkForever()

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "free"
    llm.json_mode = False
    llm.timeout = 5
    llm.think_timeout = 0.08
    llm.first_token_timeout = 2
    llm.deadline = None
    llm.remaining_usd = None
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = Client()
    started = time.monotonic()
    result = llm.complete(system="s", user="u")
    assert time.monotonic() - started < 1.0
    assert result.cut == "think"
    assert result.error is None
    assert "plan" in result.text


def test_speech_is_not_cut_by_think_budget():
    from types import SimpleNamespace

    from adags.llm import ChatLLM

    class Speaks:
        def __iter__(self):
            yield SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content='{"speech":"aye"}',
                            reasoning="",
                            reasoning_content=None,
                            model_extra={},
                        )
                    )
                ],
            )

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return Speaks()

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "free"
    llm.json_mode = False
    llm.timeout = 5
    llm.think_timeout = 0.001
    llm.first_token_timeout = 2
    llm.deadline = None
    llm.remaining_usd = None
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = Client()
    result = llm.complete(system="s", user="u")
    assert result.cut is None
    assert "aye" in result.text


def test_delta_parts_does_not_double_identical_streams():
    from types import SimpleNamespace

    from adags.llm import _delta_parts

    delta = SimpleNamespace(content="We ", reasoning="We ", reasoning_content=None, model_extra={})
    content, think = _delta_parts(delta)
    assert content == "We "
    assert think == "We "


def test_stream_live_view_skips_reasoning():
    from types import SimpleNamespace

    from adags.llm import ChatLLM

    class Stream:
        def __iter__(self):
            yield SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="",
                            reasoning="We need to output JSON",
                            reasoning_content=None,
                            model_extra={},
                        )
                    )
                ],
            )
            yield SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content='{"speech":"aye"}',
                            reasoning="",
                            reasoning_content=None,
                            model_extra={},
                        )
                    )
                ],
            )

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**k):
                    return Stream()

    llm = ChatLLM.__new__(ChatLLM)
    llm.model = "x"
    llm.json_mode = False
    llm.timeout = 1
    llm._in_rate = 0
    llm._out_rate = 0
    llm.client = Client()
    seen: list[str] = []
    thinks: list[str] = []
    result = ChatLLM._complete_stream(llm, {}, seen.append, thinks.append)
    assert thinks == ["We need to output JSON"]
    assert seen == ['{"speech":"aye"}']
    assert result.text == '{"speech":"aye"}'


def test_extract_json_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_think_tags_and_prose():
    blob = '<think>nope</think>\nSure.\n{"speech": "hi", "nominate": null}\nbye'
    assert extract_json(blob)["speech"] == "hi"


def test_salvage_truncated_nominate():
    from adags.llm import salvage_act

    blob = '''{"speech": "I nominate myself.", "nominate": {"member": "restraint", "platform": "go slow'''
    act = salvage_act(blob)
    assert act["nominate"]["member"] == "restraint"
    assert "I nominate" in act["speech"]


def test_apply_prefix_glues_continuation():
    from adags.llm import apply_prefix

    assert apply_prefix('{"speech":"', 'I vote aye."}') == '{"speech":"I vote aye."}'
    assert apply_prefix('{"speech":"', '{"speech":"I vote aye."}') == '{"speech":"I vote aye."}'
    assert apply_prefix(None, "x") == "x"



def test_planned_speech_from_notes():
    from adags.llm import planned_speech, salvage_act

    blob = (
        "We need to output JSON.\n"
        'Let\'s craft speech: "I vote aye on expanding membership."\n'
        "Then nominate null."
    )
    assert planned_speech(blob) == "I vote aye on expanding membership."
    assert salvage_act(blob)["speech"] == "I vote aye on expanding membership."


def test_citizen_repairs_empty_first_call():
    from adags.citizens import citizen_act
    from adags.llm import ScriptedLLM
    from adags.seed import FOUNDING_MEMBERS

    blank = {
        "speech": "",
        "nominate": None,
        "vote_election": None,
        "impeach": False,
        "propose": None,
        "vote_motion": None,
        "executive": None,
    }
    good = {**blank, "speech": "I vote for continuity.", "vote_election": "continuity"}
    llm = ScriptedLLM(scripts=[blank, good])
    act = citizen_act(llm, member=FOUNDING_MEMBERS[0], user="go")
    assert act["speech"] == "I vote for continuity."
    assert act["vote_election"] == "continuity"


def test_citizen_infers_announced_vote_without_a_second_call():
    from adags.citizens import citizen_act
    from adags.llm import ScriptedLLM
    from adags.seed import FOUNDING_MEMBERS

    speech_only = {"speech": "I vote for continuity.", "vote_election": None}
    llm = ScriptedLLM(scripts=[speech_only])
    act = citizen_act(
        llm,
        member=FOUNDING_MEMBERS[0],
        user="ballot",
        required="vote_election",
    )
    assert llm.i == 1
    assert act["vote_election"] == "continuity"


def test_missing_motion_ballot_abstains_instead_of_stalling():
    from adags.citizens import citizen_act
    from adags.llm import ScriptedLLM
    from adags.seed import FOUNDING_MEMBERS

    llm = ScriptedLLM(
        scripts=[
            {
                "speech": "",
                "nominate": None,
                "vote_election": None,
                "impeach": False,
                "propose": None,
                "vote_motion": None,
                "executive": None,
            }
        ]
    )
    act = citizen_act(
        llm,
        member=FOUNDING_MEMBERS[0],
        user="motion",
        required="vote_motion",
    )
    assert act["vote_motion"] == "abstain"


def test_fulfill_speech_turns_talk_into_votes():
    from adags.llm import fulfill_speech

    nay = fulfill_speech(
        {"speech": "I vote no on the motion to admit picker.", "vote_motion": None},
        member_id="skeptic",
    )
    assert nay["vote_motion"] == "nay"
    nom = fulfill_speech(
        {"speech": "I nominate myself.", "nominate": None},
        member_id="continuity",
    )
    assert nom["nominate"]["member"] == "continuity"
    not_phase = fulfill_speech(
        {"speech": "We are in the nominate phase.", "nominate": None},
        member_id="continuity",
    )
    assert not not_phase.get("nominate")
    not_any = fulfill_speech(
        {"speech": "I vote for any.", "vote_election": None},
        member_id="skeptic",
    )
    assert not not_any.get("vote_election")
    graffiti = fulfill_speech(
        {
            "speech": (
                "I vote no on m61-restraint to preserve the President's "
                "constitutional authority to set goals and write the workspace, "
                "ensuring stable governance."
            ),
            "executive": None,
        },
        member_id="continuity",
        president=True,
    )
    assert not graffiti.get("executive")
    explicit = fulfill_speech(
        {"speech": "I set goal open participation and write a log.", "executive": None},
        member_id="continuity",
        president=True,
    )
    assert explicit["executive"][0]["type"] == "set_goal"
    assert "open participation" in explicit["executive"][0]["text"]
    cited = fulfill_speech(
        {"speech": "I impeach the President under 303.", "impeach": False},
        member_id="skeptic",
    )
    assert cited["impeach"] == "303"
    threat = fulfill_speech(
        {"speech": "I will impeach next turn under 303.", "impeach": False},
        member_id="skeptic",
    )
    assert not threat.get("impeach")


def test_growing_speech_ignores_protocol_notes():
    from adags.llm import growing_speech

    buf = (
        "We need to output JSON with speech, nominate, vote_election.\n"
        "vote_motion: aye. propose: null.\n"
        '{"speech": "I vote aye on expanding membership.", "nominate": null'
    )
    assert growing_speech(buf) == "I vote aye on expanding membership."
    assert growing_speech("thinking about speech and votes") == ""
    assert growing_speech('{"speech": "I vote') == "I vote"


def test_growing_speech_uses_last_draft():
    from adags.llm import growing_speech

    buf = '{"speech": "draft", "x": 1}\n{"speech": "I vote aye on m19."}'
    assert growing_speech(buf) == "I vote aye on m19."


def test_growing_speech_decodes_escapes():
    from adags.llm import growing_speech

    assert growing_speech(r'{"speech": "line\nnext"}') == "line\nnext"
    assert growing_speech('{"speech": "say \\"aye\\""}') == 'say "aye"'


def test_chamber_voice_status_while_waiting():
    from adags.render import ChamberVoice

    chunks: list[str] = []
    voice = ChamberVoice(interval=10, write=chunks.append)
    voice.feed("We need to output JSON with speech, nominate, vote.\n")
    assert "thinking" in voice.status_text()
    assert voice.chars > 0
    assert voice.finish() is False


def test_chamber_voice_think_then_speech():
    from adags.render import ChamberVoice

    chunks: list[str] = []
    voice = ChamberVoice(interval=10, width=80, write=chunks.append)
    voice.feed_think("We need to pick a nominee. Continuity is safest.")
    voice.feed('{"speech":"I vote continuity."}')
    spoke = voice.finish()
    shown = "".join(chunks)
    assert spoke is True
    assert "We need to pick a nominee" not in shown
    assert "thought" in shown
    assert "I vote continuity." in shown


def test_as_ballot_accepts_object_votes():
    from adags.render import act_marks, as_ballot

    assert as_ballot({"aye": True}) == "aye"
    assert as_ballot({"vote": "nay"}) == "nay"
    assert as_ballot("no") == "nay"
    assert as_ballot("yes") == "aye"
    assert as_ballot("against") == "nay"
    assert as_ballot(["aye"]) is None
    assert act_marks({"vote_motion": {"choice": "abstain"}}) == ["abstain on the motion"]


def test_visible_speech_drops_leading_brace():
    from adags.render import visible_speech

    assert visible_speech('{"speech":"{') == ""
    assert visible_speech('{"speech":"{I vote aye."}') == "I vote aye."


def test_wait_line_clears_before_speech():
    from adags.render import ChamberVoice

    chunks: list[str] = []
    voice = ChamberVoice(interval=10, width=80, write=chunks.append)
    voice.feed('{"speech":"')
    voice._paint(voice.status_text())
    voice.feed("{")
    voice.feed('I vote aye."}')
    voice.finish()
    shown = "".join(chunks)
    assert "waiting on model│" not in shown
    assert shown.count("thought") <= 1
    assert "I vote aye." in shown
    assert shown.split("I vote aye.")[0].rstrip().endswith("│") or "│ I vote aye." in shown


def test_json_prefix_is_not_thinking():
    from adags.render import ChamberVoice

    chunks: list[str] = []
    voice = ChamberVoice(interval=10, width=80, write=chunks.append)
    voice.feed('{"speech":"')
    voice.feed('I vote aye."}')
    voice.finish()
    shown = "".join(chunks)
    assert '{"speech"' not in shown
    assert "I vote aye." in shown


def test_act_marks_keep_full_titles():
    from adags.render import act_marks, format_votes

    marks = act_marks(
        {
            "speech": "I nominate myself for President to continue steady governance, and I pro",
            "nominate": {"member": "continuity", "platform": "steady"},
            "propose": {
                "title": "Amend rule 206 to require rationale and impact analysis",
                "text": "…",
                "effects": [],
            },
            "vote_motion": "aye",
        }
    )
    assert "nominates continuity" in marks
    assert "proposes Amend rule 206 to require rationale and impact analysis" in marks
    assert "aye on the motion" in marks
    assert not any(m.endswith(" pro") for m in marks)
    fail = act_marks(
        {
            "_usage": {
                "parse_error": "no JSON",
                "raw": "x" * 4120,
                "error": None,
            }
        }
    )
    assert fail == ["no valid act · 4120 chars raw"]
    assert format_votes({"restraint": "aye", "skeptic": "nay"}) == "aye restraint · nay skeptic"


def test_speech_printer_hides_cot():
    from adags.render import SpeechPrinter

    chunks: list[str] = []
    printer = SpeechPrinter(width=80, write=chunks.append)
    printer.feed("We need to output JSON with speech, nominate, vote_election.\n")
    printer.feed("Rule 202 says one motion per turn. Let's produce.\n")
    printer.feed('{"speech": "I vote aye')
    printer.feed(' on expanding membership.", "vote_motion": "aye"}')
    printer.finish()
    shown = "".join(chunks)
    assert "We need to output JSON" not in shown
    assert "Rule 202" not in shown
    assert "I vote aye on expanding membership." in shown


def test_speech_printer_collapses_blank_lines():
    from adags.render import SpeechPrinter

    chunks: list[str] = []
    printer = SpeechPrinter(width=80, write=chunks.append)
    printer.feed('{"speech": "I support this.\\n\\n\\nWe must stay deliberate."}')
    printer.finish()
    shown = "".join(chunks)
    assert "\n\n" not in shown
    assert "I support this. We must stay deliberate." in shown


def test_speech_printer_wraps_to_width():
    from adags.render import SpeechPrinter

    chunks: list[str] = []
    printer = SpeechPrinter(indent="    ", width=20, write=chunks.append)
    printer.feed('{"speech": "I vote aye on expanding membership now"}')
    printer.finish()
    lines = "".join(chunks).splitlines()
    assert lines == [
        "    I vote aye on",
        "    expanding",
        "    membership now",
    ]
    assert all(len(line) <= 20 for line in lines)


def test_unaffiliated_party_line_urges_founding():
    from adags.citizens import party_line
    from adags.seed import FOUNDING_MEMBERS

    text = party_line(FOUNDING_MEMBERS[0], FOUNDING_MEMBERS)
    assert "unaffiliated" in text
    assert "Invent a slug" in text


def test_interior_law_drops_100_series():
    text = _interior_law(CONSTITUTION)
    assert "208." in text
    assert "101." not in text
    assert "Chamber law" in text
    assert "301." in text


def test_snapshot_is_short():
    user = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=default_gov(),
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n\n(none enacted)\n",
        open_motion=None,
        digest="x" * 5000,
        petitions=[],
        turn=1,
    )
    assert "101." not in user
    assert "Continue from the assistant prefix" not in user
    assert "If you are President, set a goal" not in user
    assert "offices:" not in user
    assert "JSON only" in user
    assert "HOST: this is a live ballot" not in user
    assert "Last time you acted:" in user
    assert "Workspace:" in user
    assert len(user) < len(CONSTITUTION) + 4000


def test_snapshot_ballot_replaces_false_digest():
    gov = default_gov()
    gov["election_phase"] = "ballot"
    gov["offices"]["president"]["holder"] = "continuity"
    gov["offices"]["president"]["term_start"] = 23
    gov["nominees"] = [
        {"member": "builder", "nominator": "builder", "platform": "tools"},
        {"member": "ambition", "nominator": "ambition", "platform": "go"},
    ]
    gov["ballots"] = {"continuity": "builder"}
    user = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n\n(none)\n",
        open_motion=None,
        digest="**builder:** The election is complete. Builder has won by unanimous vote.",
        petitions=[],
        turn=33,
    )
    assert "HOST: live ballot" in user
    assert "caretaker" in user
    assert "Builder has won by unanimous vote" not in user
    assert "1/3" in user or "1/" in user
    assert "Legal votes: builder, ambition" in user


def test_snapshot_idle_says_election_over():
    gov = default_gov()
    gov["election_phase"] = "idle"
    gov["offices"]["president"]["holder"] = "continuity"
    gov["offices"]["president"]["term_start"] = 2
    user = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n",
        open_motion=None,
        digest="I see we're still in ballot phase with one vote each.",
        petitions=[],
        turn=3,
    )
    assert "election is over" in user
    assert "continuity is President" in user
    assert "nominate and vote_election do nothing" in user
    assert "Goals are empty" in user
    assert "impeach with a cited article" in user


def test_snapshot_idle_shows_goal_clock_and_waits_on_motion():
    gov = default_gov()
    gov["election_phase"] = "idle"
    gov["offices"]["president"]["holder"] = "continuity"
    gov["offices"]["president"]["term_start"] = 1
    user = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=gov,
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n\n## g1\nKeep a civic journal until turn 12.\n",
        open_motion={"id": "m4-builder", "title": "Still open", "text": "x", "effects": [], "votes": {}},
        digest="",
        petitions=[],
        turn=9,
        goal_clock="g1 overdue 1/3 files, due turn 4",
    )
    assert "Goals: g1 overdue 1/3 files, due turn 4" in user
    assert "An election is due; it waits until this motion closes." in user


def test_snapshot_reports_identical_articles():
    user = snapshot_user(
        member_id="ambition",
        constitution=CONSTITUTION,
        gov=default_gov(),
        members=FOUNDING_MEMBERS,
        goals_md="# Goals\n\n## g1\nKeep a civic journal.\n",
        open_motion=None,
        digest="",
        petitions=[],
        turn=3,
        identical_line="302 = 304 = 305 (identical text)",
    )
    assert "HOST: 302 = 304 = 305 (identical text)." in user


def test_wrap_field_keeps_party_chips_intact(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    from adags.render import format_roster, visible_width, wrap_field

    roster = {
        "builder": ["ambition"],
        "builder_caucus": ["builder"],
        "continuity_caucus": ["continuity"],
    }
    lines = wrap_field("parties", format_roster(roster), width=48, atom="; ")
    assert lines[0].startswith("  parties")
    joined = "\n".join(lines)
    assert joined.count("●") == 3
    assert not joined.splitlines()[0].rstrip().endswith("●")
    hang = visible_width(f"{'':2}{'parties':<9} ")
    for line in lines[1:]:
        assert visible_width(line) - visible_width(line.lstrip()) == hang


def test_party_colors_are_stable_and_split():
    from adags.render import format_roster, paint_party, party_fg

    assert party_fg("watch") == party_fg("watch")
    assert party_fg("watch") != party_fg("reform")
    assert "watch" in paint_party("watch")
    roster = format_roster({"watch": ["continuity", "ambition"], "reform": ["restraint"]})
    assert "watch" in roster and "reform" in roster
    assert "continuity" in roster


def test_act_marks_ignore_wrong_phase():
    from adags.render import act_marks

    act = {
        "nominate": {"member": "restraint"},
        "vote_election": {"member": "builder"},
    }
    marks = act_marks(act, phase="idle", seated=["continuity", "restraint", "builder"])
    assert "ignored nominate (idle)" in marks
    assert "ignored vote (idle)" in marks
    assert act_marks(act) == ["nominates restraint", "votes builder"]
