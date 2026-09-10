import ipaddress
from typing import Optional, Tuple

from app.config import Config

_VPN_KEYWORDS = ("vpn", "proxy", "tunnel", "tor", "anonymizer")


def _is_private(ip_string: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_string)
    except ValueError:
        return False
    if addr.is_loopback:
        return False
    return addr.is_private or addr.is_link_local


def _user_agent_mentions_vpn(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(kw in lowered for kw in _VPN_KEYWORDS)


def detect_vpn_or_proxy(
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> Tuple[bool, float]:
    confidence = 0.0
    flagged = False

    if ip_address and _is_private(ip_address):
        flagged = True
        confidence = max(confidence, Config.NETWORK_PRIVATE_IP_RISK)

    if user_agent and _user_agent_mentions_vpn(user_agent):
        flagged = True
        confidence = max(confidence, Config.NETWORK_KEYWORD_RISK)

    return flagged, confidence