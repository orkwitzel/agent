# SPDX-License-Identifier: GPL-3.0-or-later
"""The two bases every data class inherits from.

Both are frozen and strict: values are never coerced to another type, and
changing one means `model_copy(update=...)`. They differ in what happens to
fields they don't declare.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Our own data, such as events and store records. Unknown fields are an error."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class WireModel(BaseModel):
    """Data from a protocol we don't own. Unknown fields are ignored.

    The CLIs we drive add fields often; ignoring them keeps us working,
    while a missing or mistyped field still fails validation.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")
