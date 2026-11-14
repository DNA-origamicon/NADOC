"""Render the captured feature guide for direct, offline browser viewing.

This presentation export does not recapture images or change their baseline.
"""
import argparse
from html import escape
import json

from scripts.feature_guides import GUIDES, REPO


def render(guide_id='extrude'):
    source = REPO / GUIDES / guide_id
    guide = json.loads((source / 'steps.json').read_text())
    manifest = json.loads((source / 'manifest.json').read_text())
    sections = guide['sections']
    nav = ''.join(f'<a href="#chapter-{i}">{escape(s["title"])}</a>'
                  for i, s in enumerate(sections, 1))
    chapters = []
    for i, section in enumerate(sections, 1):
        steps = []
        for step in guide['steps']:
            if step['section'] != section['title']:
                continue
            number, caption = step['number'], escape(step['caption'])
            image = escape(guide_id, quote=True) + '/' + escape(step['file'], quote=True)
            steps.append(f'''<figure id="step-{number}">
<figcaption><span class="step">Step {number}</span><p>{caption}</p></figcaption>
<a href="{image}" aria-label="Open step {number} screenshot at full size">
<img src="{image}" alt="Step {number}: {caption}" width="1920" height="1080" loading="lazy"></a>
</figure>''')
        chapters.append(f'<section id="chapter-{i}"><h2>{escape(section["title"])}</h2>'
                        f'<p>{escape(section["body"])}</p>{"".join(steps)}</section>')
    scope = ''.join(f'<li>{escape(item)}</li>' for item in manifest['covered_workflows'])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(guide['title'])} · NADOC guide</title>
<style>
:root{{color-scheme:dark; font-family:system-ui,sans-serif; line-height:1.65; color:#e6edf3; background:#10151d}}
*{{box-sizing:border-box}}body{{margin:0}}a{{color:#8ecbff}}a:hover{{color:#fff}}
a:focus-visible{{outline:3px solid #ffd54a;outline-offset:4px}}
.layout{{display:grid;grid-template-columns:265px minmax(0,1fr);max-width:1700px;margin:auto}}
nav{{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;padding:32px 22px;border-right:1px solid #303b4b}}
nav strong{{display:block;letter-spacing:.15em;color:#8ecbff;margin-bottom:20px}}
nav a{{display:block;margin:0 0 13px;font-size:.9rem;text-decoration:none}}
main{{min-width:0;padding:40px clamp(18px,4vw,64px) 70px}}
h1{{font-size:clamp(1.8rem,3vw,2.8rem);line-height:1.2;max-width:900px}}h2{{line-height:1.3}}
.eyebrow,.meta{{color:#aab9ca;font-size:.85rem}}.eyebrow{{letter-spacing:.12em;text-transform:uppercase}}
header>p,section>p{{max-width:85ch}}.links{{display:flex;gap:12px 24px;flex-wrap:wrap}}
.notice{{border-left:3px solid #ffd54a;padding:12px 18px;background:#202532}}
section{{margin-top:58px;scroll-margin-top:24px}}figure{{margin:26px 0 38px;border:1px solid #344153;border-radius:10px;overflow:hidden;background:#17202c}}
figcaption{{padding:18px 22px}}figcaption p{{margin:7px 0 0;max-width:95ch}}
.step{{font-weight:700;color:#ffd54a}}img{{display:block;width:100%;height:auto}}
footer{{margin-top:50px;color:#aab9ca}}.skip{{position:absolute;left:-9999px}}.skip:focus{{left:12px;top:12px;z-index:2;background:#10151d;padding:8px}}
@media(max-width:850px){{.layout{{display:block}}nav{{position:static;height:auto;border-right:0;border-bottom:1px solid #303b4b;padding:22px}}nav a{{display:inline-block;margin:0 18px 10px 0}}main{{padding-top:24px}}}}
@media print{{:root{{color-scheme:light;color:#111;background:white}}nav,.skip{{display:none}}.layout{{display:block}}main{{padding:0}}figure{{break-inside:avoid;background:white}}a{{color:inherit}}}}
</style></head><body><a class="skip" href="#guide">Skip to guide</a>
<div class="layout"><nav aria-label="Guide chapters"><strong>NADOC / GUIDES</strong>
<a href="#guide">Overview</a>{nav}<a href="extrude.html">Extrude guide</a><a href="bend.html">Bend guide</a><a href="twist.html">Twist guide</a><a href="README.md">Guide library (Markdown)</a></nav>
<main id="guide"><header><p class="eyebrow">{escape(guide_id.title())} · desktop walkthrough · style-review draft</p>
<h1>{escape(guide['title'])}</h1><p>{escape(manifest['introduction'])}</p>
<p class="meta">{len(guide['steps'])} illustrated steps · {len(sections)} chapters · Captured {escape(manifest['captured_at'])}</p>
<p class="notice">Follow the illustrated steps below to use the tool.</p>
<p>Numbered arrows indicate click targets; dashed boxes show drag extents. Click any screenshot to open it at full size.</p>
<p class="links"><a href="{escape(guide_id, quote=True)}/example.nadoc" download>Download example</a><a href="{escape(guide_id, quote=True)}/README.md">Markdown guide</a><a href="{escape(guide_id, quote=True)}/verification.json">Construction verification</a><a href="UX_LEDGER.md">UX findings</a></p>
<details><summary>Demonstrated scope</summary><ul>{scope}</ul></details></header>
{''.join(chapters)}
<footer>Offline viewing: keep this HTML file beside the {escape(guide_id)} folder. No server or internet connection is required. <a href="#guide">Back to top ↑</a></footer>
</main></div></body></html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the HTML matches the current captured guide')
    parser.add_argument('--guide', choices=['extrude', 'bend', 'twist', 'feature-log'], default='extrude')
    args = parser.parse_args()
    output = REPO / GUIDES / f'{args.guide}.html'
    html = render(args.guide)
    if args.check:
        if not output.exists() or output.read_text() != html:
            raise SystemExit('HTML needs refresh: python3 -m scripts.render_feature_guide_html')
        print('HTML matches the captured guide.')
    else:
        output.write_text(html)
        print(output)


if __name__ == '__main__':
    main()
