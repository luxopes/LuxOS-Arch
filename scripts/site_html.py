"""LuxOS web: znama jmena HTML/SVG prvku. Markdown pousti surove HTML beze zmeny, takze zastupny text
jako „Pokračovat jako <jméno>“ nebo `Super+<key>` mimo kod by prohlizec bral jako neznamy prvek
a vubec ho neukazal. scripts/build-site.py takove „prvky“ escapuje, scripts/check-site.py je hlasi.
"""
import re

KNOWN_TAGS = frozenset("""html head body title meta link script style noscript base header footer main nav section
article aside h1 h2 h3 h4 h5 h6 p div span a img picture source figure figcaption ul ol li dl dt dd table thead
tbody tfoot tr th td caption colgroup col pre code kbd samp var em strong b i u s small sub sup mark abbr cite q
blockquote br hr wbr button input label select option textarea form fieldset legend details summary dialog
template slot time data output progress meter iframe video audio track canvas del ins svg path circle rect line
polyline polygon g defs use symbol lineargradient radialgradient stop clippath mask text tspan ellipse filter
desc""".split())

_TAG = re.compile(r"<(/?)([^\s<>/!?]+)([^<>]*)>")


def known(tag):
    return tag.lower() in KNOWN_TAGS or tag.lower().startswith("fe")


def escape_unknown_tags(html_text):
    """<jméno>, </name> apod. -> &lt;jméno&gt; (skutecne HTML prvky zustanou)."""
    def fix(m):
        if known(m.group(2)):
            return m.group(0)
        return "&lt;" + m.group(0)[1:-1] + "&gt;"
    return _TAG.sub(fix, html_text)
