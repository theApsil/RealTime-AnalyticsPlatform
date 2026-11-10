#!/usr/bin/env python3
"""Конвертер Markdown -> PDF (xhtml2pdf) с поддержкой кириллицы."""
import markdown
from xhtml2pdf import pisa

SRC = "docs/razbor_generator.md"
OUT = "docs/razbor_generator.pdf"
FONT = "file:///Users/da.goncharuk/PycharmProjects/Generator/docs/_fonts/ArialUnicode.ttf"

with open(SRC, encoding="utf-8") as f:
    md = f.read()

html_body = markdown.markdown(md, extensions=["fenced_code", "tables"])

css = f"""
@font-face {{ font-family: "ArialUni"; src: url("{FONT}"); }}
body {{ font-family: "ArialUni"; font-size: 10pt; line-height: 1.45; }}
h1 {{ color: #14324f; font-size: 16pt; }}
h2 {{ color: #14324f; font-size: 13pt; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
h3 {{ color: #14324f; font-size: 11pt; }}
pre {{ background: #f5f5f5; padding: 8px; font-size: 8pt; white-space: pre-wrap; }}
code {{ font-family: "ArialUni"; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 4px; font-size: 9pt; }}
th {{ background: #eef2f6; }}
blockquote {{ border-left: 3px solid #1a6bb0; margin: 0; padding-left: 10px; color: #333; }}
hr {{ border: none; border-top: 1px solid #ccc; }}
"""

html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{html_body}</body></html>"

with open(OUT, "wb") as f:
    pisa.CreatePDF(html, dest=f)

print("OK:", OUT)