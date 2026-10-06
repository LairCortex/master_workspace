"""Local IPv4 addresses for the table-host URL list (design D4)."""
from __future__ import annotations

import socket


def _default_route_ipv4() -> str | None:
    """The LIVE LAN address: the source the kernel would pick for a real
    outbound connection (the UDP connect trick sends nothing, it only makes
    the routing table name the interface in use).  None with no usable route.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("1.1.1.1", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def local_ipv4_addresses() -> list[str]:
    found: list[str] = []

    def _add(ip: str) -> None:
        if ip and ip not in found:
            found.append(ip)

    # The active (default-route) address LEADS the list (user request
    # 2026-10-05): the desk encodes the FIRST address into its QR, and the
    # old order let a dead adapter's name lookup take the first place.  The
    # name/interface sources keep their order behind it; ``_add`` dedups a
    # repeat of the same address.
    default_route = _default_route_ipv4()
    if default_route:
        _add(default_route)
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
