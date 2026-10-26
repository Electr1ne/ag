from aiogram.fsm.state import State, StatesGroup

class AdminStates(StatesGroup):
    broadcast_text = State()
    direct_msg_target = State()
    direct_msg_text = State()

    # Бан с причиной
    ban_user_target = State()
    ban_user_reason = State()
    unban_user_target = State()

    # Попытки
    give_attempts_target = State()
    give_attempts_game = State()
    give_attempts_count = State()

    # Звёзды (выдача и снятие)
    give_stars_target = State()
    give_stars_count = State()
    take_stars_target = State()
    take_stars_count = State()

    # Каналы
    add_channel_title = State()
    add_channel_username = State()
    add_channel_type = State()