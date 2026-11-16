"""Chat rendering and the Prompt pass-through the native VLM path relies on."""

import asyncio

from app.api.openai_api import IMAGE_PLACEHOLDER, build_prompt
from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.scheduler import Scheduler
from app.schemas import ChatMessage, ContentPart


def test_text_prompt_ends_with_empty_think_block():
    prompt, images = build_prompt([ChatMessage(role="user", content="hi")])
    assert images == []
    assert prompt == ("<|im_start|>user\nhi<|im_end|>\n"
                      "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_thinking_opt_in_leaves_think_open():
    prompt, _ = build_prompt([ChatMessage(role="user", content="hi")], enable_thinking=True)
    assert prompt.endswith("<|im_start|>assistant\n<think>\n")


def test_image_placeholder_sits_where_the_image_part_was():
    msg = ChatMessage(role="user", content=[
        ContentPart(type="image_url", image_url={"url": "data:image/png;base64,QUJD"}),
        ContentPart(type="text", text="Describe this image."),
    ])
    prompt, images = build_prompt([msg])
    assert images == ["QUJD"]
    assert f"<|im_start|>user\n{IMAGE_PLACEHOLDER}Describe this image.<|im_end|>" in prompt


class _Tagged(list):
    pass


class _OneShotMock(MockBackend):
    """Like the native backend: the whole prompt in one feed_prompt call."""

    @property
    def supports_chunked_prefill(self) -> bool:
        return False


def test_scheduler_hands_the_original_prompt_object_to_the_session():
    backend = _OneShotMock("m")
    seen = []

    async def run():
        sched = Scheduler(backend)
        orig = backend.new_session

        async def spy_session():
            s = await orig()
            feed = s.feed_prompt

            async def spy_feed(tokens):
                seen.append(tokens)
                await feed(tokens)
            s.feed_prompt = spy_feed
            return s
        backend.new_session = spy_session
        tokens = _Tagged([1, 2, 3, 4])
        tokens.extra = "kept"

        async def sink(_):
            pass
        await sched.start()
        try:
            await sched.generate("r", tokens, GenerateParams(max_tokens=2), sink)
        finally:
            await sched.stop()

    asyncio.run(run())
    assert seen and getattr(seen[0], "extra", None) == "kept"


def test_playground_renders_a_whole_conversation():
    from app.api.admin_api import ChatBody, _playground_request

    body = ChatBody(model="m", messages=[
        {"role": "system", "content": "S"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
                                     {"type": "text", "text": "what?"}]},
        {"role": "assistant", "content": "a cat"},
        {"role": "user", "content": "colour?"},
    ])
    prompt, images = _playground_request(body)
    assert images == ["QUJD"]
    assert prompt.startswith("<|im_start|>system\nS<|im_end|>\n<|im_start|>user\n<|vision_start|>")
    assert "<|im_start|>assistant\na cat<|im_end|>\n<|im_start|>user\ncolour?<|im_end|>\n" in prompt
