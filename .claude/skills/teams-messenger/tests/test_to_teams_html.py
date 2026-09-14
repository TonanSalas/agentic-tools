from to_teams_html import to_html


def test_html_passthrough():
    assert to_html("<b>Hi</b><br>x") == "<b>Hi</b><br>x"


def test_strips_html_wrapper_and_whitespace():
    assert to_html("  <html>\n<b>A</b>\n</html>\n") == "<b>A</b>"


def test_heading_and_bold():
    assert to_html("# Title\n**x** y") == "<b>Title</b><br>\n<p><b>x</b> y</p>"


def test_subheading():
    assert to_html("## Sub") == "<b>Sub</b><br>"


def test_bullets_grouped_and_blank_line():
    assert to_html("* a\n* b\n\nz") == "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<br>\n<p>z</p>"


def test_dash_bullets_and_inline_bold_inside_bullets():
    assert to_html("- **k**: v") == "<ul>\n<li><b>k</b>: v</li>\n</ul>"


def test_escapes_angle_brackets_in_markdown_text():
    assert to_html("a < b") == "<p>a &lt; b</p>"
