from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📖 Глоссарий", callback_data="glossary"),
            InlineKeyboardButton(text="🌍 Страны", callback_data="countries"),
            InlineKeyboardButton(text="📅 Календарь", callback_data="calendar"),
        ],
        [
            InlineKeyboardButton(text="🏦 Эквайеры", callback_data="acquirers"),
            InlineKeyboardButton(text="🔍 BIN Checker", callback_data="bin_check"),
            InlineKeyboardButton(text="📰 Новости", callback_data="news"),
        ],
        [
            InlineKeyboardButton(text="💻 Платформы", callback_data="platforms"),
            InlineKeyboardButton(text="📊 Трафик", callback_data="traffic"),
            InlineKeyboardButton(text="🛡 AML", callback_data="aml"),
        ],
        [
            InlineKeyboardButton(text="⭐ PRO подписка", callback_data="subscribe"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def glossary_categories_kb(categories: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(text=cat, callback_data=f"gloss_cat:{cat}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def glossary_page_kb(page: int, total_pages: int, category: str,
                     terms: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = []
    for idx, name in terms:
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"gloss_t:{idx}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"gloss_p:{category}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"gloss_p:{category}:{page + 1}"))
    buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="◀️ Категории", callback_data="glossary"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def country_regions_kb(regions: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for r in regions:
        row.append(InlineKeyboardButton(text=r, callback_data=f"c_reg:{r}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="🔎 По вертикали", callback_data="c_verts"),
    ])
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def country_verticals_kb() -> InlineKeyboardMarkup:
    verticals = [
        ("Gambling", "c_vert:gambling"),
        ("Crypto", "c_vert:crypto"),
        ("Forex", "c_vert:forex"),
        ("Adult", "c_vert:adult"),
        ("Nutra", "c_vert:nutra"),
    ]
    buttons = []
    row = []
    for text, cb in verticals:
        row.append(InlineKeyboardButton(text=text, callback_data=cb))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="◀️ Регионы", callback_data="countries"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def acquirer_filter_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="Gambling", callback_data="acq_v:gambling"),
            InlineKeyboardButton(text="Crypto", callback_data="acq_v:crypto"),
        ],
        [
            InlineKeyboardButton(text="Forex", callback_data="acq_v:forex"),
            InlineKeyboardButton(text="Adult", callback_data="acq_v:adult"),
        ],
        [
            InlineKeyboardButton(text="Nutra", callback_data="acq_v:nutra"),
        ],
        [
            InlineKeyboardButton(text="🟢 Low Risk", callback_data="acq_r:low"),
            InlineKeyboardButton(text="🟡 Medium", callback_data="acq_r:medium"),
            InlineKeyboardButton(text="🔴 High", callback_data="acq_r:high"),
        ],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def calendar_month_kb() -> InlineKeyboardMarkup:
    months = [
        "Янв", "Фев", "Мар", "Апр",
        "Май", "Июн", "Июл", "Авг",
        "Сен", "Окт", "Ноя", "Дек",
    ]
    buttons = []
    for i in range(0, 12, 4):
        row = []
        for j in range(4):
            num = i + j + 1
            row.append(InlineKeyboardButton(text=months[i + j], callback_data=f"cal_m:{num}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def platform_type_kb() -> InlineKeyboardMarkup:
    types = [
        ("Биржи", "plat_t:exchange"),
        ("P2P", "plat_t:p2p"),
        ("Крипто-карты", "plat_t:crypto_card"),
        ("Процессинг", "plat_t:processing"),
    ]
    buttons = [[InlineKeyboardButton(text=t, callback_data=cb)] for t, cb in types]
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def aml_region_kb(regions: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for r in regions:
        row.append(InlineKeyboardButton(text=r, callback_data=f"aml_r:{r}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def traffic_vertical_kb() -> InlineKeyboardMarkup:
    verticals = [
        ("Gambling", "traf:gambling"),
        ("Crypto", "traf:crypto"),
        ("Forex", "traf:forex"),
        ("Adult", "traf:adult"),
        ("Nutra", "traf:nutra"),
    ]
    buttons = [[InlineKeyboardButton(text=t, callback_data=cb)] for t, cb in verticals]
    buttons.append([InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="⭐ Купить PRO", callback_data="buy_pro")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu")],
    ])


def acquirer_list_kb(acquirers: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"acq:{idx}")] for idx, name in acquirers]
    buttons.append([
        InlineKeyboardButton(text="◀️ Фильтры", callback_data="acquirers"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def platform_list_kb(platforms: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"plat:{idx}")] for idx, name in platforms]
    buttons.append([
        InlineKeyboardButton(text="◀️ Типы", callback_data="platforms"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def country_list_kb(countries: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"c:{code}")] for code, name in countries]
    buttons.append([
        InlineKeyboardButton(text="◀️ Регионы", callback_data="countries"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
