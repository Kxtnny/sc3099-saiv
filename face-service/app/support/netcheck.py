import re
from typing import Optional, Tuple
from app.config import Config

_VPN_PATTERNS = [
    re.compile(r"\bvpn\b"), re.compile(r"\bproxy\b"),
    re.compile(r"\btunnel\b"), re.compile(r"\btor\b"),
    re.compile(r"\banonymizer\b"),
]

def detect_vpn_or_proxy(ip_address: Optional[str], user_agent: Optional[str]) -> Tuple[bool, float]:
    confidence = 0.0
    if user_agent:
        lowered = user_agent.lower()
        if any(pattern.search(lowered) for pattern in _VPN_PATTERNS):
            confidence = max(confidence, Config.NETWORK_KEYWORD_RISK)
    return confidence > 0, confidence