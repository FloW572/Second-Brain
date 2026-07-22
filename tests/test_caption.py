"""Tests for the file-caption parser: whole caption = note, optional #Projekt = project."""
from app.documents import parse_caption


def test_empty_caption():
    assert parse_caption(None) == (None, None)
    assert parse_caption("") == (None, None)
    assert parse_caption("   ") == (None, None)


def test_note_only():
    assert parse_caption("Sonnenuntergang am Gardasee") == (None, "Sonnenuntergang am Gardasee")


def test_note_with_hashtag_project():
    assert parse_caption("Sonnenuntergang am Gardasee #Urlaub") == ("Urlaub", "Sonnenuntergang am Gardasee")


def test_hashtag_in_the_middle_is_removed_from_note():
    assert parse_caption("War toll #Urlaub hier") == ("Urlaub", "War toll hier")


def test_hashtag_only():
    assert parse_caption("#Finanzen") == ("Finanzen", None)


def test_umlauts_and_hyphen_in_project():
    assert parse_caption("Bergtour #Südtirol-2026") == ("Südtirol-2026", "Bergtour")


def test_first_hashtag_wins_second_stays_in_note():
    project, note = parse_caption("Notiz #Urlaub und #Strand")
    assert project == "Urlaub"
    assert note == "Notiz und #Strand"
