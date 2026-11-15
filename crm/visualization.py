"""
Генерация визуализаций для алертов по конверсии.
Дизайн: изумрудный на чёрном, логотип ProcessingHub, почасовой график по методам.
"""
import io
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from datetime import datetime, timezone, timedelta
from PIL import Image

MSK = timezone(timedelta(hours=3))

# === FONT ===
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False
for _font in ['Helvetica Neue', 'Helvetica', 'Arial']:
    try:
        from matplotlib.font_manager import findfont, FontProperties
        if findfont(FontProperties(family=_font)) != findfont(FontProperties()):
            plt.rcParams['font.family'] = _font
            break
    except Exception:
        continue

# === COLORS ===
BG = '#08080A'
EMERALD = '#00E88A'
EMERALD_BRIGHT = '#00FFA3'
TEXT_WHITE = '#FFFFFF'
TEXT_LIGHT = '#C0C0C0'
TEXT_GRAY = '#808080'
TEXT_DIM = '#484848'
RED = '#FF3B5C'
ORANGE = '#FF8C42'
YELLOW = '#FFD84D'
GRID_COLOR = '#161618'
CARD_BG = '#12121A'
CARD_BORDER = '#252530'

METHOD_COLORS = [
    '#00FFA3', '#4DA6FF', '#FF6B9D', '#FFD84D',
    '#A78BFA', '#FF8C42', '#67E8F9', '#F472B6',
]

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'logo.png')


def _status_style(conv: float):
    if conv < 10:
        return RED, "КРИТИЧНО"
    elif conv < 20:
        return ORANGE, "НИЗКАЯ"
    elif conv < 25:
        return YELLOW, "НИЖЕ НОРМЫ"
    return EMERALD, "НОРМА"


def generate_conversion_chart(
    merchant_name: str,
    total: int,
    with_req: int,
    successful: int,
    conv: float,
    hourly_data=None,
    method_stats_pg=None,
) -> io.BytesIO:
    """
    Генерирует карточку алерта конверсии с графиком по методам.

    Args:
        hourly_data: Dict[method, List[{"hour", "total", "successful", "conv_pct"}]]
        method_stats_pg: List[{"method", "total", "with_req", "successful", "conv_pct"}] (from PG)
    """
    status_color, status_text = _status_style(conv)

    # Normalize hourly_data to methods dict (for chart lines)
    methods_data = {}
    if isinstance(hourly_data, dict):
        methods_data = hourly_data
    elif isinstance(hourly_data, list):
        methods_data = {"total": hourly_data}

    # Method stats from PG (consistent with main conv) — for cards
    pg_methods = []
    if method_stats_pg and isinstance(method_stats_pg, list):
        pg_methods = sorted(method_stats_pg, key=lambda m: m.get('total', 0), reverse=True)

    # Sort hourly methods by volume (for chart)
    sorted_chart_methods = sorted(
        methods_data.keys(),
        key=lambda m: sum(r.get('total', 0) for r in methods_data[m]),
        reverse=True,
    )

    has_methods = len(pg_methods) > 0 or len(sorted_chart_methods) > 0

    # Figure layout: top + method cards + chart
    fig = plt.figure(figsize=(12, 9), facecolor=BG, dpi=150)
    if has_methods:
        gs = fig.add_gridspec(3, 1, height_ratios=[1, 0.5, 2], hspace=0.12,
                              left=0.07, right=0.93, top=0.93, bottom=0.08)
        ax_top = fig.add_subplot(gs[0])
        ax_methods = fig.add_subplot(gs[1])
        ax_chart = fig.add_subplot(gs[2])
    else:
        gs = fig.add_gridspec(2, 1, height_ratios=[1, 2], hspace=0.15,
                              left=0.07, right=0.93, top=0.93, bottom=0.08)
        ax_top = fig.add_subplot(gs[0])
        ax_methods = None
        ax_chart = fig.add_subplot(gs[1])

    # === TOP PANEL ===
    ax_top.set_facecolor(BG)
    ax_top.axis('off')
    ax_top.set_xlim(0, 1)
    ax_top.set_ylim(0, 1)

    # Logo
    try:
        if os.path.exists(LOGO_PATH):
            logo = Image.open(LOGO_PATH).convert('RGBA').resize((200, 200), Image.LANCZOS)
            imagebox = OffsetImage(np.array(logo), zoom=0.22)
            ab = AnnotationBbox(imagebox, (0.03, 0.95),
                                frameon=False, box_alignment=(0, 1))
            ax_top.add_artist(ab)
    except Exception:
        pass

    # Merchant name
    ax_top.text(0.10, 0.80, merchant_name, fontsize=20, fontweight='bold',
                color=TEXT_WHITE, va='center')

    # Conversion card
    c_card = mpatches.FancyBboxPatch(
        (0.09, 0.05), 0.32, 0.55, boxstyle="round,pad=0.02",
        facecolor=CARD_BG, edgecolor=status_color, linewidth=1.5, alpha=0.9)
    ax_top.add_patch(c_card)
    ax_top.text(0.25, 0.45, f'{conv:.1f}%', fontsize=38, fontweight='bold',
                color=status_color, va='center', ha='center')
    ax_top.text(0.25, 0.15, f' {status_text} ', fontsize=11, fontweight='bold',
                color=status_color, va='center', ha='center',
                bbox=dict(boxstyle="round,pad=0.3", facecolor=status_color,
                          alpha=0.18, edgecolor=status_color, linewidth=1))

    # Requisites card
    r_card = mpatches.FancyBboxPatch(
        (0.48, 0.05), 0.22, 0.55, boxstyle="round,pad=0.02",
        facecolor=CARD_BG, edgecolor=CARD_BORDER, linewidth=1.2, alpha=0.9)
    ax_top.add_patch(r_card)
    ax_top.text(0.59, 0.72, 'С реквизитами', fontsize=10, color=TEXT_GRAY,
                va='center', ha='center')
    ax_top.text(0.59, 0.35, f'{with_req}', fontsize=30, fontweight='bold',
                color=TEXT_WHITE, va='center', ha='center')

    # Paid card
    p_card = mpatches.FancyBboxPatch(
        (0.74, 0.05), 0.22, 0.55, boxstyle="round,pad=0.02",
        facecolor=CARD_BG, edgecolor=EMERALD, linewidth=1.2, alpha=0.5)
    ax_top.add_patch(p_card)
    ax_top.text(0.85, 0.72, 'Оплатили', fontsize=10, color=TEXT_GRAY,
                va='center', ha='center')
    ax_top.text(0.85, 0.35, f'{successful}', fontsize=30, fontweight='bold',
                color=EMERALD_BRIGHT, va='center', ha='center')

    # === METHOD CARDS ROW ===
    cards_source = pg_methods if pg_methods else []
    if ax_methods is not None and cards_source:
        ax_methods.set_facecolor(BG)
        ax_methods.axis('off')
        ax_methods.set_xlim(0, 1)
        ax_methods.set_ylim(0, 1)

        # Only show methods with requisites
        visible = [m for m in cards_source if m.get('with_req', 0) > 0]
        if not visible:
            visible = cards_source[:4]

        n = min(len(visible), 6)
        card_w = min(0.20, 0.9 / n - 0.02)
        total_w = n * card_w + (n - 1) * 0.02
        start_x = (1 - total_w) / 2

        for i, ms in enumerate(visible[:n]):
            color = METHOD_COLORS[i % len(METHOD_COLORS)]
            method_name = ms.get('method', '?')
            m_conv = ms.get('conv_pct', 0) or 0
            m_req = ms.get('with_req', 0)
            m_succ = ms.get('successful', 0)
            x = start_x + i * (card_w + 0.02)

            card = mpatches.FancyBboxPatch(
                (x, 0.05), card_w, 0.90, boxstyle="round,pad=0.02",
                facecolor=CARD_BG, edgecolor=color, linewidth=1.2, alpha=0.8)
            ax_methods.add_patch(card)

            cx = x + card_w / 2
            ax_methods.text(cx, 0.82, method_name, fontsize=9, fontweight='bold',
                            color=color, va='center', ha='center')
            ax_methods.text(cx, 0.52, f'{m_conv:.1f}%', fontsize=16,
                            fontweight='bold', color=TEXT_WHITE, va='center', ha='center')
            ax_methods.text(cx, 0.22, f'{m_succ}/{m_req}', fontsize=9,
                            color=TEXT_GRAY, va='center', ha='center')

    # === CHART PANEL ===
    ax_chart.set_facecolor(BG)

    all_hours = set()
    max_conv = 0
    drawn = False

    for idx, method in enumerate(sorted_chart_methods):
        rows = methods_data[method]
        color = METHOD_COLORS[idx % len(METHOD_COLORS)]

        h_list = []
        c_list = []
        for r in sorted(rows, key=lambda r: r["hour"]):
            if r.get("total", 0) > 0:
                h_list.append(r["hour"])
                c_list.append(r.get("conv_pct", 0))

        if len(h_list) < 2:
            continue

        x = np.array(h_list)
        y = np.array(c_list, dtype=float)
        all_hours.update(h_list)
        max_conv = max(max_conv, max(c_list))

        # Smooth
        if len(x) > 3:
            try:
                from scipy.interpolate import make_interp_spline
                x_s = np.linspace(x.min(), x.max(), 200)
                spl = make_interp_spline(x, y, k=min(3, len(x) - 1))
                y_s = np.clip(spl(x_s), 0, 100)
            except Exception:
                x_s, y_s = x, y
        else:
            x_s, y_s = x, y

        ax_chart.fill_between(x_s, 0, y_s, alpha=0.06, color=color)
        ax_chart.plot(x_s, y_s, color=color, linewidth=4, alpha=0.10, zorder=2)
        ax_chart.plot(x_s, y_s, color=color, linewidth=2, alpha=0.9, zorder=3,
                      label=method)
        ax_chart.scatter(x, y, color=color, s=30, zorder=4,
                         edgecolors=BG, linewidths=1.2)
        drawn = True

    if not drawn:
        ax_chart.text(0.5, 0.5, 'Нет почасовых данных', ha='center', va='center',
                      fontsize=14, color=TEXT_GRAY, transform=ax_chart.transAxes)
        max_conv = 25

    # Threshold line
    ax_chart.axhline(y=25, color=RED, linewidth=1.2, linestyle='--', alpha=0.6, zorder=1)
    rh = max(all_hours) + 0.5 if all_hours else 23
    ax_chart.text(rh, 26, 'порог 25%', fontsize=9, color=RED, alpha=0.7,
                  va='bottom', fontweight='bold', ha='right')

    # Legend
    if drawn and len(sorted_chart_methods) > 1:
        leg = ax_chart.legend(loc='upper left', fontsize=9, frameon=True,
                              facecolor='#101015', edgecolor='#252530',
                              labelcolor=TEXT_LIGHT, borderpad=0.6, handlelength=1.5)
        leg.get_frame().set_alpha(0.85)

    # Axis styling
    ax_chart.spines['top'].set_visible(False)
    ax_chart.spines['right'].set_visible(False)
    ax_chart.spines['bottom'].set_color('#252528')
    ax_chart.spines['left'].set_color('#252528')
    ax_chart.spines['bottom'].set_linewidth(1.2)
    ax_chart.spines['left'].set_linewidth(1.2)

    ax_chart.tick_params(colors=TEXT_LIGHT, labelsize=11, length=0, pad=8)
    ax_chart.set_xticks(range(0, 24, 2))
    ax_chart.set_xticklabels([f'{h:02d}:00' for h in range(0, 24, 2)],
                              fontsize=10, color=TEXT_LIGHT)
    ax_chart.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:.0f}%'))
    ax_chart.tick_params(axis='y', colors=TEXT_LIGHT, labelsize=10)

    ax_chart.grid(axis='y', color=GRID_COLOR, linewidth=0.8)
    ax_chart.grid(axis='x', color=GRID_COLOR, linewidth=0.4, alpha=0.5)
    ax_chart.set_ylim(bottom=0, top=max(max_conv * 1.3, 30))
    lh = min(all_hours) - 0.5 if all_hours else 0
    ax_chart.set_xlim(lh, rh)

    ax_chart.set_title('Конверсия в оплату по часам', fontsize=14, fontweight='bold',
                       color=TEXT_WHITE, pad=12)

    # Footer
    fig.text(0.07, 0.02,
             f'ProcessingHub  |  {datetime.now(MSK).strftime("%d.%m.%Y %H:%M")} MSK',
             fontsize=9, color=TEXT_DIM)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=BG, edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    return buf
