import pytest

from ogoh.pipeline.normalize import canonicalize_url, url_hash


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # The same article as three feeds hand it over.
        ("https://www.example.com/post/", "https://example.com/post"),
        ("http://example.com/post", "https://example.com/post"),
        ("https://example.com/post?utm_source=feedly&utm_medium=rss", "https://example.com/post"),
        ("https://example.com/post#section-2", "https://example.com/post"),
        ("https://example.com/post?fbclid=abc123", "https://example.com/post"),
        # Query order is not identity.
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ],
)
def test_canonicalize_collapses_noise(left, right):
    assert canonicalize_url(left) == canonicalize_url(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Meaningful query params must survive — some sites paginate on them.
        ("https://example.com/p?id=1", "https://example.com/p?id=2"),
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/p", "https://other.com/p"),
    ],
)
def test_canonicalize_keeps_real_differences(left, right):
    assert canonicalize_url(left) != canonicalize_url(right)


def test_hash_is_stable_and_distinct():
    assert url_hash(canonicalize_url("https://example.com/p")) == url_hash("https://example.com/p")
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")
