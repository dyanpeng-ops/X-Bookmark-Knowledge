"""统一外链抓取封装（Phase 9）。

职责边界
--------
* 只做「HTTP 取回 + 逐跳跟随重定向 + 编码探测 + 体积上限 + 重试与退避」，
  **不做正文抽取**（在 `handlers/`），也**不写盘、不落库**（在 `resolver.py`）。
* 网络访问集中在本模块：其余层不直接使用 `urllib`（AGENTS.md 第 5 节）。
* 传输层（`transport`）可注入，因此全部测试无需真实网络（`tests/README.md` 的约定）。
* **目标安全校验（复审修复）**：抓取前与**每一次重定向跳转后**都经 :mod:`src.external.netguard`
  校验，拒绝 `localhost` / 私网 / 链路本地 / 云元数据等非公网目标（默认开启，可用
  `external.block_non_public_hosts: false` 关闭，或 `external.allow_hosts` 显式放行）。

实现选择
--------
* 只用标准库 `urllib.request`（ADR-017）：不引入 httpx/requests。
* 重定向**显式逐跳跟随**（`_NoRedirectHandler` 让 3xx 作为普通响应回到本模块），
  这样才能记录跳转链、限制 `max_redirects`、并用 `urljoin` 解析相对 `Location`。
* 请求头带 `Accept-Encoding: identity`：标准库不会解压，若允许压缩会存下一堆二进制。
* 体积上限在传输层读取时即生效（先看 `Content-Length`，随后最多读 `max_bytes + 1`），
  超限直接失败，而不是落半截正文。

重试
----
* `retries` 表示**额外**重试次数（与 `FieldTheoryAdapter` 一致）：总尝试 = `1 + retries`。
* 只重试「可能瞬时」的错误：连接失败 / 超时 / 408 / 425 / 429 / 5xx；
  其余 4xx（含 404）立即失败，不浪费请求。
* 退避时间 = `backoff_seconds * 第几次尝试`（与上游适配器同一公式）。
"""

from __future__ import annotations

import codecs
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from .netguard import HostResolver, check_url_allowed, system_host_resolver

__all__ = [
    "ALLOWED_SCHEMES",
    "BlockedTargetError",
    "DEFAULT_ACCEPT",
    "REDIRECT_STATUSES",
    "RETRYABLE_STATUSES",
    "DecodedText",
    "FetchError",
    "FetchedPage",
    "HttpFetcher",
    "HttpStatusError",
    "PageTooLargeError",
    "RetryableFetchError",
    "TooManyRedirectsError",
    "TransportFailure",
    "TransportResponse",
    "TransportTimeoutError",
    "UnsupportedSchemeError",
    "UrllibTransport",
    "decode_body",
    "detect_bom_encoding",
]

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")
DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5"

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
RETRYABLE_STATUSES = frozenset({408, 425, 429})

_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9._\-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    rb"<meta[^>]{0,200}?charset\s*=\s*[\"']?\s*([A-Za-z0-9._\-]+)", re.IGNORECASE
)
_META_SNIFF_BYTES = 4096



# ── 错误 ─────────────────────────────────────────────────────────────────────


class FetchError(RuntimeError):
    """一次外链抓取失败。异常消息就是写进 `external_links.error_message` 的原因。"""

    retryable = False

    def __init__(self, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.attempts = max(1, int(attempts))


class RetryableFetchError(FetchError):
    """瞬时错误（连接失败 / 超时）：在 `retries` 范围内重试。"""

    retryable = True


class TransportFailure(RetryableFetchError):
    """连接层失败：DNS 解析失败、连接被拒、TLS 失败等。"""


class TransportTimeoutError(RetryableFetchError):
    """读取超时或连接超时。"""


class UnsupportedSchemeError(FetchError):
    """非 http(s) 链接（`mailto:` / `javascript:` / `ftp:` …）不抓取。"""


class BlockedTargetError(FetchError):
    """目标被安全策略拒绝（非公网地址）。

    **不可重试**，也**不应计入抓取尝试**：调用方（`LinkResolver`）把它当作策略跳过
    （`SKIPPED` + 原因），与 `skip_domains` 同级。
    """


class PageTooLargeError(FetchError):
    """页面超过 `external.max_bytes`。"""


class TooManyRedirectsError(FetchError):
    """重定向次数超过 `external.max_redirects`（或重定向缺少 Location）。"""


class HttpStatusError(FetchError):
    """服务端返回非 2xx。4xx 默认不重试；408/425/429/5xx 重试。"""

    def __init__(
        self,
        status_code: int,
        url: str,
        *,
        attempts: int = 1,
        retryable: bool | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self.url = url
        self.retryable = (
            (self.status_code in RETRYABLE_STATUSES or self.status_code >= 500)
            if retryable is None
            else retryable
        )
        super().__init__(f"HTTP {self.status_code}", attempts=attempts)


# ── 数据结构 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """传输层的一次原始响应（未跟随重定向、未解码、未抽取）。"""

    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes = b""
    truncated: bool = False

    def header(self, name: str) -> str | None:
        """大小写无关地取响应头（缺失返回 None）。"""

        lowered = name.lower()
        for key, value in self.headers.items():
            if str(key).lower() == lowered:
                return str(value)
        return None


@dataclass(frozen=True, slots=True)
class DecodedText:
    """解码后的文本与最终采用的编码名。"""

    text: str
    encoding: str


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """一次成功的抓取结果（已跟随重定向，`body` 为原始字节）。"""

    url: str
    final_url: str
    status_code: int
    content_type: str | None
    content_length: int | None
    body: bytes
    redirects: tuple[str, ...] = ()
    attempts: int = 1

    def text(self) -> str:
        """按 `Content-Type` / BOM / `<meta charset>` 探测编码后解码正文。"""

        return decode_body(self.body, self.content_type).text


# ── 编码探测 ─────────────────────────────────────────────────────────────────


def detect_bom_encoding(body: bytes) -> str | None:
    """按 BOM 判断编码（无 BOM 返回 None）。"""

    for bom, encoding in _BOM_ENCODINGS:
        if body.startswith(bom):
            return encoding
    return None


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = _CHARSET_RE.search(content_type)
    return match.group(1) if match else None


def _charset_from_meta(body: bytes) -> str | None:
    match = _META_CHARSET_RE.search(body[:_META_SNIFF_BYTES])
    if not match:
        return None
    try:
        return match.group(1).decode("ascii", errors="strict")
    except UnicodeDecodeError:  # pragma: no cover - 正则只匹配 ASCII 字符集名
        return None


def _valid_encoding(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return codecs.lookup(str(name).strip()).name
    except (LookupError, ValueError):
        return None


def decode_body(body: bytes, content_type: str | None = None) -> DecodedText:
    """解码正文：响应头 charset → BOM → `<meta charset>` → UTF-8 → 替换式解码。

    顺序理由：HTTP 头的声明最权威，BOM 次之，`<meta charset>` 是 HTML 里的事实兜底。
    任何一步失败都不抛异常——正文宁可带替换字符，也不能让整条外链失败。
    """

    candidates = [
        _valid_encoding(_charset_from_content_type(content_type)),
        _valid_encoding(detect_bom_encoding(body)),
        _valid_encoding(_charset_from_meta(body)),
        "utf-8",
    ]
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return DecodedText(body.decode(encoding), encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return DecodedText(body.decode("utf-8", errors="replace"), "utf-8")


# ── 传输层 ───────────────────────────────────────────────────────────────────


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """不自动跟随重定向：3xx 作为普通响应交回 :class:`HttpFetcher` 逐跳处理。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - 覆写
        return None


def _build_opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )


class UrllibTransport:
    """默认传输层：标准库 `urllib`，单次请求，不跟随重定向。

    ``opener`` 可注入（测试用）；不注入时按需构建一个只读 opener。
    """

    def __init__(self, opener: object | None = None) -> None:
        self._opener = opener

    @property
    def opener(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            self._opener = _build_opener()
        return self._opener  # type: ignore[return-value]

    def __call__(
        self,
        url: str,
        *,
        timeout: float,
        max_bytes: int,
        user_agent: str,
    ) -> TransportResponse:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": user_agent,
                "Accept": DEFAULT_ACCEPT,
                "Accept-Encoding": "identity",
                "Accept-Language": "en,zh-CN;q=0.8,*;q=0.5",
            },
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return _read_response(
                    url=url,
                    status_code=int(getattr(response, "status", 0) or 0),
                    headers=getattr(response, "headers", None),
                    stream=response,
                    max_bytes=max_bytes,
                    final_url=str(getattr(response, "url", "") or url),
                )
        except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx 都走这里
            try:
                return _read_response(
                    url=url,
                    status_code=int(exc.code or 0),
                    headers=exc.headers,
                    stream=exc,
                    max_bytes=max_bytes,
                    final_url=str(getattr(exc, "url", "") or url),
                )
            finally:
                exc.close()
        except (socket.timeout, TimeoutError) as exc:
            raise TransportTimeoutError(f"timeout after {timeout:g}s") from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise TransportTimeoutError(f"timeout after {timeout:g}s") from exc
            raise TransportFailure(f"connection failed: {reason}") from exc
        except ssl.SSLError as exc:
            raise TransportFailure(f"TLS error: {exc}") from exc
        except OSError as exc:
            raise TransportFailure(f"connection failed: {exc}") from exc


def _read_response(
    *,
    url: str,
    status_code: int,
    headers: object,
    stream: object,
    max_bytes: int,
    final_url: str,
) -> TransportResponse:
    """把 urllib 的响应对象读成 :class:`TransportResponse`（受 `max_bytes` 限制）。"""

    header_map = _headers_to_dict(headers)
    declared = _content_length(header_map)
    if declared is not None and declared > max_bytes:
        # 已知超限：不读正文，直接让上层判失败（省流量）。
        return TransportResponse(
            url=final_url or url,
            status_code=status_code,
            headers=header_map,
            body=b"",
            truncated=True,
        )
    body = stream.read(max_bytes + 1)  # type: ignore[attr-defined]
    truncated = len(body) > max_bytes
    return TransportResponse(
        url=final_url or url,
        status_code=status_code,
        headers=header_map,
        body=body[:max_bytes] if truncated else body,
        truncated=truncated,
    )


def _headers_to_dict(headers: object) -> dict[str, str]:
    if isinstance(headers, Message):
        return {str(key): str(value) for key, value in headers.items()}
    if isinstance(headers, Mapping):
        return {str(key): str(value) for key, value in headers.items()}
    return {}


def _content_length(headers: Mapping[str, str]) -> int | None:
    for key, value in headers.items():
        if str(key).lower() == "content-length":
            try:
                return int(str(value).strip())
            except ValueError:
                return None
    return None


# ── 抓取器 ───────────────────────────────────────────────────────────────────


class HttpFetcher:
    """带超时、重试、退避、重定向与体积上限的抓取器（传输层可注入）。

    ``__call__(url) -> FetchedPage``；失败抛 :class:`FetchError` 的某个子类。
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        retries: int = 2,
        backoff_seconds: float = 3.0,
        max_bytes: int = 5 * 1024 * 1024,
        max_redirects: int = 5,
        user_agent: str = "Mozilla/5.0 (compatible; XBookmarkKnowledgePipeline)",
        block_non_public_hosts: bool = True,
        allow_hosts: Sequence[str] = (),
        host_resolver: HostResolver | None = None,
        transport: Callable[..., TransportResponse] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.retries = max(0, int(retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.max_redirects = max(0, int(max_redirects))
        self.user_agent = str(user_agent)
        self.block_non_public_hosts = bool(block_non_public_hosts)
        self.allow_hosts: tuple[str, ...] = tuple(str(item) for item in allow_hosts)
        self._resolve_host: HostResolver = host_resolver or system_host_resolver
        self._transport: Callable[..., TransportResponse] = (
            transport if transport is not None else UrllibTransport()
        )
        self._sleep = sleeper

    def __call__(self, url: str) -> FetchedPage:
        scheme = urlsplit(str(url)).scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise UnsupportedSchemeError(f"unsupported scheme: {scheme or '(none)'}")

        redirects: list[str] = []
        current = str(url)
        attempts_total = 0
        for _hop in range(self.max_redirects + 1):
            self._guard(current)
            response, attempts = self._attempt(current)
            attempts_total += attempts
            if response.status_code in REDIRECT_STATUSES:
                location = response.header("location")
                if not location:
                    raise TooManyRedirectsError(
                        f"redirect without Location from {current}", attempts=attempts_total
                    )
                if len(redirects) >= self.max_redirects:
                    raise TooManyRedirectsError(
                        f"more than {self.max_redirects} redirects from {url}",
                        attempts=attempts_total,
                    )
                redirects.append(current)
                current = urljoin(current, location.strip())
                if urlsplit(current).scheme.lower() not in ALLOWED_SCHEMES:
                    raise UnsupportedSchemeError(
                        f"redirect to unsupported scheme: {current}", attempts=attempts_total
                    )
                logger.debug("redirect %s -> %s", redirects[-1], current)
                continue

            self._raise_for_failure(response, attempts=attempts_total)
            return FetchedPage(
                url=str(url),
                final_url=response.url or current,
                status_code=response.status_code,
                content_type=response.header("content-type"),
                content_length=_content_length(response.headers),
                body=response.body,
                redirects=tuple(redirects),
                attempts=attempts_total,
            )

    def _guard(self, url: str) -> None:
        """抓取前的安全校验：非公网目标直接拒绝（初始请求与每一跳重定向都走这里）。

        DNS 解析失败属于传输层瞬时问题，转成 `TransportFailure` 交给重试逻辑。
        """

        if not self.block_non_public_hosts and not self.allow_hosts:
            return
        try:
            reason = check_url_allowed(
                url,
                resolver=self._resolve_host,
                allow_hosts=self.allow_hosts,
                block_non_public=self.block_non_public_hosts,
            )
        except socket.gaierror as exc:
            raise TransportFailure(f"cannot resolve host: {exc}") from exc
        if reason:
            raise BlockedTargetError(f"blocked target ({reason})")

    # ── 内部 ────────────────────────────────────────────────────────────────

    def _attempt(self, url: str) -> tuple[TransportResponse, int]:
        """在 `1 + retries` 次内取回一次响应；瞬时错误按退避后重试。"""

        max_attempts = 1 + self.retries
        last_transport_error: RetryableFetchError | None = None
        last_status: int | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._transport(
                    url,
                    timeout=self.timeout_seconds,
                    max_bytes=self.max_bytes,
                    user_agent=self.user_agent,
                )
            except RetryableFetchError as exc:
                last_transport_error = exc
                last_status = None
            else:
                if response.status_code in RETRYABLE_STATUSES or response.status_code >= 500:
                    last_status = response.status_code
                    last_transport_error = None
                else:
                    return response, attempt

            if attempt < max_attempts:
                delay = self.backoff_seconds * attempt
                logger.debug(
                    "retrying %s (%d/%d attempts), sleeping %.1fs",
                    url,
                    attempt,
                    max_attempts,
                    delay,
                )
                if delay > 0:
                    self._sleep(delay)

        if last_transport_error is not None:
            raise type(last_transport_error)(
                str(last_transport_error), attempts=max_attempts
            )
        assert last_status is not None  # 进入重试分支必然二选一
        raise HttpStatusError(last_status, url, attempts=max_attempts, retryable=True)

    def _raise_for_failure(self, response: TransportResponse, *, attempts: int) -> None:
        if response.truncated:
            raise PageTooLargeError(
                f"page exceeds external.max_bytes ({self.max_bytes} bytes)",
                attempts=attempts,
            )
        if 200 <= response.status_code < 300:
            return
        raise HttpStatusError(
            response.status_code, response.url, attempts=attempts, retryable=False
        )
