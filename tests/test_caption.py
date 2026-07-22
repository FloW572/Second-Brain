"""Tests for the file-caption parser: whole caption = note, optional #Projekt = project."""
from app.documents import extract_project_hashtag, parse_caption


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


def test_hashtag_with_space_after_hash():
    assert parse_caption("Bergtour # Südtirol") == ("Südtirol", "Bergtour")


def test_url_fragment_is_not_a_project():
    # '#' inside a URL (preceded by a letter) must not be taken as a project.
    assert parse_caption("Link example.com/p#section") == (None, "Link example.com/p#section")


# --- extract_project_hashtag (shared by text capture) ---

def test_extract_trailing_hashtag_with_space():
    assert extract_project_hashtag("Geld überweisen # Finanzen") == ("Finanzen", "Geld überweisen")


def test_extract_trailing_hashtag_no_space():
    assert extract_project_hashtag("Geld überweisen #Finanzen") == ("Finanzen", "Geld überweisen")


def test_extract_leading_hashtag():
    assert extract_project_hashtag("#Finanzen Geld überweisen") == ("Finanzen", "Geld überweisen")


def test_extract_no_hashtag():
    assert extract_project_hashtag("Geld überweisen") == (None, "Geld überweisen")


def test_extract_ignores_sharp_inside_word():
    # "C#" must not turn "lernen" into a project.
    assert extract_project_hashtag("C# lernen") == (None, "C# lernen")
