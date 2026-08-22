"""Tests for plain HTTP GET fetch, visible-text extraction and degraded-fetch detection.
httpx.get is mocked throughout -- this suite never makes a real HTTP request."""
from opportunity_tracker.fetcher.http_fetch import FetchResult, extract_visible_text, fetch_http


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_fetch_http_normal_content_is_not_degraded(mocker):
    real_text = "Scholarship details and eligibility criteria. " * 10  # well over 200 chars
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(real_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/scholarships/rtp")

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    # Plain (non-markup) content survives extraction unchanged apart from edge whitespace.
    assert result.text == real_text.strip()
    assert result.is_degraded is False


def test_fetch_http_short_loading_body_is_degraded(mocker):
    short_text = "Loading component..."
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(short_text, 200),
    )

    result = fetch_http("https://uwa.edu.au/hdr-application")

    assert result.status_code == 200
    assert result.text == short_text
    assert result.is_degraded is True


# --- Whole-branch review I2: stored text is extracted visible text, never raw HTML --------

_PAGE = """<!DOCTYPE html>
<html>
  <head>
    <title>RTP Scholarship</title>
    <style>.nav { color: #fff; } .banner { background: url(x.png); }</style>
    <script>window.analytics = {id: "UA-1234"}; track("pageview");</script>
  </head>
  <body>
    <nav><a href="/study">Study</a> <a href="/research">Research</a></nav>
    <h1>Research Training Program Scholarship</h1>
    <p>Applications close 15 March 2027.</p>
    <p>The research project component must constitute at least 25 percent of a full time
       equivalent annual enrolment.</p>
  </body>
</html>"""


def test_fetch_http_returns_extracted_text_not_raw_html(mocker):
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(_PAGE, 200),
    )

    result = fetch_http("https://uwa.edu.au/scholarships/rtp", min_content_length=1)

    assert "<p>" not in result.text
    assert "<html" not in result.text
    assert "Applications close 15 March 2027." in result.text
    assert "at least 25 percent" in result.text


def test_extract_visible_text_drops_script_and_style_content():
    text = extract_visible_text(_PAGE)

    assert "window.analytics" not in text
    assert "track(" not in text
    assert "background: url" not in text
    assert "Research Training Program Scholarship" in text


def test_extract_visible_text_keeps_noscript_so_loading_markers_still_fire():
    # "Please enable JavaScript" almost always lives in <noscript>; stripping that tag
    # would silently disable the headless fallback for exactly the JS-rendered pages it
    # exists to handle.
    html = "<html><body><noscript>Please enable JavaScript to view this page.</noscript></body></html>"

    assert "Please enable JavaScript" in extract_visible_text(html)


def test_html_shell_with_no_visible_content_is_now_correctly_degraded(mocker):
    """The whole point of measuring length against extracted text: this shell is >200
    characters of raw markup (so it used to look healthy) but has almost no real content."""
    shell = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="/assets/app.2f9c1b.css">'
        '<script src="/assets/app.2f9c1b.js" defer></script>'
        '<script>window.__STATE__={"route":"/scholarships","hydrated":false};</script>'
        '</head><body><div id="root"></div></body></html>'
    )
    assert len(shell) > 200
    mocker.patch(
        "opportunity_tracker.fetcher.http_fetch.httpx.get",
        return_value=_FakeResponse(shell, 200),
    )

    result = fetch_http("https://uwa.edu.au/scholarships")

    assert result.is_degraded is True
