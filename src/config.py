"""配置加载（Phase 6）。

职责
----
* 读取 `config/config.yaml`（已被 gitignore），校验并解析为强类型配置对象。
* **把配置里的相对路径统一解析为项目根下的绝对路径**（AGENTS.md 第 5 节：禁止硬编码 `D:\\...`）。
* 收集未识别的键并暴露给调用方，避免"配置写错了但被静默忽略"。

依赖
----
PyYAML（见 `CHANGELOG.md` Phase 6 记录的引入理由）。除解析 YAML 外不再引入其他依赖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

__all__ = [
    "ConfigError",
    "SUPPORTED_CONFIG_VERSIONS",
    "DEFAULT_CONFIG_RELATIVE_PATH",
    "EXAMPLE_CONFIG_RELATIVE_PATH",
    "STATE_DB_FILENAME",
    "SyncConfig",
    "AuthConfig",
    "CollectorConfig",
    "IngestConfig",
    "LoggingConfig",
    "MediaOptions",
    "ExternalOptions",
    "PathsConfig",
    "AppConfig",
    "load_media_options",
    "load_external_options",
    "default_project_root",
    "load_config",
    "resolve_path",
]

SUPPORTED_CONFIG_VERSIONS: tuple[int, ...] = (1,)
DEFAULT_CONFIG_RELATIVE_PATH = "config/config.yaml"
EXAMPLE_CONFIG_RELATIVE_PATH = "config/config.example.yaml"
STATE_DB_FILENAME = "state.db"
FT_DATA_DIR_ENV = "FT_DATA_DIR"
_DEFAULT_PATHS: Mapping[str, str] = {
    "data_dir": "data",
    "raw_dir": "data/raw",
    "state_dir": "data/state",
    "log_dir": "data/logs",
    "knowledge_dir": "knowledge/X-Bookmarks",
}
_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "paths",
        "collector",
        "ingest",
        "media",
        "external",
        "markdown",
        "ai",
        "logging",
        "scheduler",
        "safety",
    }
)


class ConfigError(RuntimeError):
    """配置缺失、格式错误或取值非法。"""


def default_project_root() -> Path:
    """`src/config.py` 的上级目录即项目根（不依赖当前工作目录）。"""

    return Path(__file__).resolve().parents[1]


def resolve_path(value: Any, project_root: Path, *, field_name: str) -> Path:
    """把配置里的路径解析为绝对路径；相对路径以项目根为基准。"""

    if value is None or str(value).strip() == "":
        raise ConfigError(f"paths.{field_name} must not be empty")
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (project_root / path)


def _as_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{field_name} must be a boolean, got {type(value).__name__}")


def _as_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer, got {type(value).__name__}")
    return value


def _as_float(value: Any, field_name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} must be a number, got {type(value).__name__}")
    return float(value)


def _as_str(value: Any, field_name: str, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} must be a string, got {type(value).__name__}")
    text = value.strip()
    return text or default


def _as_str_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ConfigError(f"{field_name} must be a list of strings")
    if not isinstance(value, Sequence):
        raise ConfigError(f"{field_name} must be a list of strings")
    return tuple(str(item) for item in value)


def _section(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} must be a mapping, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class SyncConfig:
    """`collector.sync` —— 传给上游 `fieldtheory sync` 的默认开关。"""

    media: bool = False
    skip_profile_images: bool = True
    gaps: bool = False
    folders: bool = False
    max_minutes: int = 30
    delay_ms: int = 600
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthConfig:
    """`collector.auth` —— 认证方式；凭证只允许来自环境变量。"""

    method: str = "firefox"
    browser: str | None = "firefox"
    cookies_env: str = "FT_SYNC_COOKIES"


@dataclass(frozen=True)
class CollectorConfig:
    """`collector` —— 上游采集器接入方式。"""

    provider: str
    executable: str
    executable_args: tuple[str, ...]
    upstream_data_dir: Path | None
    read_only: bool
    sync: SyncConfig
    auth: AuthConfig

    @property
    def command(self) -> tuple[str, ...]:
        """上游命令前缀，例如 `('fieldtheory.cmd',)` 或 `('python', '-B', 'stub.py')`。"""

        return (self.executable, *self.executable_args)


@dataclass(frozen=True)
class IngestConfig:
    """`ingest` —— 入库与幂等策略。"""

    dedupe_key: str = "tweet_id"
    mark_failed_after_attempts: int = 3
    stop_after_consecutive_seen: int = 50


@dataclass(frozen=True)
class LoggingConfig:
    """`logging` —— 控制台与按日文件日志。"""

    level: str = "INFO"
    file_per_day: bool = True
    console: bool = True
    report_on_sync: bool = True


DEFAULT_MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB，与 config.example.yaml 保持一致


@dataclass(frozen=True)
class MediaOptions:
    """`media` —— 媒体本地化选项（Phase 8）。

    `media` 段与 `markdown` / `external` 一样不进 ``AppConfig`` 的强类型字段，
    由 CLI 层在需要时用 :func:`load_media_options` 从原始段构造（保持"尚未建模
    的段落通过 ``AppConfig.section`` 读取"的既有约定）。
    """

    download: bool = True
    download_video: bool = False
    max_bytes: int = DEFAULT_MAX_MEDIA_BYTES
    stable_naming: bool = True
    assets_subdir: str = "assets"


DEFAULT_MAX_EXTERNAL_BYTES = 5 * 1024 * 1024  # 5 MB，与 config.example.yaml 保持一致
DEFAULT_EXTERNAL_TIMEOUT_SECONDS = 20.0
DEFAULT_EXTERNAL_BACKOFF_SECONDS = 3.0
DEFAULT_EXTERNAL_DELAY_SECONDS = 1.0
DEFAULT_EXTERNAL_MAX_REDIRECTS = 5
DEFAULT_EXTERNAL_MAX_ATTEMPTS = 3

#: 本阶段已实现的 handler（`external.handlers` 里其余名字只提示、不启用）。
IMPLEMENTED_EXTERNAL_HANDLERS: tuple[str, ...] = ("web", "github")

#: 默认跳过的域名：X 自身的链接，正文已由富化 `## article` 提供，抓取只会撞登录墙。
DEFAULT_EXTERNAL_SKIP_DOMAINS: tuple[str, ...] = ("x.com", "twitter.com")


@dataclass(frozen=True)
class ExternalOptions:
    """`external` —— 外链抓取选项（Phase 9）。

    与 `media` 一样，本段不进 ``AppConfig`` 的强类型字段，由 CLI 层在需要时用
    :func:`load_external_options` 从原始段构造。
    """

    enabled: bool = True
    timeout_seconds: float = DEFAULT_EXTERNAL_TIMEOUT_SECONDS
    retries: int = 2
    backoff_seconds: float = DEFAULT_EXTERNAL_BACKOFF_SECONDS
    max_links_per_tweet: int = 10
    max_bytes: int = DEFAULT_MAX_EXTERNAL_BYTES
    user_agent: str = "Mozilla/5.0 (compatible; XBookmarkKnowledgePipeline)"
    handlers: tuple[str, ...] = IMPLEMENTED_EXTERNAL_HANDLERS
    max_redirects: int = DEFAULT_EXTERNAL_MAX_REDIRECTS
    max_attempts: int = DEFAULT_EXTERNAL_MAX_ATTEMPTS
    delay_seconds: float = DEFAULT_EXTERNAL_DELAY_SECONDS
    skip_domains: tuple[str, ...] = DEFAULT_EXTERNAL_SKIP_DOMAINS
    links_subdir: str = "links"
    #: 拒绝抓取非公网目标（localhost / 私网 / 链路本地 / 云元数据）；复审修复，默认开。
    block_non_public_hosts: bool = True
    #: 允许抓取的主机白名单（精确或子域，如 `example.org`）；优先级高于上面的开关。
    allow_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathsConfig:
    """`paths` —— 全部解析为绝对路径。"""

    project_root: Path
    data_dir: Path
    raw_dir: Path
    state_dir: Path
    log_dir: Path
    knowledge_dir: Path
    knowledge_layout: str
    agent_inbox: Path | None
    agent_inbox_enabled: bool

    @property
    def state_db_path(self) -> Path:
        """本项目唯一权威状态库：`data/state/state.db`。"""

        return self.state_dir / STATE_DB_FILENAME

    def raw_json_path(self, tweet_id: str) -> Path:
        """逐条原始 JSON 快照路径（永不删除）。"""

        return self.raw_dir / f"{tweet_id}.json"


@dataclass(frozen=True)
class AppConfig:
    """解析后的完整配置。"""

    version: int
    project_root: Path
    paths: PathsConfig
    collector: CollectorConfig
    ingest: IngestConfig
    logging: LoggingConfig
    source_path: Path | None = None
    unknown_keys: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def section(self, key: str) -> Mapping[str, Any]:
        """读取尚未建模的段落（media / external / markdown / ai / scheduler / safety）。"""

        value = self.raw.get(key)
        return value if isinstance(value, Mapping) else {}


def _build_paths(payload: Mapping[str, Any], project_root: Path) -> PathsConfig:
    section = _section(payload, "paths")
    resolved: dict[str, Path] = {}
    for key, default in _DEFAULT_PATHS.items():
        raw = section.get(key)
        resolved[key] = resolve_path(
            default if raw in (None, "") else raw, project_root, field_name=key
        )
    inbox_raw = _as_str(section.get("agent_inbox"), "paths.agent_inbox")
    return PathsConfig(
        project_root=project_root,
        data_dir=resolved["data_dir"],
        raw_dir=resolved["raw_dir"],
        state_dir=resolved["state_dir"],
        log_dir=resolved["log_dir"],
        knowledge_dir=resolved["knowledge_dir"],
        knowledge_layout=_as_str(
            section.get("knowledge_layout"), "paths.knowledge_layout", "year_month"
        )
        or "year_month",
        agent_inbox=(
            resolve_path(inbox_raw, project_root, field_name="agent_inbox") if inbox_raw else None
        ),
        agent_inbox_enabled=_as_bool(
            section.get("agent_inbox_enabled"), "paths.agent_inbox_enabled", False
        ),
    )


def _build_ingest(payload: Mapping[str, Any]) -> IngestConfig:
    section = _section(payload, "ingest")
    return IngestConfig(
        dedupe_key=_as_str(section.get("dedupe_key"), "ingest.dedupe_key", "tweet_id") or "tweet_id",
        mark_failed_after_attempts=_as_int(
            section.get("mark_failed_after_attempts"), "ingest.mark_failed_after_attempts", 3
        ),
        stop_after_consecutive_seen=_as_int(
            section.get("stop_after_consecutive_seen"), "ingest.stop_after_consecutive_seen", 50
        ),
    )


def _build_logging(payload: Mapping[str, Any]) -> LoggingConfig:
    section = _section(payload, "logging")
    return LoggingConfig(
        level=(_as_str(section.get("level"), "logging.level", "INFO") or "INFO").upper(),
        file_per_day=_as_bool(section.get("file_per_day"), "logging.file_per_day", True),
        console=_as_bool(section.get("console"), "logging.console", True),
        report_on_sync=_as_bool(section.get("report_on_sync"), "logging.report_on_sync", True),
    )


def load_media_options(section: Mapping[str, Any] | None) -> MediaOptions:
    """把原始 `media` 段（``AppConfig.section("media")``）构造为强类型选项。

    缺失的键取默认值；类型非法时抛 ``ConfigError``（与其余段一致的校验行为）。
    ``None`` / 空段 → 全部默认值。
    """

    data = section if isinstance(section, Mapping) else {}
    return MediaOptions(
        download=_as_bool(data.get("download"), "media.download", True),
        download_video=_as_bool(data.get("download_video"), "media.download_video", False),
        max_bytes=_as_int(data.get("max_bytes"), "media.max_bytes", DEFAULT_MAX_MEDIA_BYTES),
        stable_naming=_as_bool(data.get("stable_naming"), "media.stable_naming", True),
        assets_subdir=_as_str(data.get("assets_subdir"), "media.assets_subdir", "assets") or "assets",
    )


def load_external_options(section: Mapping[str, Any] | None) -> ExternalOptions:
    """把原始 `external` 段构造为强类型选项（Phase 9）。

    与 :func:`load_media_options` 同一约定：缺失键取默认值，类型非法抛 ``ConfigError``。
    ``handlers`` 只做字符串列表校验；"配置了尚未实现的名字"由调用方提示（不在这里报错，
    否则本机旧配置会直接让 `links` 无法运行）。
    """

    data = section if isinstance(section, Mapping) else {}
    # 注意：`skip_domains` 必须区分"键不存在"（用默认跳过名单）与"显式写 []"（不跳过任何域名），
    # 因此不能走 `_as_str_tuple(x) or 默认值` 的写法。
    skip_raw = data.get("skip_domains")
    skip_domains = (
        DEFAULT_EXTERNAL_SKIP_DOMAINS
        if skip_raw is None
        else _as_str_tuple(skip_raw, "external.skip_domains")
    )
    return ExternalOptions(
        enabled=_as_bool(data.get("enabled"), "external.enabled", True),
        timeout_seconds=_as_float(
            data.get("timeout_seconds"),
            "external.timeout_seconds",
            DEFAULT_EXTERNAL_TIMEOUT_SECONDS,
        ),
        retries=_as_int(data.get("retries"), "external.retries", 2),
        backoff_seconds=_as_float(
            data.get("backoff_seconds"),
            "external.backoff_seconds",
            DEFAULT_EXTERNAL_BACKOFF_SECONDS,
        ),
        max_links_per_tweet=_as_int(
            data.get("max_links_per_tweet"), "external.max_links_per_tweet", 10
        ),
        max_bytes=_as_int(
            data.get("max_bytes"), "external.max_bytes", DEFAULT_MAX_EXTERNAL_BYTES
        ),
        user_agent=_as_str(
            data.get("user_agent"),
            "external.user_agent",
            ExternalOptions().user_agent,
        )
        or ExternalOptions().user_agent,
        handlers=_as_str_tuple(data.get("handlers"), "external.handlers")
        or IMPLEMENTED_EXTERNAL_HANDLERS,
        max_redirects=_as_int(
            data.get("max_redirects"), "external.max_redirects", DEFAULT_EXTERNAL_MAX_REDIRECTS
        ),
        max_attempts=_as_int(
            data.get("max_attempts"), "external.max_attempts", DEFAULT_EXTERNAL_MAX_ATTEMPTS
        ),
        delay_seconds=_as_float(
            data.get("delay_seconds"), "external.delay_seconds", DEFAULT_EXTERNAL_DELAY_SECONDS
        ),
        skip_domains=skip_domains,
        links_subdir=_as_str(data.get("links_subdir"), "external.links_subdir", "links")
        or "links",
        block_non_public_hosts=_as_bool(
            data.get("block_non_public_hosts"), "external.block_non_public_hosts", True
        ),
        allow_hosts=_as_str_tuple(data.get("allow_hosts"), "external.allow_hosts"),
    )


def _build_collector(
    payload: Mapping[str, Any], project_root: Path, env: Mapping[str, str]
) -> CollectorConfig:
    section = _section(payload, "collector")
    sync_section = _section(section, "sync")
    auth_section = _section(section, "auth")

    data_dir_raw = _as_str(section.get("upstream_data_dir"), "collector.upstream_data_dir")
    env_data_dir = env.get(FT_DATA_DIR_ENV)
    upstream_data_dir: Path | None = None
    if data_dir_raw:
        # 项目配置优先：配置文件是本项目的权威来源；环境变量只在配置留空时回退。
        # （实测教训：若让环境变量覆盖配置，离线测试会写进真实上游目录。）
        upstream_data_dir = resolve_path(
            data_dir_raw, project_root, field_name="upstream_data_dir"
        )
    elif env_data_dir:
        upstream_data_dir = Path(env_data_dir).expanduser()

    return CollectorConfig(
        provider=_as_str(section.get("provider"), "collector.provider", "fieldtheory")
        or "fieldtheory",
        executable=_as_str(section.get("executable"), "collector.executable", "fieldtheory.cmd")
        or "fieldtheory.cmd",
        executable_args=_as_str_tuple(section.get("executable_args"), "collector.executable_args"),
        upstream_data_dir=upstream_data_dir,
        read_only=_as_bool(section.get("read_only"), "collector.read_only", True),
        sync=SyncConfig(
            media=_as_bool(sync_section.get("media"), "collector.sync.media", False),
            skip_profile_images=_as_bool(
                sync_section.get("skip_profile_images"), "collector.sync.skip_profile_images", True
            ),
            gaps=_as_bool(sync_section.get("gaps"), "collector.sync.gaps", False),
            folders=_as_bool(sync_section.get("folders"), "collector.sync.folders", False),
            max_minutes=_as_int(sync_section.get("max_minutes"), "collector.sync.max_minutes", 30),
            delay_ms=_as_int(sync_section.get("delay_ms"), "collector.sync.delay_ms", 600),
            extra_args=_as_str_tuple(sync_section.get("extra_args"), "collector.sync.extra_args"),
        ),
        auth=AuthConfig(
            method=_as_str(auth_section.get("method"), "collector.auth.method", "firefox")
            or "firefox",
            browser=_as_str(auth_section.get("browser"), "collector.auth.browser", "firefox"),
            cookies_env=_as_str(
                auth_section.get("cookies_env"), "collector.auth.cookies_env", "FT_SYNC_COOKIES"
            )
            or "FT_SYNC_COOKIES",
        ),
    )


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    project_root: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    require_file: bool = True,
) -> AppConfig:
    """读取并校验配置。

    `path` 为空时使用 `<project_root>/config/config.yaml`；`project_root` 为空时
    先看 `paths.project_root`，再按代码位置推断（`src/config.py` 的上级目录）。
    `require_file=False` 时允许文件缺失，此时全部使用默认值（供 `doctor` 探测）。
    """

    environment = dict(os.environ if env is None else env)
    base_root = Path(project_root).expanduser().resolve() if project_root else default_project_root()
    source_path = Path(path).expanduser() if path else base_root / DEFAULT_CONFIG_RELATIVE_PATH

    exists = source_path.is_file()
    if not exists:
        if require_file:
            raise ConfigError(
                f"config file not found: {source_path}. Copy {EXAMPLE_CONFIG_RELATIVE_PATH} "
                f"to {DEFAULT_CONFIG_RELATIVE_PATH} first."
            )
        payload: Mapping[str, Any] = {}
    else:
        try:
            loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"{source_path}: invalid YAML ({exc})") from exc
        if loaded is None:
            payload = {}
        elif not isinstance(loaded, Mapping):
            raise ConfigError(f"{source_path}: top level must be a mapping")
        else:
            payload = loaded

    version = _as_int(payload.get("version"), "version", 1)
    if version not in SUPPORTED_CONFIG_VERSIONS:
        raise ConfigError(
            f"unsupported config version {version}; supported: {list(SUPPORTED_CONFIG_VERSIONS)}"
        )

    configured_root = _as_str(_section(payload, "paths").get("project_root"), "paths.project_root")
    if configured_root:
        candidate = Path(configured_root).expanduser()
        project_root_path = (candidate if candidate.is_absolute() else base_root / candidate).resolve()
    else:
        project_root_path = base_root

    unknown = tuple(sorted(set(payload) - _KNOWN_TOP_LEVEL_KEYS))

    return AppConfig(
        version=version,
        project_root=project_root_path,
        paths=_build_paths(payload, project_root_path),
        collector=_build_collector(payload, project_root_path, environment),
        ingest=_build_ingest(payload),
        logging=_build_logging(payload),
        source_path=source_path if exists else None,
        unknown_keys=unknown,
        raw=dict(payload),
    )


