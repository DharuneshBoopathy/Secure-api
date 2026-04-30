"""Parse PCAP files (Wireshark / tshark exports) for HTTP-like TCP payloads."""

import io
import re
from typing import Iterator

import dpkt

_REQUEST_LINE = re.compile(rb"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s+HTTP/\d")


def iter_http_requests_from_pcap(data: bytes) -> Iterator[tuple[str, str]]:
    """Yield (method, path) pairs from cleartext HTTP request lines in PCAP."""
    try:
        r = dpkt.pcap.Reader(io.BytesIO(data))
    except Exception:
        return
    for _ts, buf in r:
        try:
            eth = dpkt.ethernet.Ethernet(buf)
        except Exception:  # nosec B112
            continue
        ip = eth.data
        if not isinstance(ip, dpkt.ip.IP):
            continue
        if not isinstance(ip.data, dpkt.tcp.TCP):
            continue
        payload = ip.data.data
        if not payload or len(payload) < 10:
            continue
        m = _REQUEST_LINE.match(payload.split(b"\r\n", 1)[0])
        if not m:
            continue
        method = m.group(1).decode("ascii", errors="ignore")
        uri = m.group(2).decode("utf-8", errors="replace")
        path = uri.split("?", 1)[0]
        if path:
            yield method, path
