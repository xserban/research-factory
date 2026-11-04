"""Errors raised by external-tool converters. Messages never contain document text."""

from factory.errors import FactoryError


class ConversionToolError(FactoryError):
    """An external conversion tool failed (timeout, non-zero exit, undecodable output).

    The message names the failure class only; tool stderr and document text are never included.
    """
