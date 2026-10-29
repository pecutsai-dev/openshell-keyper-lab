"""The complete mutation supported by this milestone, with strict input bounds."""

from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import re


class ApprovalError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NetworkChange:
    sandbox_id: str
    domain: str
    port: int
    operation: str = "network.allow"
    protocol: str = "tcp"

    def __post_init__(self):
        if not isinstance(self.sandbox_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.sandbox_id
        ):
            raise ValueError("sandbox_id must be a 1-128 character identifier")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        if not isinstance(self.domain, str) or not self.domain.isascii():
            raise ValueError("domain must be an ASCII DNS name; use punycode for IDNs")
        domain = self.domain.lower()
        if domain.endswith("."):
            domain = domain[:-1]
        if len(domain) > 253 or "." not in domain or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in domain.split(".")
        ):
            raise ValueError("domain must be a DNS name without URLs, paths or wildcards")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError("IP address rules are outside this milestone")
        if self.operation != "network.allow" or self.protocol != "tcp":
            raise ValueError("Only network.allow over tcp is supported")
        object.__setattr__(self, "domain", domain)

    @property
    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()
