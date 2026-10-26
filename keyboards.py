from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Any
from config import ADMIN_ID

GAMES = {
    "basket": {
        "title": "🏀 Баскет за подарки",
        "desc": "Попади мячом ровно в кольцо каждым чистым броском и получи подарок 🎁",
        "item_name": "Мячей",
        "single_name": "Мяч",
        "emoji": "🏀",
        "shots_count": 6,
        "prev": "slots",
        "next": "football",
        "prev_label": "🎰 Слоты",
        "next_label": "⚽ Футбол"
    },
    "football": {
        "title": "⚽ Футбол за подарки",
        "desc": "Попади в девятку каждым мячом и получи подарок 🎁",
        "item_name": "Мячей",
        "single_name": "Мяч",
        "emoji": "⚽",
        "shots_count": 6,
        "prev": "basket",
        "next": "darts",
        "prev_label": "🏀 Баскет",
        "next_label": "🎯 Дартс"
    },
    "darts": {
        "title": "🎯 Дартс за подарки",
        "desc": "Попади дротиком в мишень(в яблочко) каждым броском и получи крутой подарок 🎁",
        "item_name": "Бросков",
        "single_name": "Бросок",
        "emoji": "🎯",
        "shots_count": 6,
        "prev": "football",
        "next": "bowling",
        "prev_label": "⚽ Футбол",
        "next_label": "🎳 Боулинг"
    },
    "bowling": {
        "title": "🎳 Боулинг за подарки",
        "desc": "Оформи страйк каждым броском и получи подарок 🎁",
        "item_name": "Шаров",
        "single_name": "Шар",
        "emoji": "🎳",
        "shots_count": 6,
        "prev": "darts",
        "next": "dice",
        "prev_label": "🎯 Дартс",
        "next_label": "🎲 Кости"
    },
    "dice": {
        "title": "🎲 Кости за подарки",
        "desc": "Все числа на кубиках одинаковые? — получаешь подарок 🎁",
        "item_name": "Кубиков",
        "single_name": "Кубик",
        "emoji": "🎲",
        "shots_count": 6,
        "prev": "bowling",
        "next": "slots",
        "prev_label": "🎳 Боулинг",
        "next_label": "🎰 Слоты"
    },
    "slots": {
        "title": "🎰 Слоты за подарки",
        "desc": "Выбей три в ряд каждым прокрутом и забери подарок 🎁",
        "item_name": "Прокрута",
        "single_name": "Прокрут",
        "emoji": "🎰",
        "shots_count": 3,
        "prev": "dice",
        "next": "basket",
        "prev_label": "🎲 Кости",
        "next_label": "🏀 Баскет"
    }
}

def format_time_left(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}ч {minutes}м"

def get_game_keyboard(
    game_key: str,
    user_id: int,
    bot_username: str,
    cooldown_left: int,
    chat_reward_claimed: bool,
    extra_attempts: int = 0
) -> InlineKeyboardMarkup:
    g = GAMES[game_key]
    count = g["shots_count"]
    item = g["item_name"]
    single = g["single_name"]
    icon = g["emoji"]

    buttons = []

    if cooldown_left <= 0:
        buttons.append([
            InlineKeyboardButton(text=f"🔥{icon} {count} {item} бесплатно", callback_data=f"play_free:{game_key}")
        ])
    else:
        time_str = format_time_left(cooldown_left)
        buttons.append([
            InlineKeyboardButton(text=f"⏳ Бесплатно через {time_str}", callback_data=f"cooldown_info:{cooldown_left}")
        ])

    if extra_attempts > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 Бесплатные попытки от админа ({extra_attempts})",
                callback_data=f"play_extra:{game_key}"
            )
        ])

    buttons.extend([
        [
            InlineKeyboardButton(text=f"{icon} 5 {item} - 1 ⭐", callback_data=f"buy_attempt:{game_key}:5:1"),
            InlineKeyboardButton(text=f"{icon} 4 {item} - 2 ⭐", callback_data=f"buy_attempt:{game_key}:4:2")
        ],
        [
            InlineKeyboardButton(text=f"{icon} 3 {item} - 3 ⭐", callback_data=f"buy_attempt:{game_key}:3:3"),
            InlineKeyboardButton(text=f"{icon} 2 {item} - 5 ⭐", callback_data=f"buy_attempt:{game_key}:2:5")
        ],
        [
            InlineKeyboardButton(text=f"💎{icon} 1 {single} - 10 ⭐", callback_data=f"buy_attempt:{game_key}:1:10")
        ]
    ])

    if chat_reward_claimed:
        chat_btn = InlineKeyboardButton(text="✅ Чат добавлен (+3 ⭐)", callback_data="chat_claimed_info")
    else:
        chat_btn = InlineKeyboardButton(text="+3 ⭐ Добавить в чат", url=f"https://t.me/{bot_username}?startgroup=true&admin=post_messages")

    buttons.append([
        chat_btn,
        InlineKeyboardButton(text="+2 ⭐ За друга", callback_data="ref_section")
    ])

    buttons.append([
        InlineKeyboardButton(text="📋 Мои заявки на подарки", callback_data="my_claims")
    ])

    buttons.append([
        InlineKeyboardButton(text=f"❮❮ {g['prev_label']}", callback_data=f"nav:{g['prev']}"),
        InlineKeyboardButton(text=f"{g['next_label']} ❯❯", callback_data=f"nav:{g['next']}")
    ])

    if user_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton(text="🅰️ Админ-панель", callback_data="admin_panel")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard(target_game: str = "basket") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data=f"nav:{target_game}")]
    ])

def get_sub_check_keyboard(channels: List[Any], check_type: str, game_key: str = "basket") -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        url = f"https://t.me/{ch['channel_username']}"
        buttons.append([InlineKeyboardButton(text=ch['title'], url=url)])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить подписку", callback_data=f"sub_check:{check_type}:{game_key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- Админ-панель ---
def get_admin_main_keyboard(pending_claims: int = 0) -> InlineKeyboardMarkup:
    claims_text = f"📋 Заявки ({pending_claims})" if pending_claims > 0 else "📋 Заявки"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=claims_text, callback_data="adm:claims:1"),
            InlineKeyboardButton(text="🎲 Сыграть выигрыш (Тест)", callback_data="adm:test_win")
        ],
        [
            InlineKeyboardButton(text="🗑 Очистить заявки (Сброс в #1)", callback_data="adm:clear_claims_confirm")
        ],
        [
            InlineKeyboardButton(text="⭐ Выдать звёзды", callback_data="adm:give_stars"),
            InlineKeyboardButton(text="🔻 Забрать звёзды", callback_data="adm:take_stars")
        ],
        [
            InlineKeyboardButton(text="🎁 Выдать попытки", callback_data="adm:give_attempts"),
            InlineKeyboardButton(text="📢 Рассылка всем", callback_data="adm:broadcast")
        ],
        [
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data="adm:direct_msg"),
            InlineKeyboardButton(text="⛔ Забанить", callback_data="adm:ban")
        ],
        [
            InlineKeyboardButton(text="✅ Разбанить", callback_data="adm:unban"),
            InlineKeyboardButton(text="⚙️ Управление каналами (ОП)", callback_data="adm:channels")
        ],
        [
            InlineKeyboardButton(text="🔙 В главное меню", callback_data="nav:basket")
        ]
    ])

def get_admin_clear_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Да, удалить все и сбросить в #1", callback_data="adm:clear_claims_execute")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")
        ]
    ])

def get_admin_claims_keyboard(claims: List[Any], page: int, total_count: int, per_page: int = 8) -> InlineKeyboardMarkup:
    buttons = []
    row = []

    for claim in claims:
        status_icon = "⏳" if claim["status"] == "pending" else ("✅" if claim["status"] == "approved" else "❌")
        btn_text = f"{status_icon} #{claim['id']} {claim['prize_name']}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"adm_claim_view:{claim['id']}:{page}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    total_pages = max(1, (total_count + per_page - 1) // per_page)
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:claims:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:claims:{page + 1}"))
    buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="🔙 В админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_claim_action_keyboard(claim_id: int, page: int, status: str) -> InlineKeyboardMarkup:
    buttons = []
    if status == "pending":
        buttons.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm_claim_act:{claim_id}:approve:{page}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_claim_act:{claim_id}:reject:{page}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 К списку заявок", callback_data=f"adm:claims:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_channels_keyboard(channels: List[Any]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="adm:add_channel")]
    ]
    for ch in channels:
        status_icon = "🟢" if ch["is_active"] else "🔴"
        type_str = "Бот" if ch["check_type"] == "bot" else "Попытка"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status_icon} [{type_str}] {ch['title']}",
                callback_data=f"adm_ch_view:{ch['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_channel_item_keyboard(ch_id: int, is_active: bool) -> InlineKeyboardMarkup:
    status_btn = "🔴 Выключить" if is_active else "🟢 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_btn, callback_data=f"adm_ch_toggle:{ch_id}")],
        [InlineKeyboardButton(text="🗑 Удалить канал", callback_data=f"adm_ch_delete:{ch_id}")],
        [InlineKeyboardButton(text="🔙 К списку каналов", callback_data="adm:channels")]
    ])

def get_cancel_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]
    ])