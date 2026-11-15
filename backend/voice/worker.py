"""Worker giọng nói HercFit: nghe (STT) và đọc (TTS) cho trang chat qua LiveKit.

Worker là lớp vào/ra. Mỗi lượt nói được gửi cho trình duyệt (RPC `hercfit.turn`); trình duyệt chạy lượt qua
/api/v1/chat/stream như khi gõ, rồi gửi lại câu trả lời cuối trên text stream `hercfit.reply`. Trong lúc chờ, worker
nói câu đệm tự nhiên ("Hmm, để mình nghĩ chút nhé."); có câu trả lời thì Gemini Flash-Lite (LiveKit Inference) viết lại
thành lời nói, code kiểm tra bản viết lại (speech.py) rồi mới đọc. Worker không giữ JWT, không gọi backend và không
đụng database.

Chạy: backend/voice/.venv/bin/python backend/voice/worker.py start
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

import speech
from dotenv import dotenv_values
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    APIConnectOptions,
    JobContext,
    cli,
    inference,
    llm,
    metrics,
)
from livekit.agents.types import FlushSentinel
from livekit.plugins import silero

# Chạy ngoài Docker: dùng chung key LiveKit với agentic, và chỉ lấy đúng các biến của lớp voice từ file đó.
for _key, _value in dotenv_values(Path(__file__).resolve().parents[1] / "agentic" / ".env").items():
    if _key.startswith(("LIVEKIT_", "VOICE_")) and _value:
        os.environ.setdefault(_key, _value)
logger = logging.getLogger("hercfit.voice")

# Phải khớp AGENT_NAME trong backend/agentic/services/voice.py (token phòng gọi đúng worker này).
AGENT_NAME = "hercfit-voice"
# Giao thức với frontend/src/composables/useVoice.ts.
TURN_METHOD = "hercfit.turn"
CANCEL_METHOD = "hercfit.cancel"
REPLY_TOPIC = "hercfit.reply"
# Dài hơn PLAN_RUN_TIMEOUT_SECONDS của agent (300 s): tab bị đóng giữa lượt không treo worker mãi.
TURN_TIMEOUT_SECONDS = 320
# Câu đệm đầu tiên nếu câu trả lời chưa về sau chừng này giây; sau đó một câu "đợi chút" mỗi WAIT_FILLER_SECONDS.
FIRST_FILLER_SECONDS = 0.4
WAIT_FILLER_SECONDS = 7
MAX_WAIT_FILLERS = 2
# Viết lại quá chừng này thì đọc bản gốc đã làm sạch (speech.fallback).
REWRITE_TIMEOUT_SECONDS = 4
REWRITE_INPUT_CHARS = 6000


class HercFitVoice(Agent):
    """Thay node model của LiveKit: câu trả lời đến từ luồng chat của trình duyệt, model chỉ viết lại thành lời nói."""

    def __init__(self, room: rtc.Room, user_identity: str, rewriter: llm.LLM):
        super().__init__(instructions="")
        self.room = room
        self.user_identity = user_identity
        self.rewriter = rewriter
        self.turns: dict[str, asyncio.Queue] = {}
        self.tasks: set[asyncio.Task] = set()
        room.register_text_stream_handler(REPLY_TOPIC, self._on_reply)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _on_reply(self, reader, participant_identity):
        if participant_identity == self.user_identity:
            self.spawn(self._read(reader))

    async def _read(self, reader):
        queue = self.turns.get((reader.info.attributes or {}).get("turn_id"))
        if queue is None:
            return  # lượt đã bị ngắt lời hoặc hết hạn
        try:
            async for chunk in reader:
                queue.put_nowait(chunk)
        except rtc.StreamError:
            logger.warning("reply stream aborted")
        finally:
            queue.put_nowait(None)

    async def rpc(self, method: str, payload: dict) -> str:
        return await self.room.local_participant.perform_rpc(
            destination_identity=self.user_identity, method=method, payload=json.dumps(payload)
        )

    @staticmethod
    async def _collect(queue: asyncio.Queue) -> str:
        parts = []
        while (chunk := await queue.get()) is not None:
            parts.append(chunk)
        return "".join(parts)

    async def _start(self, turn_id: str, text: str) -> str:
        """Gửi lượt nói cho trình duyệt; trả loại câu đệm (trình duyệt biết lượt này có phải lệnh duyệt thẻ không)."""
        answer = await self.rpc(TURN_METHOD, {"turn_id": turn_id, "text": text})
        try:
            kind = json.loads(answer).get("kind")
        except (ValueError, AttributeError):
            kind = None
        return kind if kind in ("approve", "reject") else speech.filler_kind(text)

    async def _rewrite(self, source: str) -> str:
        ctx = llm.ChatContext.empty()
        ctx.add_message(role="system", content=speech.REWRITE_PROMPT)
        ctx.add_message(role="user", content=source[:REWRITE_INPUT_CHARS])
        parts = []
        options = APIConnectOptions(max_retry=0, timeout=REWRITE_TIMEOUT_SECONDS)
        async with self.rewriter.chat(chat_ctx=ctx, conn_options=options) as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    parts.append(chunk.delta.content)
        return "".join(parts)

    async def _spoken(self, source: str) -> str:
        if not source.strip():
            return ""  # người dùng bấm Dừng: lượt không có câu trả lời, không nói gì thêm
        started = monotonic()
        try:
            rewritten = await asyncio.wait_for(self._rewrite(source), REWRITE_TIMEOUT_SECONDS)
        except Exception as exc:  # lỗi mạng, timeout, model từ chối: vẫn đọc được bản gốc
            logger.warning("voice rewrite failed: %s", type(exc).__name__)
            rewritten = ""
        text, used = speech.spoken_version(source, rewritten)
        logger.info("voice reply path=%s rewrite_ms=%d", "rewrite" if used else "fallback",
                    (monotonic() - started) * 1000)
        return text

    async def llm_node(self, chat_ctx, tools, model_settings):
        text = next(
            (item.text_content for item in reversed(chat_ctx.items) if item.type == "message" and item.role == "user"),
            None,
        )
        if not text or not text.strip():
            return
        turn_id = uuid4().hex
        queue = self.turns[turn_id] = asyncio.Queue()
        reply = asyncio.create_task(self._collect(queue))
        started = monotonic()
        try:
            kind = await self._start(turn_id, text)
            await asyncio.wait({reply}, timeout=FIRST_FILLER_SECONDS)
            last, said = None, 0
            while not reply.done():
                if said <= MAX_WAIT_FILLERS:
                    # Mỗi câu đệm là một đoạn riêng (FlushSentinel): đọc ngay, không đợi câu trả lời.
                    last = speech.pick(kind if said == 0 else "wait", last)
                    said += 1
                    yield last
                    yield FlushSentinel()
                remaining = TURN_TIMEOUT_SECONDS - (monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("voice turn timed out")
                await asyncio.wait({reply}, timeout=min(WAIT_FILLER_SECONDS, remaining))
            yield await self._spoken(reply.result())
        except (asyncio.CancelledError, GeneratorExit):
            # Người dùng nói chen: dừng lượt chat đang chạy phía trình duyệt.
            if not reply.done():
                self.spawn(self.rpc(CANCEL_METHOD, {"turn_id": turn_id}))
            raise
        except Exception:
            # Không ném lỗi ra ngoài: LiveKit sẽ thử lại, tức là chạy lượt chat lần thứ hai.
            logger.exception("voice turn failed")
            yield speech.FAILED_REPLY
        finally:
            self.turns.pop(turn_id, None)
            reply.cancel()


# Cổng health: mặc định của LiveKit ở chế độ `start` là 8081, trùng với service agentic. Một tiến trình chờ sẵn
# là đủ cho một người dùng (mặc định 8 tiến trình, mỗi tiến trình nạp riêng model VAD).
server = AgentServer(port=8082, num_idle_processes=1)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext):
    await ctx.connect()
    user = await ctx.wait_for_participant()
    voice = os.getenv("VOICE_TTS_VOICE")
    # Model của phiên chỉ viết lại câu trả lời thành lời nói; suy nghĩ "minimal" nhanh gấp đôi mặc định (đo 15/11).
    rewriter = inference.LLM(
        os.getenv("VOICE_REWRITE_MODEL", "google/gemini-3.5-flash-lite"),
        extra_kwargs={"temperature": 0.4, "max_completion_tokens": 300},
        reasoning="minimal",
    )
    session = AgentSession(
        stt=inference.STT(os.getenv("VOICE_STT", "deepgram/nova-3"), language="vi"),
        llm=rewriter,
        tts=inference.TTS(
            os.getenv("VOICE_TTS", "cartesia/sonic-3"), language="vi", **({"voice": voice} if voice else {})
        ),
        vad=silero.VAD.load(),
        turn_handling={
            # Bộ nhận diện hết lượt của LiveKit chưa hỗ trợ tiếng Việt: dùng khoảng lặng theo VAD.
            "turn_detection": "vad",
            # Khoảng lặng (tính từ tiếng nói cuối) để chốt lượt. 0,6 s tách "Chiều này… tôi định sẽ đi chạy" thành hai
            # lượt (15/11); 1,2 s giữ được chỗ ngập ngừng giữa câu, đổi lại mỗi lượt trả lời chậm thêm khoảng 0,6 s.
            "endpointing": {"min_delay": 1.2},
            # Hai từ trở lên mới tính là nói chen: tiếng ồn không huỷ một lượt đang chạy.
            "interruption": {"mode": "vad", "min_words": 2},
            # Mỗi lần gọi "model" là một lượt chat thật (tính hạn mức, có thể ghi dữ liệu): không chạy đoán trước.
            "preemptive_generation": {"enabled": False},
        },
        user_away_timeout=None,
    )
    session.on("metrics_collected", lambda event: metrics.log_metrics(event.metrics))
    await session.start(agent=HercFitVoice(ctx.room, user.identity, rewriter), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
