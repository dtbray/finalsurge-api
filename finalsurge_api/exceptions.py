class FinalSurgeError(Exception):
    """Base error for this package."""


class AuthenticationError(FinalSurgeError):
    """Final Surge did not establish an authenticated session."""


class WriteProtectionError(FinalSurgeError):
    """A caller attempted a write without explicitly enabling it."""
