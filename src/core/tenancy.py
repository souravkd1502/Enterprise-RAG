"""Explicit tenant identity passed from verified authentication into services."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Immutable identity, not a permission grant or a substitute for ACL checks.

    Construct only from verified JWT claims or validated persisted job ownership.
    Identifiers are opaque, case-sensitive strings and are never normalized.
    """

    tenant_id: str
    user_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.user_id):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 256
                or any(
                    character.isspace() or not character.isprintable()
                    for character in value
                )
            ):
                raise ValueError(
                    "Identity claims must be nonempty strings of up to 256 visible characters"
                )
