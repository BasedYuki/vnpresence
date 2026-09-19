"""The artwork script must never eat the project's real icons.

This has bitten once already: a regenerate quietly replaced the app icon that
had just been set by hand. These tests run the script against a throwaway
assets folder whose files have known contents, and assert byte-for-byte that
the protected ones came out untouched.
"""

from __future__ import annotations

import pytest

from tools import make_icon

PROTECTED = ("icon.ico", "icon-256.png", "icon.png")
MARKER = b"this is the project's own artwork, not generated"


@pytest.fixture()
def assets(tmp_path, monkeypatch):
    """A fake assets/ folder holding recognisable 'hand-made' files."""
    folder = tmp_path / "assets"
    folder.mkdir()
    for name in PROTECTED:
        (folder / name).write_bytes(MARKER + name.encode())
    monkeypatch.setattr(make_icon, "OUT", folder)
    return folder


def untouched(folder) -> bool:
    return all((folder / n).read_bytes() == MARKER + n.encode() for n in PROTECTED)


def test_a_plain_run_touches_none_of_them(assets, capsys):
    make_icon.main([])
    assert untouched(assets), "the script overwrote a file it does not own"
    assert (assets / "icon-source.png").exists()  # it wrote its own name instead
    assert "left alone" in capsys.readouterr().out


def test_the_ico_flag_still_spares_the_app_icon(assets):
    make_icon.main(["--ico"])
    assert untouched(assets)
    assert (assets / "icon-generated.ico").exists()


def test_force_is_the_only_way_to_replace_them(assets):
    make_icon.main(["--force"])
    assert not untouched(assets), "--force should regenerate the real artwork"
    for name in PROTECTED:
        assert (assets / name).stat().st_size > 0


def test_the_protected_list_covers_everything_the_project_ships():
    # A new shipped asset must be added to PROTECTED, or this fails.
    assert set(make_icon.PROTECTED) == set(PROTECTED)


def test_the_guard_itself():
    assert make_icon._guard("icon.ico", force=False) is False
    assert make_icon._guard("icon-256.png", force=False) is False
    assert make_icon._guard("icon.png", force=False) is False
    assert make_icon._guard("icon-source.png", force=False) is True
    assert make_icon._guard("icon.ico", force=True) is True
