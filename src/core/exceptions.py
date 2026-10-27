"""Document service failures; HTTP presentation belongs to the API layer."""


class DocumentError(Exception):
    """Base for safe, explicitly handled document operation failures."""


class InvalidDocument(DocumentError):
    """Missing or invalid file metadata."""


class UnsupportedDocument(DocumentError):
    """File does not meet the initial PDF acceptance checks."""


class UploadTooLarge(DocumentError):
    """File or multipart request exceeds its configured bound."""


class DocumentNotFound(DocumentError):
    """Missing document or one the caller is not permitted to inspect."""


class DocumentStorageError(DocumentError):
    """A backing store failed; never expose its raw exception to a caller."""


class AuthError(Exception):
    """Authentication service error with fixed, safe API presentation."""


class AuthRejected(AuthError):
    """Invalid credentials, revoked session, or invalid refresh token."""


class AccountConflict(AuthError):
    """An account cannot be registered with the supplied identifier."""


class AuthUnavailable(AuthError):
    """Authentication persistence is unavailable; fail closed."""


class AuthRateLimited(AuthError):
    """Authentication request budget exhausted."""


class AuthForbidden(AuthError):
    """The authenticated user lacks an active membership or required role."""


class WorkspaceRequired(AuthError):
    """An account session must select a workspace before accessing tenant data."""


class InvitationRejected(AuthError):
    """Invitation is expired, consumed, or does not match the authenticated email."""
