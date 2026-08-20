#!/usr/bin/env python3
"""Opaque token boundary for the stdlib-only release control scripts."""

from __future__ import annotations

import hmac
import os


class SecretToken:
    """Keep credential values out of ordinary string/logging paths."""

    __slots__ = ("__value",)

    def __init__(self, value: str):
        if type(value) is not str or not value:
            raise ValueError("secret token must be a non-empty string")
        self.__value = value

    @classmethod
    def from_env(cls, name: str) -> "SecretToken":
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"{name} is not set")
        return cls(value)

    def expose(self) -> str:
        """Return the inner value only at the Authorization-header use site."""

        return self.__value

    def matches(self, other: "SecretToken") -> bool:
        if not isinstance(other, SecretToken):
            return False
        return hmac.compare_digest(self.__value, other.__value)

    def __str__(self) -> str:
        return "[REDACTED]"

    def __repr__(self) -> str:
        return "SecretToken([REDACTED])"


def require_secret(value: object) -> SecretToken:
    if not isinstance(value, SecretToken):
        raise TypeError("credential boundary requires SecretToken")
    return value
