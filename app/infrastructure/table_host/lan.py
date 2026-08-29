"""Local IPv4 addresses for the table-host URL list (design D4)."""
from __future__ import annotations

import socket


def local_ipv4_addresses() -> list[str]:
    found: list[str] = []

    def _add(ip: str) -> None:
        if ip and ip not in found:
            found.append(ip)

    try:
        hostname = socket.gethostname()
        try:
            _name, _aliases, ips = socket.gethostbyname_ex(hostname)
            for ip in ips:
                _add(ip)
        except OSError:
            pass
        try:
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                _add(info[4][0])
        except OSError:
            pass
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("1.1.1.1", 80))
            _add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for _idx, name in socket.if_nameindex():
            try:
                for info in socket.getaddrinfo(
                    name, None, socket.AF_INET, socket.SOCK_DGRAM
                ):
                    _add(info[4][0])
            except OSError:
                continue
    except (OSError, AttributeError):
        pass
    return found
