"""The see-through look: the three modes, how much shows through, and the fallback from frosted to dim to solid (no Qt)."""
import pytest

from dossier.core import glass
from dossier.core.glass import Capabilities, DIM, FROSTED, SOLID

FULL = Capabilities(transparent=True, blur=True)
NO_BLUR = Capabilities(transparent=True, blur=False)
NOTHING = Capabilities(transparent=False, blur=False)


def test_each_look_falls_back_one_step_at_a_time_to_what_the_computer_can_do():
    assert [glass.resolve(FROSTED, c) for c in (FULL, NO_BLUR, NOTHING)] == [FROSTED, DIM, SOLID]
    assert [glass.resolve(DIM, c) for c in (FULL, NO_BLUR, NOTHING)] == [DIM, DIM, SOLID]
    assert [glass.resolve(SOLID, c) for c in (FULL, NO_BLUR, NOTHING)] == [SOLID, SOLID, SOLID]
    assert glass.resolve("nonsense", FULL) == FROSTED                    # an unknown name gets the default look


def test_the_computer_is_asked_and_a_remote_session_gets_solid(monkeypatch):
    from dossier.core import platform
    monkeypatch.setattr(platform, "is_remote_session", lambda: True)
    assert glass.detect() == Capabilities(False, False)
    monkeypatch.setattr(platform, "is_remote_session", lambda: False)
    assert glass.detect().transparent is True and glass.detect().blur is platform.IS_WINDOWS


def test_what_the_owner_types_is_understood():
    assert glass.parse("frosted") == (FROSTED, None) and glass.parse("DIM") == (DIM, None) and glass.parse("solid") == (SOLID, None)
    assert glass.parse("60") == (None, 60) and glass.parse("frosted:60") == (FROSTED, 60) and glass.parse("dim, 30") == (DIM, 30)
    assert glass.parse("0") == (SOLID, 0) and glass.parse("frosted:0") == (SOLID, 0)         # 0 shows nothing through: solid
    assert glass.parse("250") == (None, 100)
    for bad in ("glassy", "frosted:blur", "-5"):
        with pytest.raises(ValueError, match="not a glass setting"):
            glass.parse(bad)


def test_how_much_shows_through_and_the_opacity_of_the_dark_layer():
    assert glass.level_for(FROSTED, None) == 65 and glass.level_for(DIM, None) == 28 and glass.level_for(SOLID, 70) == 0
    assert glass.level_for(FROSTED, 100) == glass.MAX_LEVEL and glass.level_for(DIM, 0) == 1      # never fully clear
    assert glass.alpha_for(SOLID) == 255
    assert glass.alpha_for(FROSTED) == round(255 * 0.35) and glass.alpha_for(DIM) == round(255 * 0.72)
    assert glass.alpha_for(DIM, 60) == round(255 * 0.4)
