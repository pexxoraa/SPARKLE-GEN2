"""Stable domain/application error vocabulary."""
class SparkleError(Exception):
    """Base error for expected SPARKLE failures."""
class ValidationError(SparkleError): pass
class AuthorizationError(SparkleError): pass
class NotFoundError(SparkleError): pass
class CapabilityUnavailableError(SparkleError): pass
