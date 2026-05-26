"""iBackupX package."""

__version__ = "1.0.0"


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""


class BackupError(Exception):
    """Raised when backup discovery or access fails."""


class ExtractionError(Exception):
    """Raised when extraction fails."""


__all__ = ["__version__", "ConfigError", "BackupError", "ExtractionError"]
