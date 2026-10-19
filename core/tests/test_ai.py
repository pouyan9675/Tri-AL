import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tri_al.ai import AiService, ModelError, ModelInfo, OpenAICompatible
from tri_al.ai.annotate import (
    Chunk,
    Span,
    answer_schema,
    colored,
    ground,
    normalize,
    parse,
    split,
    system_prompt,
)
from tri_al.config import (
    AiConfig,
    AnnotationLabel,
    Config,
    ConfigError,
    edit_ai_section,
    load_config,
)
from tri_al.plugins import PluginError, Registry
from tri_al.plugins.registry import Contributions
from tri_al.testing import FakeChatModel, FakeModelBackend

LABELS = [
    AnnotationLabel(name="Condition", description="Diseases", examples=["dementia", "MCI"]),
    AnnotationLabel(name="Intervention", examples=["donepezil"]),
]


def spans_text(text: str, spans: list[Span]) -> list[tuple[str, str]]:
    return [(text[s.start : s.end], s.label) for s in spans]


# --- splitting ----------------------------------------------------------------------------


def test_short_text_is_one_piece() -> None:
    assert split("Donepezil for dementia.", 100) == [Chunk(0, 0, "Donepezil for dementia.")]


def test_pieces_are_cut_between_paragraphs_and_keep_their_offsets() -> None:
    paragraphs = [f"Paragraph {n}. " + "word " * 30 for n in range(6)]
    text = "\n\n".join(paragraphs)

    chunks = split(text, 400)

    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk.text) <= 400
        assert text[chunk.start : chunk.start + len(chunk.text)] == chunk.text
        assert chunk.text.startswith("Paragraph")
    assert " ".join(chunk.text for chunk in chunks).split() == text.split()


def test_a_long_paragraph_is_cut_between_sentences_then_words() -> None:
    sentence = "Amyloid is measured with PET at every visit. "
    text = sentence * 30 + "x" * 50

    chunks = split(text, 200)

    assert all(len(chunk.text) <= 200 for chunk in chunks)
    assert all(chunk.text.startswith(("Amyloid", "x")) for chunk in chunks)
    assert " ".join(c.text for c in chunks).split() == text.split()
    word = split("y" * 450, 200)
    assert [len(chunk.text) for chunk in word] == [200, 200, 50]


def test_blank_text_has_no_pieces() -> None:
    assert split(" \n\n  ", 100) == []


def test_normalize_keeps_offsets_like_the_front_end() -> None:
    assert normalize("a\r\nb\rc") == "a\nb\nc"


# --- prompting ----------------------------------------------------------------------------


def test_the_prompt_describes_each_label_with_an_example_from_their_own() -> None:
    prompt = system_prompt(LABELS)

    assert "- Condition: Diseases (for example dementia, MCI)" in prompt
    assert "- Intervention (for example donepezil)" in prompt
    example = next(line for line in prompt.splitlines() if line.startswith("Example answer"))
    answer = json.loads(example.removeprefix("Example answer: "))
    assert answer["entities"] == [
        {"text": "dementia", "label": "Condition"},
        {"text": "donepezil", "label": "Intervention"},
        {"text": "MCI", "label": "Condition"},
    ]
    assert "Example text" not in system_prompt([AnnotationLabel(name="Condition")])


def test_the_schema_holds_answers_to_the_labels() -> None:
    schema = answer_schema(LABELS)
    item = schema["properties"]["entities"]["items"]
    assert item["properties"]["label"]["enum"] == ["Condition", "Intervention"]


def test_labels_get_free_colours() -> None:
    labels = colored(
        [
            AnnotationLabel(name="A"),
            AnnotationLabel(name="B", color="blue"),
            AnnotationLabel(name="C"),
        ]
    )
    assert [label.color for label in labels] == ["orange", "blue", "teal"]


# --- reading answers ----------------------------------------------------------------------


def test_parse_reads_json_and_keeps_known_labels() -> None:
    reply = json.dumps(
        {
            "entities": [
                {"text": "dementia", "label": "condition"},
                {"text": "walking", "label": "Exercise"},
                {"text": 3, "label": "Condition"},
            ]
        }
    )
    assert parse(reply, LABELS) == [("dementia", "Condition")]
    assert parse(f"```json\n{reply}\n```", LABELS) == [("dementia", "Condition")]


def test_parse_salvages_a_reply_cut_short() -> None:
    reply = '{"entities": [{"text": "dementia", "label": "Condition"}, {"text": "done'
    assert parse(reply, LABELS) == [("dementia", "Condition")]


def test_ground_marks_every_place_a_term_is_as_whole_words() -> None:
    text = "AD and ADRD. In AD, Alzheimer\u2019s disease\nprogresses; MADE no sense."
    chunk = Chunk(0, 100, text)

    spans = ground(chunk, [("AD", "Condition"), ("Alzheimer's disease progresses", "Condition")])

    assert spans_text(text, [Span(s.start - 100, s.end - 100, s.label) for s in spans]) == [
        ("AD", "Condition"),
        ("AD", "Condition"),
        ("Alzheimer\u2019s disease\nprogresses", "Condition"),
    ]
    assert spans[0].start == 100


def test_ground_drops_what_isnt_there_or_isnt_a_term() -> None:
    text = "Patients with dementia take donepezil in this study with their partner."
    found = [
        ("Patients", "Condition"),
        ("study", "Intervention"),
        ("Condition", "Condition"),
        ("dementias", "Condition"),
        ("Patients with dementia take donepezil in this study with their", "Condition"),
        ("x", "Condition"),
        ("donepezil.", "Intervention"),
    ]
    assert spans_text(text, ground(Chunk(0, 0, text), found)) == [("donepezil", "Intervention")]


def test_ground_gives_overlaps_to_the_longer_term() -> None:
    text = "mild cognitive impairment and cognitive tests"
    found = [("cognitive", "Condition"), ("mild cognitive impairment", "Condition")]
    assert spans_text(text, ground(Chunk(0, 0, text), found)) == [
        ("mild cognitive impairment", "Condition"),
        ("cognitive", "Condition"),
    ]


# --- the openai backend -------------------------------------------------------------------


def lmstudio(requests: list[httpx.Request], **routes: Any) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        answer = routes.get(request.url.path)
        if answer is None:
            return httpx.Response(404, json={"error": "Unexpected endpoint or method."})
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    return httpx.MockTransport(handle)


V0_MODELS = {
    "data": [
        {"id": "big", "type": "llm", "state": "not-loaded", "quantization": "Q4"},
        {"id": "small", "type": "vlm", "state": "loaded", "compatibility_type": "mlx"},
        {"id": "nomic-embed", "type": "embeddings", "state": "loaded"},
    ]
}


def test_lm_studio_says_which_models_are_loaded() -> None:
    backend = OpenAICompatible(lmstudio([], **{"/api/v0/models": V0_MODELS}))
    try:
        models = backend.models(AiConfig())
    finally:
        backend.close()

    assert models == [
        ModelInfo(id="small", kind="vlm", loaded=True, detail="mlx"),
        ModelInfo(id="big", kind="llm", loaded=False, detail="Q4"),
    ]


def test_other_servers_list_their_models() -> None:
    requests: list[httpx.Request] = []
    models = {"data": [{"id": "llama3"}, {"id": "nomic-embed-text"}]}
    backend = OpenAICompatible(lmstudio(requests, **{"/v1/models": models}))
    try:
        listed = backend.models(AiConfig(server="http://127.0.0.1:11434/v1"))
    finally:
        backend.close()

    assert listed == [ModelInfo(id="llama3")]
    assert [r.url.path for r in requests] == ["/api/v0/models", "/v1/models"]


def test_chat_asks_for_json_in_the_schema() -> None:
    requests: list[httpx.Request] = []
    message = {"content": '{"entities": []}'}
    completion = {"choices": [{"message": message, "finish_reason": "stop"}]}
    routes = {"/api/v0/models": V0_MODELS, "/v1/chat/completions": completion}
    backend = OpenAICompatible(lmstudio(requests, **routes))
    try:
        model = backend.open(AiConfig())
        reply = model.chat([{"role": "user", "content": "hi"}], schema={"type": "object"})
    finally:
        backend.close()

    assert (model.id, reply) == ("small", '{"entities": []}')
    sent = json.loads(requests[-1].content)
    assert sent["model"] == "small"
    assert sent["temperature"] == 0
    assert sent["response_format"]["json_schema"]["schema"] == {"type": "object"}


def completion(content: str | None, **message: Any) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content, **message}, "finish_reason": "stop"}]}


def chat_with(answer: Any, *, thinking: bool = False, calls: int = 1) -> list[httpx.Request]:
    requests: list[httpx.Request] = []
    backend = OpenAICompatible(lmstudio(requests, **{"/v1/chat/completions": answer}))
    try:
        model = backend.open(AiConfig(model="tiny"))
        for _ in range(calls):
            model.chat([{"role": "user", "content": "hi"}], thinking=thinking)
    finally:
        backend.close()
    return requests


def test_thinking_is_off_unless_asked_for() -> None:
    off = json.loads(chat_with(completion("{}"))[0].content)
    assert off["reasoning_effort"] == "none"  # what LM Studio reads
    assert off["chat_template_kwargs"] == {"enable_thinking": False}  # llama.cpp, vLLM
    on = json.loads(chat_with(completion("{}"), thinking=True)[0].content)
    assert "reasoning_effort" not in on
    assert "chat_template_kwargs" not in on


def test_a_server_that_refuses_a_thinking_switch_gets_the_request_without_it() -> None:
    def strict(request: httpx.Request) -> httpx.Response:
        if "reasoning_effort" in json.loads(request.content):
            detail = "reasoning_effort: Input should be 'low', 'medium' or 'high'"
            return httpx.Response(400, json={"error": {"message": detail}})
        return httpx.Response(200, json=completion("{}"))

    sent = [json.loads(r.content) for r in chat_with(strict, calls=2)]

    assert ["reasoning_effort" in body for body in sent] == [True, False, False]
    assert all(body["chat_template_kwargs"] == {"enable_thinking": False} for body in sent)


def test_other_refusals_are_errors() -> None:
    refusal = httpx.Response(400, json={"error": "context length exceeded"})
    with pytest.raises(ModelError, match="answered 400: context length exceeded"):
        chat_with(refusal)


def test_thinking_never_reaches_the_answer() -> None:
    requests: list[httpx.Request] = []
    reply = completion('<think>\nLabels first...\n</think>\n\n{"entities": []}')
    backend = OpenAICompatible(lmstudio(requests, **{"/v1/chat/completions": reply}))
    try:
        answer = backend.open(AiConfig(model="tiny")).chat([{"role": "user", "content": "hi"}])
    finally:
        backend.close()
    assert answer == '{"entities": []}'


@pytest.mark.parametrize(
    "reply",
    [
        completion("", reasoning_content="Let me think about the labels..."),
        completion("<think>Let me think about the labels"),
    ],
)
def test_a_model_that_thinks_anyway_is_named(reply: dict[str, Any]) -> None:
    with pytest.raises(ModelError, match="tiny spent its 1024 tokens thinking"):
        chat_with(reply)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (httpx.ConnectError("refused"), "can't reach the model server at http://127.0.0.1:1234/v1"),
        (httpx.ReadTimeout("slow"), "didn't answer within 60 s"),
        (
            httpx.Response(400, json={"error": {"message": "Model not found: tiny"}}),
            "answered 400: Model not found: tiny",
        ),
        (httpx.Response(500, text="oops"), "answered 500: Internal Server Error"),
        (
            {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
            "tiny ran out of tokens",
        ),
        ({"choices": []}, "had no message"),
    ],
)
def test_model_errors_say_what_went_wrong(answer: Any, message: str) -> None:
    backend = OpenAICompatible(lmstudio([], **{"/v1/chat/completions": answer}))
    try:
        model = backend.open(AiConfig(model="tiny"))
        with pytest.raises(ModelError, match=message):
            model.chat([{"role": "user", "content": "hi"}])
    finally:
        backend.close()


def test_a_server_with_no_models() -> None:
    backend = OpenAICompatible(lmstudio([], **{"/api/v0/models": {"data": []}}))
    try:
        with pytest.raises(ModelError, match="lists no models"):
            backend.open(AiConfig())
    finally:
        backend.close()


# --- the service --------------------------------------------------------------------------

TERMS = {"dementia": "Condition", "donepezil": "Intervention"}


def service(tmp_path: Path, model: FakeChatModel, **config: Any) -> AiService:
    settings = AiConfig.model_validate(
        {"backend": "fake", "annotation": {"labels": [label.model_dump() for label in LABELS]}}
        | config
    )
    return AiService(settings, tmp_path / "tri-al.toml", {"fake": FakeModelBackend(model)})


def test_annotate_streams_each_piece_then_remembers_the_text(tmp_path: Path) -> None:
    model = FakeChatModel(TERMS)
    ai = service(tmp_path, model, annotation={"chunk_chars": 200, "labels": LABELS})
    text = "Donepezil helps.\r\n\r\n" + "Dementia " * 30 + "\n\nNothing here."
    try:
        events = list(ai.annotate(text, ai.config()))
        again = list(ai.annotate(text, ai.config()))
    finally:
        ai.close()

    start, *pieces, done = events
    assert start["type"] == "start"
    assert (start["model"], start["cached"], start["length"]) == (
        "fake-model",
        False,
        len(text) - 2,
    )
    assert start["labels"] == [
        {"name": "Condition", "color": "blue"},
        {"name": "Intervention", "color": "orange"},
    ]
    # "Donepezil helps." shares a piece with the start of the next paragraph, which is
    # cut between words; its end shares one with "Nothing here."
    assert len(pieces) == start["chunks"] == len(model.calls) == 2
    assert sorted(piece["chunk"] for piece in pieces) == [0, 1]
    spans = [span for piece in pieces for span in piece["spans"]]
    plain = normalize(text)
    assert {(plain[s["start"] : s["end"]], s["label"]) for s in spans} == {
        ("Donepezil", "Intervention"),
        ("Dementia", "Condition"),
    }
    assert (done["type"], done["spans"]) == ("done", 31)

    assert again[0]["cached"] is True
    assert sorted(again[1]["spans"], key=lambda s: s["start"]) == sorted(
        spans, key=lambda s: s["start"]
    )
    assert len(model.calls) == 2  # nothing asked again
    assert model.thought == [False, False]


def test_a_model_failing_part_way_ends_the_stream_with_an_error(tmp_path: Path) -> None:
    ai = service(tmp_path, FakeChatModel(error="the model crashed"))
    try:
        events = list(ai.annotate("Some text.", ai.config()))
    finally:
        ai.close()
    assert [e["type"] for e in events] == ["start", "error"]
    assert events[-1]["message"] == "the model crashed"


def test_an_unreachable_model_fails_before_the_stream(tmp_path: Path) -> None:
    backend = FakeModelBackend(error="can't reach it")
    ai = AiService(AiConfig(backend="fake"), tmp_path / "tri-al.toml", {"fake": backend})
    try:
        with pytest.raises(ModelError, match="can't reach it"):
            ai.annotate("Some text.", ai.config())
        with pytest.raises(ModelError, match="no model backend named 'nope'"):
            ai.annotate("Some text.", AiConfig(backend="nope"))
        with pytest.raises(ModelError, match="no annotation labels"):
            ai.annotate("x", AiConfig.model_validate({"annotation": {"labels": []}}))
    finally:
        ai.close()
    assert backend.closed


def test_settings_follow_the_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "tri-al.toml"
    ai = AiService(AiConfig(), path)
    try:
        assert ai.config().model == ""
        path.write_text('[ai]\nmodel = "small"\n')
        assert ai.config().model == "small"
        time.sleep(0.01)
        path.write_text("[ai]\nmodel = 3\nparallel = 0\n")
        assert ai.config().model == "small"
        assert "keeping the last [ai] settings" in caplog.text
    finally:
        ai.close()


# --- config -------------------------------------------------------------------------------


def test_default_labels() -> None:
    labels = Config().ai.annotation.labels
    assert [label.name for label in labels] == [
        "Condition",
        "Intervention",
        "Biomarker",
        "Assessment",
    ]
    assert all(label.examples for label in labels)


@pytest.mark.parametrize(
    ("ai", "problem"),
    [
        ({"server": "localhost:1234"}, "http:// or https://"),
        ({"annotation": {"labels": [{"name": "A"}, {"name": "a"}]}}, "must differ"),
        ({"annotation": {"labels": [{"name": "A", "color": "mauve"}]}}, "color must be one of"),
        ({"annotation": {"labels": [{"name": "  "}]}}, "needs a name"),
        ({"parallel": 0}, "parallel"),
    ],
)
def test_bad_ai_settings_are_refused(tmp_path: Path, ai: dict[str, Any], problem: str) -> None:
    path = tmp_path / "tri-al.toml"
    edit_ai_section(path, {k: v for k, v in ai.items() if k != "annotation"})
    if "annotation" in ai:
        edit_ai_section(path, {}, ai["annotation"]["labels"])

    with pytest.raises(ConfigError, match=problem):
        load_config(path)


def test_edit_ai_section_writes_labels_as_tables(tmp_path: Path) -> None:
    path = tmp_path / "tri-al.toml"
    path.write_text("# my settings\n[server]\nport = 9000\n")

    edit_ai_section(path, {"model": "small"}, [{"name": "Drug", "examples": ["aspirin"]}])
    edit_ai_section(path, {"model": None, "server": "http://127.0.0.1:11434/v1"})

    written = path.read_text()
    assert written.startswith("# my settings\n[server]\nport = 9000\n")
    assert "[[ai.annotation.labels]]" in written
    assert "model" not in written
    config = load_config(path)
    assert config.ai.server == "http://127.0.0.1:11434/v1"
    assert [(label.name, label.examples) for label in config.ai.annotation.labels] == [
        ("Drug", ["aspirin"])
    ]


def test_env_overrides_ai_settings(tmp_path: Path) -> None:
    config = load_config(tmp_path / "none.toml", env={"TRI_AL_AI__MODEL": "small"})
    assert config.ai.model == "small"


# --- plugins ------------------------------------------------------------------------------


def test_plugins_add_model_backends() -> None:
    contributions = Contributions()
    registry = Registry("local", None, contributions)

    registry.add_model_backend(FakeModelBackend())

    assert list(contributions.model_backends) == ["fake"]
    with pytest.raises(PluginError, match="already added"):
        registry.add_model_backend(FakeModelBackend())
    with pytest.raises(PluginError, match="already added"):
        registry.add_model_backend(FakeModelBackend(name="openai"))
    with pytest.raises(PluginError, match="isn't a model backend"):
        registry.add_model_backend(object())  # type: ignore[arg-type]
