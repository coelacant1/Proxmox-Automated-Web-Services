"""Input validation and sanitization utilities - whitelist approach."""

import ipaddress
import re
from urllib.parse import urlparse

# --- Hostname / Subdomain ---

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$")
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$")


def validate_hostname(value: str) -> str:
    """Validate a hostname label (no dots, 1-63 chars, alphanumeric + hyphens)."""
    value = value.strip()
    if not value or len(value) > 63:
        raise ValueError("Hostname must be 1-63 characters")
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Hostname must start/end with alphanumeric and contain only alphanumeric/hyphens")
    return value


def validate_subdomain(value: str) -> str:
    """Validate a subdomain (dot-separated labels, lowercase)."""
    value = value.strip().lower()
    if not value or len(value) > 253:
        raise ValueError("Subdomain must be 1-253 characters")
    if not _SUBDOMAIN_RE.match(value):
        raise ValueError("Invalid subdomain format")
    return value


# --- Network ---


def validate_cidr(value: str) -> str:
    """Validate a CIDR notation (e.g. 10.0.0.0/16)."""
    try:
        network = ipaddress.ip_network(value, strict=False)
        return str(network)
    except ValueError:
        raise ValueError(f"Invalid CIDR: {value}")


def validate_port(value: int) -> int:
    """Validate a network port number (1-65535)."""
    if not isinstance(value, int) or value < 1 or value > 65535:
        raise ValueError(f"Port must be 1-65535, got {value}")
    return value


def validate_ip_address(value: str) -> str:
    """Validate an IP address (v4 or v6)."""
    try:
        addr = ipaddress.ip_address(value)
        return str(addr)
    except ValueError:
        raise ValueError(f"Invalid IP address: {value}")


# --- Proxmox-specific ---

_NODE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,49}$")


def validate_vmid(value: int) -> int:
    """Validate a Proxmox VMID (100-999999999)."""
    if not isinstance(value, int) or value < 100 or value > 999999999:
        raise ValueError(f"VMID must be 100-999999999, got {value}")
    return value


def validate_node_name(value: str) -> str:
    """Validate a Proxmox node name."""
    value = value.strip()
    if not _NODE_NAME_RE.match(value):
        raise ValueError("Node name must be alphanumeric + hyphens, start with alphanumeric, max 50 chars")
    return value


# --- Webhook / URL ---

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def validate_webhook_url(url: str, *, allow_http: bool = False) -> str:
    """Validate a webhook URL - blocks private IPs, requires HTTPS by default."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid URL format")
    if not allow_http and parsed.scheme != "https":
        raise ValueError("Webhook URLs must use HTTPS")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP/HTTPS schemes allowed")

    hostname = parsed.hostname or ""
    # Block obvious private hostnames
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("Webhook URL cannot target localhost")

    # Try to detect private IPs in hostname
    try:
        addr = ipaddress.ip_address(hostname)
        if is_private_ip(str(addr)):
            raise ValueError("Webhook URL cannot target private IP ranges")
    except ValueError as e:
        if "private" in str(e).lower() or "localhost" in str(e).lower():
            raise
        # hostname is a domain name, not an IP - that's fine

    return url


# --- General ---

_SAFE_TEXT_RE = re.compile(r"^[\w\s\-.,!?@#$%&*()+=\[\]{};:'\"/\\<>~`|^]+$", re.UNICODE)


def sanitize_display_name(value: str, max_length: int = 100) -> str:
    """Sanitize a display name: strip, limit length, reject control chars."""
    value = value.strip()
    if not value:
        raise ValueError("Display name cannot be empty")
    if len(value) > max_length:
        raise ValueError(f"Display name exceeds {max_length} characters")
    # Reject control characters
    if any(ord(c) < 32 and c not in ("\n", "\t") for c in value):
        raise ValueError("Display name contains invalid control characters")
    return value
