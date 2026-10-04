#!/usr/bin/env python3
"""Writes the icon block of static/themes/dark.css (the tablet's "dark" theme): each Lucide icon used, from
static/icons/lucide/*.svg (ISC licence: static/icons/LICENSE-lucide.txt), as a CSS mask in a data URI, put on the
page's own classes (the nav, the footer, the rail, a few table markers). Only that theme shows them; the words beside
an icon stay. Run it after adding an icon or changing ICONS: python3 scripts/dark_icons.py
"""
import os
import re
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, "static", "icons", "lucide")
CSS = os.path.join(ROOT, "static", "themes", "dark.css")
BEGIN, END = "/* ---- icons: written by scripts/dark_icons.py ---- */", "/* ---- end of the icons ---- */"
T = '[data-theme="dark"] body.tablet'
# (selector, icon, size in px or None for 1.1em, hide the element's own glyph)
ICONS = [(f"{T} #tabNav [data-view=\"{v}\"]", i, None, False) for v, i in
         (("now", "gauge"), ("near", "radar"), ("here", "orbit"), ("bio", "dna"), ("bm", "bookmark"), ("search", "search"),
          ("map", "map"), ("hwy", "route"), ("hist", "clock"), ("log", "scroll-text"), ("mat", "package"), ("firsts", "flag"))]
ICONS += [(f"{T} #tabNav [data-group=\"{g}\"]", i, None, False) for g, i in
          (("explore", "compass"), ("navigate", "navigation"), ("records", "archive"))]
ICONS += [(f"{T} {sel}", i, None, False) for sel, i in
          ((".tb-voice", "volume-2"), ("#tabHush", "volume-x"), ("#tabStatus", "message-square-text"), ("#tabAsk", "mic"),
           ("#tabSetBtn", "settings"), ("#tabRailEditBtn", "settings"))]
ICONS += [(f"{T} .tb-rb[data-rail=\"{r}\"]", i, 20, False) for r, i in
          (("gear", "arrow-down-to-line"), ("scoop", "package-open"), ("nv", "eye"), ("lights", "lightbulb"), ("fa", "plane"),
           ("silent", "thermometer-snowflake"), ("hard", "crosshair"), ("hud", "scan"), ("da", "car"), ("head", "flashlight"),
           ("brake", "circle-stop"), ("turret", "focus"), ("recall", "ship"), ("torch", "flashlight"), ("shields", "shield"),
           ("bio", "microscope"), ("galmap", "globe"), ("sysmap", "orbit"), ("dock", "anchor"), ("fss", "radio"))]
ICONS += [(f"{T} .bm", "star", 16, True), (f"{T} .bm.on", "star-filled", 16, True), (f"{T} .first", "flag", 15, True),
          (f"{T} .first[title^=\"First footfall\"]", "footprints", 15, True), (f"{T} .scoop", "fuel", 15, True)]


def svg(name):
    if name == "star-filled":   # the same star, filled (a mask uses the shape, not the colour)
        return svg("star").replace('fill="none"', 'fill="black"')
    with open(os.path.join(ICON_DIR, f"{name}.svg"), encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).strip()


def uri(name):
    return "url(\"data:image/svg+xml," + urllib.parse.quote(svg(name), safe=" /=:;,\"'") .replace('"', "'") + "\")"


def block():
    out = [BEGIN]
    for sel, name, px, hide in ICONS:
        size = f"{px}px" if px else "1.15em"
        if hide:   # the glyph (☆ 🏁 ⛽) gives way to the icon; its title still says what it is
            out.append(f"{sel} {{ font-size: 0; }}")
        out.append(f"{sel}::before {{ content: \"\"; display: inline-block; flex: 0 0 auto; width: {size}; height: {size}; "
                   f"vertical-align: -0.2em; margin-right: {'0' if hide else '.5em'}; background: currentColor; "
                   f"-webkit-mask: {uri(name)} center / contain no-repeat; mask: {uri(name)} center / contain no-repeat; }}")
    # the sort arrows: chevrons in place of ▾ ▴
    for sel, name in ((f"{T} th[data-sort].on::after", "chevron-down"), (f"{T} th[data-sort].on.rev::after", "chevron-up")):
        out.append(f"{sel} {{ content: \"\"; display: inline-block; width: 13px; height: 13px; vertical-align: -0.15em; "
                   f"margin-left: 4px; background: currentColor; -webkit-mask: {uri(name)} center / contain no-repeat; "
                   f"mask: {uri(name)} center / contain no-repeat; }}")
    out.append(END)
    return "\n".join(out)


def main():
    with open(CSS, encoding="utf-8") as f:
        css = f.read()
    if BEGIN in css:
        css = css[:css.index(BEGIN)] + block() + css[css.index(END) + len(END):]
    else:
        css = css.rstrip("\n") + "\n" + block() + "\n"
    with open(CSS, "w", encoding="utf-8") as f:
        f.write(css)
    print(f"wrote {len(ICONS) + 2} icon rules into {os.path.relpath(CSS, ROOT)}")


if __name__ == "__main__":
    main()
