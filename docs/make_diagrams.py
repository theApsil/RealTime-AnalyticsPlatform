#!/usr/bin/env python3
"""Генерация PNG-диаграмм архитектуры проекта (matplotlib + Arial Unicode)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

FONT_TTF = "/Users/da.goncharuk/PycharmProjects/Generator/docs/_fonts/ArialUnicode.ttf"
OUT_DIR = "/Users/da.goncharuk/PycharmProjects/Generator/docs/images"
os.makedirs(OUT_DIR, exist_ok=True)

fm.fontManager.addfont(FONT_TTF)
plt.rcParams["font.family"] = "Arial Unicode MS"
plt.rcParams["axes.unicode_minus"] = False

# Палитра слоёв
C_DOMAIN = "#EAF2FB"; E_DOMAIN = "#2C6FAD"
C_GEN = "#E7F5EA";     E_GEN = "#2E8B57"
C_SVC = "#FFF3E0";     E_SVC = "#E0820C"
C_REPO = "#F3E8FB";    E_REPO = "#7B4FA6"
C_CFG = "#FCE8E8";     E_CFG = "#C0392B"
C_EXT = "#EEEEEE";     E_EXT = "#666666"


def box(ax, x, y, w, h, text, fc, ec, fs=9, tc="#111", bold=False, style="round,pad=0.25"):
    p = FancyBboxPatch((x, y), w, h, boxstyle=style, fc=fc, ec=ec, lw=1.3)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=tc, fontweight="bold" if bold else "normal")


def arrow(ax, p1, p2, color="#555", ls="-", rad=0.0, label=None, lx=0, ly=0, fs=7.5):
    a = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=14,
                        color=color, lw=1.4, linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + lx, (p1[1] + p2[1]) / 2 + ly
        ax.text(mx, my, label, ha="center", va="center", fontsize=fs, color="#333")


def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")
    return fig, ax


def save(fig, name):
    fig.savefig(os.path.join(OUT_DIR, name), dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print("saved", name)


# =========================================================
# 1. Слоистая архитектура и направление зависимостей
# =========================================================
fig, ax = new_fig(8.2, 9.5)
ax.set_title("Слоистая архитектура: направление зависимостей", fontsize=13,
             fontweight="bold", pad=10)

X, W = 21, 56
# конфигурация (сверху) -> сервис -> генерация; домен — ядро (снизу); хранение — справа
box(ax, X, 68, W, 9, "Конфигурация (config.py)\nGeneratorSettings, ClickHouseSettings",
    C_CFG, E_CFG, bold=True)
box(ax, X, 52, W, 9, "Сервисный слой (service/generator.py)\nцикл «батч → запись», retry, graceful shutdown",
    C_SVC, E_SVC, bold=True)
box(ax, X, 34, W, 10, "Слой генерации (generation/)\nseasonality, metrics (Strategy),\nanomalies, catalog, weather",
    C_GEN, E_GEN, bold=True)
box(ax, X, 8, W, 11, "Домен (models.py) — ЯДРО\nStation, WeatherReading, WeatherType\nчистые модели, ноль зависимостей",
    C_DOMAIN, E_DOMAIN, bold=True)
# хранение справа, зависит от домена
box(ax, 80, 34, 18, 10, "Хранение\n(repository/)\nпорт + адаптеры", C_REPO, E_REPO, bold=True)
box(ax, 80, 17, 18, 9, "InMemory\nClickHouse", "#FFFFFF", E_REPO)

# зависимости вниз к ядру
arrow(ax, (X + W / 2, 77), (X + W / 2, 61), label="чтение настроек", ly=-4)
arrow(ax, (X + W / 2, 52), (X + W / 2, 44), label="фасад → сервис", lx=0, ly=-4)
arrow(ax, (X + W / 2, 34), (X + W / 2, 19), label="импорт моделей", ly=-4)
arrow(ax, (89, 34), (89, 26), label="DIP: зависит от порта", lx=-8, ly=3)
arrow(ax, (77, 26.5), (60, 19), rad=-0.2, color="#bbb", ls=":", label="домен без знания о БД", lx=-6, ly=4)
ax.text(50, 0, "Главное правило: зависимости направлены ВНИЗ — к чистому ядру.\n"
               "Домен ничего не знает ни о БД, ни о генерации; хранилище и генерация зависят от домена.",
        ha="center", va="center", fontsize=8.5, color="#333", bbox=dict(fc="#FBFBFB",
        ec="#bbb", boxstyle="round,pad=0.6"))
save(fig, "01_layers.png")

# =========================================================
# 2. Композиционный корень / инъекция зависимостей
# =========================================================
fig, ax = new_fig(9.5, 8.6)
ax.set_title("Композиционный корень (cli.py) — сборка всех зависимостей", fontsize=13,
             fontweight="bold", pad=10)
box(ax, 36, 80, 28, 10, "cli.main()\nкомпозиционный корень", C_SVC, E_SVC, bold=True, fs=10)
box(ax, 4, 56, 26, 9, "get_settings()\nGeneratorSettings /\nClickHouseSettings", C_CFG, E_CFG)
box(ax, 36, 56, 26, 9, "StationCatalog(\ncities)", C_GEN, E_GEN)
box(ax, 68, 56, 28, 9, "AnomalyPolicy(prob,\nstrength, rng)", C_GEN, E_GEN)
box(ax, 36, 32, 26, 13, "BatchGenerator(catalog,\nseed, anomaly_policy)\n↓ по генератору на станцию", C_GEN, E_GEN)
box(ax, 68, 32, 28, 9, "RetryPolicy(...)\nbackoff + jitter", C_SVC, E_SVC)
box(ax, 4, 30, 26, 10, "Repository\n(порт)", C_REPO, E_REPO, bold=True)
box(ax, 4, 16, 26, 9, "InMemoryRepository", C_EXT, E_EXT)
box(ax, 34, 16, 26, 9, "ClickHouseRepository", C_EXT, E_EXT)
box(ax, 40, 4, 34, 9, "GeneratorService(settings,\nbatch_generator, repository, retry)", C_SVC, E_SVC, bold=True)

arrow(ax, (50, 80), (17, 65), label="настройки", lx=-6, ly=5)
arrow(ax, (50, 80), (49, 65), label="города", lx=-4, ly=5)
arrow(ax, (50, 80), (82, 65), label="rng(seed)", lx=7, ly=4)
arrow(ax, (49, 56), (49, 45), label="каталог+сид", lx=0, ly=5)
arrow(ax, (82, 56), (82, 41), color="#888", ls="--")
arrow(ax, (17, 56), (17, 40), color="#888", ls="--")
arrow(ax, (57, 45), (57, 13), rad=-0.15, label="всё в сервис", lx=6, ly=5)
arrow(ax, (82, 32), (72, 13), rad=0.1, label="retry", lx=4, ly=-5)
arrow(ax, (50, 80), (50, 13), rad=0.22, color="#888", ls=":")
ax.text(50, 88.5, "Идея: main() собирает готовые части и «впрыскивает» их (DI).\n"
                  "Сервис не создаёт зависимости сам — он их получает.", ha="center",
        va="center", fontsize=8.5, color="#333", bbox=dict(fc="#FBFBFB", ec="#bbb",
        boxstyle="round,pad=0.5"))
save(fig, "02_composition.png")

# =========================================================
# 3. Стратегия и Ports & Adapters
# =========================================================
fig, ax = new_fig(10, 7.6)
ax.set_title("Паттерны: Strategy (метрики) и Ports & Adapters (хранение)", fontsize=13,
             fontweight="bold", pad=10)
ax.text(25, 93, "Метрики — Strategy", fontsize=12, fontweight="bold", ha="center")
ax.text(74, 93, "Хранение — Ports & Adapters", fontsize=12, fontweight="bold", ha="center")
box(ax, 8, 66, 34, 9, "MetricSampler (ABC)\nsample(ctx, rng) -> float", C_GEN, E_GEN, bold=True)
for i, name in enumerate(["TemperatureSampler", "HumiditySampler", "PressureSampler",
                          "WindSpeedSampler", "WindDirectionSampler"]):
    y = 54 - i * 8.5
    box(ax, 8, y, 34, 6, name, "#FFFFFF", E_GEN)
    arrow(ax, (25, y + 6), (25, 66), color=E_GEN)
box(ax, 58, 66, 32, 9, "Repository (Protocol)\nensure_schema / upsert / insert", C_REPO, E_REPO, bold=True)
box(ax, 58, 46, 32, 7, "InMemoryRepository", "#FFFFFF", E_REPO)
arrow(ax, (74, 53), (74, 66), color=E_REPO)
box(ax, 58, 34, 32, 7, "ClickHouseRepository", "#FFFFFF", E_REPO)
arrow(ax, (74, 41), (74, 66), color=E_REPO, ls="--")
box(ax, 70, 14, 34, 9, "GeneratorService\nзависит только от протокола", C_SVC, E_SVC, bold=True)
arrow(ax, (74, 14 + 9), (74, 41), rad=0.15, label="DIP", lx=7, ly=3)
ax.text(25, 2, "Новая метрика = один класс.\nКод генератора не меняется (OCP).",
        ha="center", va="center", fontsize=8, color="#333")
ax.text(74, 2, "Подмена БД без правки сервиса.\nInMemory — для тестов и запуска без ClickHouse.",
        ha="center", va="center", fontsize=8, color="#333")
save(fig, "03_patterns.png")

# =========================================================
# 4. Поток данных / runtime
# =========================================================
fig, ax = new_fig(10.5, 8.2)
ax.set_title("Runtime-поток: цикл генерации батча", fontsize=13, fontweight="bold", pad=10)
box(ax, 4, 78, 30, 9, "GeneratorService.run()", C_SVC, E_SVC, bold=True)
box(ax, 40, 78, 28, 9, "repository.ensure_schema()\n+ upsert_stations()", C_REPO, E_REPO)
box(ax, 4, 60, 30, 9, "generate_batch(at, size)\nчередование станций  i % N", C_GEN, E_GEN)
box(ax, 40, 60, 28, 9, "for чтение: anomaly_policy.\ndecide() -> тип или None", C_GEN, E_GEN)
box(ax, 74, 60, 24, 9, "самплеры метрик\nsample(ctx, rng)", C_GEN, E_GEN)
box(ax, 74, 42, 24, 9, "применение аномалий\n_apply_*_anomaly()", C_GEN, E_GEN)
box(ax, 40, 42, 28, 9, "pick(weather_type)", C_GEN, E_GEN)
box(ax, 40, 24, 28, 9, "insert_readings(batch)\nRetryPolicy (backoff+jitter)", C_REPO, E_REPO)
box(ax, 74, 24, 24, 9, "sleep(interval - elapsed)", C_SVC, E_SVC)

arrow(ax, (34, 82.5), (40, 82.5), label="схема+справочник", lx=0, ly=5)
arrow(ax, (19, 78), (19, 69), label="пачка показаний", lx=0, ly=4)
arrow(ax, (34, 64.5), (40, 64.5), label="на каждую запись", lx=0, ly=5)
arrow(ax, (68, 64.5), (74, 64.5), label="контекст+rng", lx=0, ly=5)
arrow(ax, (86, 60), (86, 51), label="аномалия", lx=0, ly=4)
arrow(ax, (74, 46.5), (68, 46.5), label="значения", lx=0, ly=5)
arrow(ax, (54, 60), (54, 51), label="", lx=0, ly=4)
arrow(ax, (68, 42), (68, 33), label="запись в БД (retry)", lx=0, ly=4)
arrow(ax, (54, 24), (74, 28.5), rad=-0.15, label="пауза", lx=5, ly=2)
arrow(ax, (86, 24), (86, 15), color="#888", ls=":")
ax.text(98, 12, "цикл\nwhile not\nstop_event", ha="center", va="center", fontsize=7.5, color="#555")
save(fig, "04_runtime.png")

print("Все диаграммы готовы:", os.listdir(OUT_DIR))