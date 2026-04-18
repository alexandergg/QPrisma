from __future__ import annotations

from enum import Enum

import pytest

from evaluation_foundry.redteam_eval import _map_enum_member


class LowercaseStrategy(Enum):
    base64 = "base64"
    flip = "flip"
    morse = "morse"


class UppercaseRisk(Enum):
    VIOLENCE = "violence"
    SELF_HARM = "self_harm"


@pytest.mark.parametrize(
    ("enum_cls", "token", "expected"),
    [
        (LowercaseStrategy, "base64", LowercaseStrategy.base64),
        (LowercaseStrategy, "BASE64", LowercaseStrategy.base64),
        (LowercaseStrategy, " flip ", LowercaseStrategy.flip),
        (UppercaseRisk, "violence", UppercaseRisk.VIOLENCE),
        (UppercaseRisk, "SELF_HARM", UppercaseRisk.SELF_HARM),
    ],
)
def test_map_enum_member_accepts_case_insensitive_names_and_values(
    enum_cls: type[Enum], token: str, expected: Enum
):
    assert _map_enum_member(enum_cls, token) is expected


def test_map_enum_member_lists_valid_values_on_unknown_token():
    with pytest.raises(ValueError, match="Valid values: base64, flip, morse"):
        _map_enum_member(LowercaseStrategy, "unknown")
