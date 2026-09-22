"""网络目标安全校验（Phase 9 复审修复）：拒绝非公网目标，并在每一跳重定向后复核。

威胁模型
--------
书签里的链接是**不可信输入**。若允许抓取 `localhost`、私网、链路本地或云元数据地址
（`169.254.169.254`），恶意书签就能让本项目读取内部服务（如本地 admin 接口、云实例
凭据端点）并把内容写进知识库，违反 `AGENTS.md` 第 6 节"敏感信息不得进入 Markdown 产物"。

做法
----
* 只对 `http(s)` 生效（其余 scheme 由 :mod:`src.external.fetcher` 判为不支持）；
* 主机名先解析为 IP，**任一**解析结果落在非公网段即拒绝 —— 这样也覆盖"域名解析到内网"
  以及 IPv4-mapped IPv6（`::ffff:127.0.0.1`）这类写法；
* 解析器（`resolver`）可注入，测试无需真实 DNS；
* 显式白名单 `external.allow_hosts` 可放行（例如本机自建服务）；支持 `example.com` 与
  `.example.com` / `*.example.com`（后者等价于"含子域"）；
* 调用方（fetcher）在**初始请求前**与**每一次重定向跳转后**都调用本模块，避免
  "首跳公网、次跳内网"的绕过。

明确不做：不解析页面内的子资源、不代理、不做 egress 防火墙 —— 只保证"本项目不去读非公网目标"。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

__all__ = [
    "BLOCKED_NETWORKS",
    "HostResolver",
    "check_url_allowed",
    "host_matches_allowlist",
    "is_public_address",
    "system_host_resolver",
]

logger = logging.getLogger(__name__)

#: 非公网网段：RFC1918 私网、CGNAT、链路本地（含云元数据）、回环、保留/文档/基准测试段、
#: 多播与未指定地址，以及 IPv6 的等价集合。
BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(item)
    for item in (
        "0.0.0.0/8",  # "this network"
        "10.0.0.0/8",  # RFC1918
        "100.64.0.0/10",  # CGNAT (RFC6598)
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local：AWS/GCP/Azure 元数据端点在此
        "172.16.0.0/12",  # RFC1918
        "192.0.0.0/24",  # IETF protocol assignments
        "192.0.2.0/24",  # TEST-NET-1
        "192.168.0.0/16",  # RFC1918
        "198.18.0.0/15",  # benchmarking
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved
        "::/128",  # unspecified
        "::1/128",  # loopback
        "64:ff9b::/96",  # NAT64
        "100::/64",  # discard-only
        "2001:db8::/32",  # documentation
        "fc00::/7",  # unique local
        "fe80::/10",  # link-local
        "ff00::/8",  # multicast
    )
)

#: 把主机名解析为 IP 字符串序列；失败时允许抛 `socket.gaierror`（调用方转成传输失败）。
HostResolver = Callable[[str], Sequence[str]]


def system_host_resolver(host: str) -> Sequence[str]:
    """用系统解析器把主机名解析为去重的 IP 字符串序列。"""

    infos = socket.getaddrinfo(str(host), None, proto=socket.IPPROTO_TCP)
    return tuple(sorted({str(info[4][0]) for info in infos}))


def is_public_address(address: str) -> bool:
    """该 IP 是否属于"可以抓取的公网地址"。无法解析为 IP 时按不安全处理。"""

    try:
        parsed = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return not any(parsed in network for network in BLOCKED_NETWORKS)


def host_matches_allowlist(host: str, allow_hosts: Iterable[str]) -> bool:
    """主机是否命中白名单（精确匹配，或 `<entry>` 的后缀子域匹配）。"""

    candidate = str(host or "").strip().lower().rstrip(".")
    if not candidate:
        return False
    for entry in allow_hosts:
        allowed = str(entry or "").strip().lower().lstrip("*.").lstrip(".").rstrip(".")
        if not allowed:
            continue
        if candidate == allowed or candidate.endswith("." + allowed):
            return True
    return False


def check_url_allowed(
    url: str,
    *,
    resolver: HostResolver = system_host_resolver,
    allow_hosts: Iterable[str] = (),
    block_non_public: bool = True,
) -> str | None:
    """校验目标是否可抓取：返回**阻断原因**；允许时返回 `None`。

    解析失败（`socket.gaierror`）不在这里吞掉：那属于传输层瞬时失败，由 fetcher 转成
    `TransportFailure` 参与重试。
    """

    parts = urlsplit(str(url))
    host = str(parts.hostname or "").strip()
    if not host:
        return "url has no host"
    if host_matches_allowlist(host, allow_hosts):
        return None
    if not block_non_public:
        return None

    literal = _as_literal_address(host)
    if literal is not None:
        if is_public_address(literal):
            return None
        return f"non-public address {literal}"

    addresses = [str(item) for item in resolver(host)]
    if not addresses:
        return f"host {host} did not resolve to any address"
    blocked = [address for address in addresses if not is_public_address(address)]
    if blocked:
        return f"host {host} resolves to non-public address {', '.join(sorted(blocked))}"
    return None


def _as_literal_address(host: str) -> str | None:
    """主机本身就是 IP 字面量时返回其规范化形式，否则 `None`。"""

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None
