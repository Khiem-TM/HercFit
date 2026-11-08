from agentic.core.paths import AGENTIC_ROOT, BACKEND_ROOT
from typing import Literal
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from agentic.core.app.env_sources import JevDotEnvSettingsSource, canonical_source
from agentic.core.roster import AGENTS

# Định nghĩa cấu hình cho Agentic Service
class AgentSettings(BaseSettings):
    # Giá trị riêng của agent ghi đè giá trị mặc định dùng chung, khớp với cả hai file Compose.
    # Biến môi trường tường minh của tiến trình vẫn có độ ưu tiên cao nhất.
    model_config = SettingsConfigDict(env_file=(str(BACKEND_ROOT / '.env'), str(AGENTIC_ROOT / '.env')), extra='ignore', env_ignore_empty=True)
    MODE: str = 'dev'
    AGENT_PORT: int = 8081
    BACKEND_BASE_URL: str = 'http://localhost:8080'
    BACKEND_TIMEOUT_SECONDS: float = 15
    DEFAULT_PROVIDER: Literal['fpt', 'openai', 'openai_compatible'] = 'fpt'
    DEFAULT_MODEL: str = 'DeepSeek-V4-Flash'
    DECISION_MODEL: str | None = None
    RESPONSE_MODEL: str | None = None
    TOOL_MODEL: str | None = None
    RESEARCH_MODEL: str | None = None
    MODEL_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None
    FPT_API_KEY: SecretStr | None = None
    FPT_BASE_URL: str = 'https://mkp-api.fptcloud.com'
    MODEL_BASE_URL: str = 'https://api.openai.com/v1'
    MODEL_TIMEOUT_SECONDS: float = 30
    # Timeout theo vai trò: các lần gọi routing/tool/clarify trả về JSON nhỏ và nên
    # chuyển dự phòng nhanh; trước đây một lần gọi bị treo tốn 30 s hai lần (đuôi ≈60 s).
    ROUTING_TIMEOUT_SECONDS: float = Field(default=12, gt=0)
    # Lần gọi tool ghi cả payload (các món của bữa ăn, dinh dưỡng của thực phẩm): p95 là 13,6 s trên 500 bước tool đã lưu,
    # nên 12 s làm hỏng ~5% số đó, mỗi lần ba lượt thử (lượt chạy 195ff084 bị timeout sau một lệnh ghi đã xác nhận).
    # Ngày 02/11, lượt f6924adb và b5a60b71 (ghi 2 bữa ăn sau khi tra 17 món "xôi ...") có lời gọi tool mất 29–45 s:
    # 30 s cắt một lời gọi vẫn đúng rồi thử lại từ đầu, hai lần thử lại đốt hết ngân sách 120 s của lượt.
    TOOL_TIMEOUT_SECONDS: float = Field(default=60, gt=0)
    RESPONSE_TIMEOUT_SECONDS: float = Field(default=30, gt=0)
    RESEARCH_TIMEOUT_SECONDS: float = Field(default=45, gt=0)
    MODEL_MAX_RETRIES: int = Field(default=1, ge=0, le=3)
    CLARIFY_MODEL: str | None = None
    # Model riêng của từng agent, JSON {"nutrition": "gemma-4-26B-A4B-it", ...} (tên agent: core/roster.py). Agent vắng
    # mặt dùng model của vai trò; lỗi, timeout hoặc output sai schema của model riêng nâng lên model của vai trò.
    AGENT_MODELS: dict[str, str] = Field(default_factory=dict)
    # Timeout của model riêng (trần, không bao giờ dài hơn timeout của vai trò): gemma-4-26B từng treo tới hết 60 s của
    # vai trò tool với prompt coach ~16k token (ma trận 07/11); cắt sớm để nâng lên model của vai trò kịp thời.
    AGENT_MODEL_TIMEOUT_SECONDS: float = Field(default=20, gt=0)
    # Tin nhắn nhiều ý (RouteDecision.tasks) chạy song song ở các agent chuyên trách; False: luôn tuần tự như trước.
    PARALLEL_AGENTS: bool = True
    # Endpoint tương thích OpenAI thứ hai (tuỳ chọn), dùng khi endpoint chính lỗi hoặc timeout.
    FALLBACK_PROVIDER: Literal['fpt', 'openai', 'openai_compatible'] | None = None
    FALLBACK_MODEL: str | None = None
    FALLBACK_BASE_URL: str | None = None
    FALLBACK_API_KEY: SecretStr | None = None
    # Stream token câu trả lời tới client (chỉ model trả lời được stream; các lần gọi tool và
    # định tuyến không stream để cơ chế khôi phục lời gọi tool của nhà cung cấp vẫn hoạt động).
    STREAM_RESPONSE_TOKENS: bool = True
    # Yêu cầu nhà cung cấp gửi số liệu sử dụng trong phản hồi stream (stream_options.include_usage).
    MODEL_STREAM_USAGE: bool = False
    SSE_HEARTBEAT_SECONDS: float = Field(default=15, gt=0)
    TAVILY_API_KEY: SecretStr | None = None
    AGENT_DATABASE_URL: SecretStr = SecretStr('postgresql://hercfit:hercfit_secret@localhost:5432/hercfit_db')
    MAX_TOOL_CALLS: int = Field(default=12, ge=1, le=50)
    MAX_GRAPH_STEPS: int = Field(default=60, ge=10)
    # Một lượt ghi bữa ăn = định tuyến + 2–3 vòng tool + trả lời. Tốc độ sinh của FPT dao động 12–40 token/s
    # (cùng ~700 token: 17–60 s, đo ngày 02/11), nên 120 s từng hết hạn giữa chừng khi provider chậm.
    RUN_TIMEOUT_SECONDS: float = Field(default=180, gt=0)
    # Chế độ Plan: đọc dữ liệu sâu, tra cứu theo từng câu hỏi con và trả lời ở effort cao, nên cần thời gian dài hơn.
    PLAN_RUN_TIMEOUT_SECONDS: float = Field(default=300, gt=0)
    CONFIRMATION_TTL_SECONDS: int = Field(default=1800, gt=0)
    RESEARCH_SOURCE_DOMAINS: list[str] = []
    # DeepSeek trên FPT suy nghĩ ~9k token cho mỗi lần trích xuất ở mức mặc định (25-70 s); "low" giữ
    # nguyên các khẳng định trong 5-12 s. Chỉ áp dụng cho client tra cứu FPT (None để tắt).
    RESEARCH_REASONING_EFFORT: Literal['low', 'medium', 'high'] | None = 'low'
    # Mức suy luận của lời gọi tool. 'low' nhanh (3–17 s) nhưng 2/3 lần viết "Xem trước bữa ăn… bạn xác nhận nhé"
    # bằng văn bản thay vì gọi create_meals, nên frontend không có thẻ xác nhận (lượt 955777c0, 02/11). 'medium' gọi
    # đúng tool 4/4 lần trong 10–24 s; mức mặc định của model 3/3 lần nhưng 14–45 s. None để dùng mặc định.
    TOOL_REASONING_EFFORT: Literal['low', 'medium', 'high'] | None = 'medium'
    # Dùng chung với backend (backend/.env): ký các lệnh finalize tra cứu đã kiểm chứng.
    RESEARCH_ATTESTATION_SECRET: SecretStr | None = None
    # Dùng chung với backend (backend/.env): chứng minh service này khi đổi token người dùng
    # lấy token uỷ quyền ngắn hạn (POST /api/v2/auth/delegations).
    AGENT_SERVICE_SECRET: SecretStr | None = None
    # Quên output của tool sức khoẻ, thẻ ngữ cảnh và bộ nhớ phiên khi người dùng thu hồi consent.
    CONSENT_PURGE_ENABLED: bool = True
    JEV_MODE: Literal['off', 'shadow', 'enforce'] = 'off'
    JEV_BASE_URL: str = Field(default='https://litellm.otanicloud.link/v1',
                              validation_alias=AliasChoices('JEV_BASE_URL', 'JEV_GATEWAY_URL'))
    JEV_API_KEY: SecretStr | None = None
    JEV_MODEL: str | None = None
    JEV_TIMEOUT_SECONDS: float = Field(default=3, gt=0, le=10)
    JEV_ENFORCE_PERCENT: int = Field(default=100, ge=0, le=100)
    # Các cổng mà một lượt chạy 'enforce' được phép thay đổi quyết định; cổng còn lại chỉ ghi nhận như 'shadow'.
    JEV_ENFORCE_PHASES: list[Literal['routing', 'local', 'final']] = ['routing', 'local', 'final']
    JEV_POLICY_VERSION: str = Field(default='v1', min_length=1, max_length=64)
    JEV_INPUT_PRICE_PER_MILLION: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    JEV_OUTPUT_PRICE_PER_MILLION: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    RAG_ENABLED: bool = False
    # Knowledge graph luôn là một phần ngữ cảnh của agent; Neo4j không truy cập được
    # chỉ hạ lượt chạy xuống dùng tool backend (KG_RETRIEVAL_TIMEOUT_MS, fail-open).
    # Mẫu toàn tin nhắn chặt chẽ cho các lệnh đọc phổ biến (tiến độ, mục tiêu hiện tại, số đo
    # gần nhất, hồ sơ, mục tiêu calo): một lần gọi trả lời thay vì bốn.
    FAST_READ_ENABLED: bool = True
    NEO4J_URI: str = 'bolt://localhost:7687'
    NEO4J_USER: str = 'neo4j'
    NEO4J_PASSWORD: SecretStr | None = None
    NEO4J_DATABASE: str = 'neo4j'
    KG_BACKEND_DATABASE_URL: SecretStr | None = None
    KG_RETRIEVAL_TIMEOUT_MS: int = Field(default=150, ge=1, le=5000)
    KG_FACT_LIMIT: int = Field(default=12, ge=1, le=12)
    KG_EPISODE_LIMIT: int = Field(default=3, ge=0, le=3)
    KG_CONTEXT_TOKEN_BUDGET: int = Field(default=1500, ge=100, le=1500)
    KG_BUSINESS_RETENTION_DAYS: int = Field(default=90, ge=1)
    KG_MEMORY_RETENTION_DAYS: int = Field(default=30, ge=1)
    KG_WORKER_POLL_SECONDS: float = Field(default=1, gt=0)
    KG_WORKER_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    KG_RECONCILE_SECONDS: float = Field(default=5, gt=0)
    AGENT_DATABASE_POOL_SIZE: int = Field(default=10, ge=2)
    # Không còn dùng: phiên giờ dùng một dòng lease có thời hạn thay vì kết nối giữ advisory lock.
    AGENT_SESSION_POOL_SIZE: int = Field(default=10, ge=1)
    # Thời gian một request thứ hai cho cùng cuộc trò chuyện chờ trước khi trả 409.
    SESSION_LEASE_WAIT_SECONDS: float = Field(default=30, ge=0, le=300)
    # Chốt chặn lạm dụng và chi phí (OWASP LLM10). 0 để tắt một giới hạn.
    AGENT_RATE_LIMIT_PER_MINUTE: int = Field(default=20, ge=0)
    AGENT_DAILY_TURN_LIMIT: int = Field(default=300, ge=0)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=2_000_000, ge=0)
    # Danh tính đã kiểm chứng được cache ngắn hạn để tránh mỗi request một lượt gọi backend.
    IDENTITY_CACHE_SECONDS: float = Field(default=60, ge=0, le=600)
    # Chạy bộ đối soát checkpoint và dọn bộ nhớ trong tiến trình này (tắt trên các bản sao phụ).
    AGENT_BACKGROUND_TASKS: bool = True
    KG_RECONCILE_GRACE_SECONDS: float = Field(default=180, gt=0)
    CHECKPOINT_RETENTION_DAYS: int = Field(default=30, ge=1)
    # Bộ nhớ phiên Redis là tầng tuỳ chọn, dựng lại được, nằm trên checkpoint.
    # Nâng dần off -> shadow -> on; mọi lỗi Redis đều quay về dùng checkpoint.
    REDIS_URL: SecretStr | None = None
    REDIS_KEY_PREFIX: str = Field(default='hf:agent', min_length=1, max_length=64)
    REDIS_TIMEOUT_MS: int = Field(default=100, ge=10, le=2000)
    SESSION_MEMORY_MODE: Literal['off', 'shadow', 'on'] = 'off'
    SESSION_MEMORY_TTL_SECONDS: int = Field(default=30 * 24 * 3600, gt=0)
    SESSION_MEMORY_MAX_TURNS: int = Field(default=200, ge=10, le=1000)
    # Số tin nhắn nguyên văn mang vào mỗi lượt; 40 khớp với hành vi chỉ dùng checkpoint.
    SESSION_MEMORY_WINDOW_MESSAGES: int = Field(default=40, ge=4, le=200)
    SESSION_MEMORY_SUMMARY_ENABLED: bool = True
    SESSION_MEMORY_SUMMARY_TRIGGER_TURNS: int = Field(default=4, ge=1, le=50)
    SESSION_MEMORY_SUMMARY_MAX_CHARS: int = Field(default=2000, ge=200, le=8000)
    SESSION_MEMORY_ENTITY_LIMIT: int = Field(default=20, ge=0, le=50)
    SUMMARY_MODEL: str | None = None
    CORS_ORIGINS: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:5174', 'http://127.0.0.1:5174']

    @field_validator('AGENT_MODELS')
    @classmethod
    def known_agents(cls, value):
        # Tên agent gõ sai sẽ âm thầm dùng model mặc định: dừng ngay khi khởi động thay vì vậy.
        unknown = sorted(set(value) - AGENTS)
        if unknown:
            raise ValueError('Unknown agents in AGENT_MODELS: ' + ', '.join(unknown))
        return value

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        dotenv = JevDotEnvSettingsSource(
            settings_cls, env_file=dotenv_settings.env_file,
            env_file_encoding=dotenv_settings.env_file_encoding,
            case_sensitive=dotenv_settings.case_sensitive,
            env_ignore_empty=dotenv_settings.env_ignore_empty,
        )
        return tuple(canonical_source(source) for source in (init_settings, env_settings, dotenv, file_secret_settings))

    def check(self):
        if self.JEV_MODE != 'off':
            self.check_jev()
        if not self.model_api_key:
            raise ValueError(f'API key for {self.DEFAULT_PROVIDER} is required; runtime never falls back to fake models')
        if not self.TAVILY_API_KEY and self.MODE != 'dev':
            raise ValueError('TAVILY_API_KEY is required')
        if self.SESSION_MEMORY_MODE != 'off' and not self.REDIS_URL:
            raise ValueError('REDIS_URL is required when SESSION_MEMORY_MODE is enabled')

    def check_jev(self, *, require_model=True):
        from urllib.parse import urlsplit
        url = urlsplit(self.JEV_BASE_URL)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('JEV_BASE_URL / JEV_GATEWAY_URL must be an HTTPS API base without credentials, query or fragment')
        if require_model and (not self.JEV_MODEL or not self.JEV_MODEL.strip()):
            raise ValueError('JEV_MODEL is required; discover the gateway model using agentic.scripts.jev_preflight')
        if not self.JEV_API_KEY or not self.JEV_API_KEY.get_secret_value().strip():
            raise ValueError('JEV_API_KEY (gateway virtual key) is required when Jev is enabled')

    @property
    def model_api_key(self):
        if self.DEFAULT_PROVIDER == 'fpt':
            return self.FPT_API_KEY
        return self.MODEL_API_KEY or self.OPENAI_API_KEY

    @property
    def model_base_url(self):
        return self.FPT_BASE_URL if self.DEFAULT_PROVIDER == 'fpt' else self.MODEL_BASE_URL

    @property
    def session_lease_seconds(self):
        # Bao trùm cả lượt chạy cùng phần ghi nhật ký; lease bị bỏ dở sẽ tự hết hạn.
        return max(self.RUN_TIMEOUT_SECONDS, self.PLAN_RUN_TIMEOUT_SECONDS) + 60

agent_settings = AgentSettings()
