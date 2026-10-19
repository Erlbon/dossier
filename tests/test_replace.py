import pytest

from dossier.core.progress import Cancelled, CancelToken
from dossier.core.replace import (FindSpec, PatternError, compile_spec, count, find_all, find_next, preview,
                                  replace_all, replace_one)

TEXT = "Alpha beta\nbeta Gamma\nalphabet beta\n"


# plain text ------------------------------------------------------------------------------------------
def test_plain_search_is_literal_and_case_insensitive_by_default():
    assert find_all(TEXT, FindSpec("beta")) == [(6, 10), (11, 15), (31, 35)]
    assert count(TEXT, FindSpec("a.b")) == 0                           # the dot is just a dot
    assert count("a.b a-b", FindSpec("a.b")) == 1


def test_match_case_and_whole_word():
    assert count(TEXT, FindSpec("beta", case=True)) == 3
    assert count(TEXT, FindSpec("Beta", case=True)) == 0
    assert count(TEXT, FindSpec("alpha", whole_word=True)) == 1        # not the one inside "alphabet"
    assert count(TEXT, FindSpec("beta", whole_word=True)) == 3


def test_plain_replacement_is_literal_even_with_backslashes_and_ampersands():
    new, n = replace_all("a b a", FindSpec("a"), "\\1 & \\n")
    assert n == 2 and new == "\\1 & \\n b \\1 & \\n"


def test_replace_all_counts_and_keeps_the_rest():
    new, n = replace_all(TEXT, FindSpec("beta", whole_word=True), "BETA")
    assert n == 3 and new == "Alpha BETA\nBETA Gamma\nalphabet BETA\n"
    assert replace_all(TEXT, FindSpec("zzz"), "x") == (TEXT, 0)


# regex -------------------------------------------------------------------------------------------------
def test_regex_groups_and_escapes_in_the_replacement():
    new, n = replace_all("2024-10-19 and 2025-01-02", FindSpec(r"(\d{4})-(\d\d)-(\d\d)", regex=True), r"\3.\2.\1")
    assert n == 2 and new == "19.10.2024 and 02.01.2025"
    new, n = replace_all("a,b", FindSpec(",", regex=True), r"\n")
    assert new == "a\nb"
    new, n = replace_all("a b", FindSpec(" ", regex=True), r"\t")
    assert new == "a\tb"


def test_named_groups_and_anchors_work_line_by_line():
    spec = FindSpec(r"^(?P<word>\w+)", regex=True)
    new, n = replace_all("one two\nthree four\n", spec, r"[\g<word>]")
    assert new == "[one] two\n[three] four\n" and n == 2


def test_dot_all_lets_a_pattern_cross_lines():
    assert count("a\nb", FindSpec("a.b", regex=True)) == 0
    assert count("a\nb", FindSpec("a.b", regex=True, dot_all=True)) == 1


def test_regex_with_whole_word_and_match_case():
    assert count("Cat cat concat", FindSpec("cat", regex=True, whole_word=True)) == 2
    assert count("Cat cat concat", FindSpec("cat", regex=True, whole_word=True, case=True)) == 1


def test_empty_matches_never_insert_text_everywhere():
    new, n = replace_all("abc", FindSpec("x*", regex=True), "-")
    assert (new, n) == ("abc", 0)


# errors the user can read ----------------------------------------------------------------------------------
def test_bad_patterns_say_what_and_where():
    with pytest.raises(PatternError, match="regular expression"):
        compile_spec(FindSpec("(unclosed", regex=True))
    with pytest.raises(PatternError, match="Enter something"):
        compile_spec(FindSpec(""))
    assert count("(unclosed", FindSpec("(unclosed")) == 1              # the same text is fine as plain search


def test_bad_replacements_are_refused_before_anything_changes():
    with pytest.raises(PatternError, match="replacement"):
        replace_all("abc", FindSpec("b", regex=True), r"\g<nope>")
    with pytest.raises(PatternError, match="replacement"):
        replace_all("abc", FindSpec("b", regex=True), r"\9")
    with pytest.raises(PatternError, match="replacement"):
        replace_all("abc", FindSpec("(b)", regex=True), r"\q")


# stepping -------------------------------------------------------------------------------------------------------
def test_find_next_wraps_and_find_previous_wraps():
    spec = FindSpec("beta")
    assert find_next(TEXT, spec, 0) == (6, 10)
    assert find_next(TEXT, spec, 7) == (11, 15)
    assert find_next(TEXT, spec, 33) == (6, 10)                          # wrapped to the first
    assert find_next(TEXT, spec, 33, wrap=False) is None
    assert find_next(TEXT, spec, 11, forward=False) == (6, 10)
    assert find_next(TEXT, spec, 6, forward=False) == (31, 35)           # wrapped to the last
    assert find_next(TEXT, spec, 6, forward=False, wrap=False) is None


def test_replace_one_changes_only_the_first_match_after_the_cursor():
    new, begin, after = replace_one("x a x a", FindSpec("a"), "LONGER", start=3)
    assert new == "x a x LONGER" and begin == 6 and after == 12
    assert replace_one("abc", FindSpec("z"), "y") is None


def test_replace_inside_a_selection_only():
    new, n = replace_all("a a a a", FindSpec("a"), "b", region=(2, 5))
    assert new == "a b b a" and n == 2


def test_preview_lists_line_numbers_and_results():
    rows = preview(TEXT, FindSpec(r"(\w)eta", regex=True), r"<\1>", limit=2)
    assert rows == [(1, "beta", "<b>"), (2, "beta", "<b>")]


def test_a_long_replace_can_be_cancelled():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        replace_all("a " * 5000, FindSpec("a"), "b", cancel=token)


def test_unicode_and_case_insensitive_matching():
    assert count("ÆØÅ æøå", FindSpec("æøå")) == 2
    new, n = replace_all("Straße STRASSE", FindSpec("straße"), "x")
    assert n == 1
