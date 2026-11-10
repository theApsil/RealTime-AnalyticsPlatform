#!/usr/bin/env python3
"""Сборка двух версий презентации:
  - prezentaciya.md  (для студентов: mermaid-диаграммы, эмодзи сохраняются)
  - prezentaciya.pdf (для чтения: PNG-диаграммы, без эмодзи)
"""
import os
import re

import markdown
from xhtml2pdf import pisa

DOCS = "/Users/da.goncharuk/PycharmProjects/Generator/docs"
FONT = f"file://{DOCS}/_fonts/ArialUnicode.ttf"
OUT_MD = os.path.join(DOCS, "prezentaciya.md")
OUT_PDF = os.path.join(DOCS, "prezentaciya.pdf")

# Порядок mermaid-блоков в architecture.md -> PNG
MM_TO_IMG = [
    ("images/01_layers.png", "Слоистая архитектура и направление зависимостей"),
    ("images/03_patterns.png", "Паттерн Strategy для метрик"),
    ("images/03_patterns.png", "Ports & Adapters — хранение"),
    ("images/02_composition.png", "Композиционный корень и инъекция зависимостей"),
    ("images/04_runtime.png", "Runtime: цикл генерации батча"),
]


def mermaid_to_images(text: str) -> str:
    """Заменяет ```mermaid ... ``` на ссылку на PNG (по порядку появления)."""
    counter = 0

    def repl(m):
        nonlocal counter
        if counter >= len(MM_TO_IMG):
            return m.group(0)
        img, caption = MM_TO_IMG[counter]
        counter += 1
        return f"![{caption}]({img})\n"

    return re.sub(r"```mermaid\s*.*?```", repl, text, flags=re.DOTALL)


def read(path: str) -> str:
    with open(os.path.join(DOCS, path), encoding="utf-8") as f:
        return f.read()


arch = read("architecture.md")
osnovy = read("razbor_osnovy.md")
gen = read("razbor_generator.md")
gen = gen.replace("# Подробный разбор модулей генератора",
                  "# Часть C. Подробный разбор файлов генерации", 1)

title = """# ⚡ RealTime-AnalyticsPlatform

## Учебный материал: архитектура и подробный разбор кода

**Модуль генерации данных** · Production-ready платформа для end-to-end потоковой аналитики

---

> Содержание:
> 1. **Часть A** — полная архитектура проекта (слои, паттерны, решения «почему так»).
> 2. **Часть B** — подробный разбор основ: `models.py`, `config.py`, `seasonality.py`, `anomalies.py`.
> 3. **Часть C** — подробный разбор генерации: `metrics.py`, `catalog.py`, `weather.py`, `retry.py`.

---

"""

# Заголовок для MD (только архитектура, без ссылок на отсутствующие части)
title_md = """# ⚡ RealTime-AnalyticsPlatform

## Архитектура модуля генерации данных

**Production-ready платформа для end-to-end потоковой аналитики** · диаграммы архитектуры

---

"""

ARCH_ONLY = "# Часть A. Архитектура\n\n" + arch

# ===== 1) MD для студентов: только архитектура с mermaid-диаграммами =========
md_full = title_md + ARCH_ONLY
with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write(md_full)
print("OK:", OUT_MD)

# ===== 2) PDF для чтения: всё (архитектура + разборы), PNG, без эмодзи ========
pdf_arch = mermaid_to_images(arch)
pdf_full = (title
            + "# Часть A. Архитектура\n\n" + pdf_arch + "\n\n---\n\n"
            + osnovy + "\n\n---\n\n" + gen)
pdf_full = (pdf_full.replace("⚡", "").replace("✅", "✓").replace("❌", "✗")
            .replace("⚠️", "").replace("⚠", "").replace("\ufe0f", ""))

html_body = markdown.markdown(pdf_full, extensions=["fenced_code", "tables"])
html_body = html_body.replace('src="images/', f'src="file://{DOCS}/images/')

css = f"""
@font-face {{ font-family: "ArialUni"; src: url("{FONT}"); }}
body {{ font-family: "ArialUni"; font-size: 10pt; line-height: 1.45; }}
h1 {{ color: #14324f; font-size: 17pt; }}
h2 {{ color: #14324f; font-size: 13pt; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
h3 {{ color: #14324f; font-size: 11pt; }}
pre {{ background: #f5f5f5; padding: 8px; font-size: 8pt; white-space: pre-wrap; }}
code {{ font-family: "ArialUni"; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 4px; font-size: 9pt; }}
th {{ background: #eef2f6; }}
blockquote {{ border-left: 3px solid #1a6bb0; margin: 0; padding-left: 10px; color: #333; }}
img {{ max-width: 620px; max-height: 500px; }}
hr {{ border: none; border-top: 1px solid #ccc; }}
"""

html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{html_body}</body></html>"
with open(OUT_PDF, "wb") as f:
    pisa.CreatePDF(html, dest=f)
print("OK:", OUT_PDF)