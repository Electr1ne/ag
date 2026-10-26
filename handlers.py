import asyncio
import logging
import random
from html import escape
from typing import Tuple, List, Any

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    ChatMemberUpdated,
    PreCheckoutQuery,
    LabeledPrice,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
)
from aiogram.filters import (
    CommandStart,
    Command,
    ChatMemberUpdatedFilter,
    MEMBER,
    ADMINISTRATOR,
)
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from database import (
    add_user,
    get_user,
    get_user_by_query,
    get_all_users,
    get_total_users_count,
    update_balance,
    get_referrals_count,
    get_free_cooldown_left,
    set_free_game_used_now,
    get_extra_attempts,
    add_extra_attempts,
    can_claim_chat_reward,
    claim_chat_reward,
    get_ban_info,
    set_ban_status,
    get_channels,
    add_channel,
    toggle_channel_status,
    delete_channel,
    create_prize_claim,
    get_claim_by_id,
    get_user_claims,
    update_claim_status,
    get_claims_page,
    get_pending_claims_count,
    clear_all_claims,
    CHAT_REWARD_STARS,
    REFERRAL_REWARD_STARS,
)
from keyboards import (
    GAMES,
    format_time_left,
    get_game_keyboard,
    get_back_keyboard,
    get_sub_check_keyboard,
    get_admin_main_keyboard,
    get_admin_clear_confirm_keyboard,
    get_admin_claims_keyboard,
    get_admin_claim_action_keyboard,
    get_admin_channels_keyboard,
    get_admin_channel_item_keyboard,
    get_cancel_admin_keyboard,
)
from game_logic import evaluate_full_series
from admin_states import AdminStates
from config import ADMIN_ID

router = Router()
logger = logging.getLogger(__name__)

active_players = set()
cached_bot_username: str = ""

PRIZES = ["🧸 Мишка", "💝 Сердце с лентой"]


async def get_bot_username(bot: Bot) -> str:
    global cached_bot_username
    if not cached_bot_username:
        try:
            me = await bot.get_me()
            cached_bot_username = me.username or ""
        except TelegramAPIError:
            cached_bot_username = "bot"
    return cached_bot_username


def format_card_text(game_key: str, balance: int) -> str:
    g = GAMES[game_key]
    return (
        f"{g['title']}\n\n"
        f"{g['desc']}\n\n"
        f"💰 Баланс: {balance} ⭐"
    )


async def check_user_subscriptions(
        bot: Bot, user_id: int, check_type: str
) -> Tuple[bool, List[Any]]:
    channels = get_channels(check_type=check_type, active_only=True)
    unsubscribed = []

    VALID_STATUSES = {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
        "creator",
        "administrator",
        "member",
    }

    for ch in channels:
        chat_identifier = f"@{ch['channel_username']}"
        try:
            member = await bot.get_chat_member(chat_id=chat_identifier, user_id=user_id)
            if member.status not in VALID_STATUSES:
                unsubscribed.append(ch)
        except TelegramAPIError as err:
            logger.warning("Ошибка проверки подписки %s на %s: %s", user_id, chat_identifier, err)
            unsubscribed.append(ch)

    return (len(unsubscribed) == 0), unsubscribed


async def run_game_series(
        bot: Bot, chat_id: int, user_id: int, game_key: str, count: int, username: str = None
):
    active_players.add(user_id)
    g = GAMES[game_key]
    emoji = g["emoji"]

    intro_msg = await bot.send_message(chat_id,
                                       f"🚀 Погнали! Кидаем {count} {g['single_name'] if count == 1 else g['item_name']} подряд:")

    results = []
    for _ in range(count):
        msg = await bot.send_dice(chat_id=chat_id, emoji=emoji)
        results.append(msg.dice.value)
        await asyncio.sleep(0.6)

    await asyncio.sleep(2.0 if game_key != "slots" else 1.5)
    active_players.discard(user_id)

    try:
        await bot.delete_message(chat_id=chat_id, message_id=intro_msg.message_id)
    except TelegramAPIError:
        pass

    won, result_msg = evaluate_full_series(game_key, results)

    if won:
        prize = random.choice(PRIZES)
        claim_id = create_prize_claim(user_id=user_id, username=username, game_title=g["title"], prize_name=prize)

        user_text = (
            "🎉 <b>ПОБЕДА! ВЫ ВЫИГРАЛИ ПОДАРОК!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎁 <b>Ваш приз:</b> <b>{prize}</b>\n"
            f"📋 <b>Номер заявки:</b> <code>#{claim_id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ <i>Заявка успешно зарегистрирована в очереди!</i>\n"
            "⏳ <b>Срок выдачи:</b> от <b>15 минут</b> до <b>7 дней</b>.\n\n"
            "Вы всегда можете проверить статус в разделе «📋 Мои заявки на подарки»."
        )
        await bot.send_message(chat_id, user_text, reply_markup=get_back_keyboard(game_key), parse_mode="HTML")

        try:
            admin_notify = (
                "🚨 <b>НОВАЯ ЗАЯВКА НА ВЫДАЧУ ПОДАРКА!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>Заявка:</b> <code>#{claim_id}</code>\n"
                f"👤 <b>Игрок:</b> @{username or 'нет'} (ID: <code>{user_id}</code>)\n"
                f"🎮 <b>Режим:</b> {g['title']}\n"
                f"🎁 <b>Приз:</b> <b>{prize}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Нажмите кнопку ниже для обработки:"
            )
            quick_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔎 Открыть заявку", callback_data=f"adm_claim_view:{claim_id}:1")]
            ])
            await bot.send_message(chat_id=ADMIN_ID, text=admin_notify, reply_markup=quick_kb, parse_mode="HTML")
        except TelegramAPIError as err:
            logger.warning("Не удалось отправить уведомление админу: %s", err)
    else:
        await bot.send_message(chat_id, result_msg, reply_markup=get_back_keyboard(game_key))


# --- Фильтр бана с выводом точной причины ---
@router.message(lambda msg: get_ban_info(msg.from_user.id)[0])
async def banned_message_handler(message: Message):
    _, reason = get_ban_info(message.from_user.id)
    await message.answer(
        f"⛔ <b>Ваш аккаунт заблокирован администратором!</b>\n"
        f"💬 <b>Причина:</b> <i>{escape(str(reason))}</i>",
        parse_mode="HTML"
    )


@router.callback_query(lambda cb: get_ban_info(cb.from_user.id)[0])
async def banned_callback_handler(callback: CallbackQuery):
    _, reason = get_ban_info(callback.from_user.id)
    await callback.answer(f"⛔ Вы заблокированы!\nПричина: {reason}", show_alert=True)


# --- 1. Старт и вход в меню ---
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    user_id = message.from_user.id
    username = message.from_user.username

    referrer_id = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_candidate = args[1].replace("ref_", "")
        if ref_candidate.isdigit() and int(ref_candidate) != user_id:
            referrer_id = int(ref_candidate)

    is_new = add_user(user_id=user_id, username=username, referrer_id=referrer_id)

    if is_new and referrer_id:
        update_balance(referrer_id, REFERRAL_REWARD_STARS)
        try:
            await bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎁 <b>Новый реферал!</b>\n"
                    f"Пользователь @{username or user_id} присоединился по вашей ссылке.\n"
                    f"Вам начислено: <b>+{REFERRAL_REWARD_STARS} ⭐</b>"
                ),
                parse_mode="HTML",
            )
        except TelegramAPIError as err:
            logger.info("Не удалось уведомить реферера %s: %s", referrer_id, err)

    subscribed, unsubs = await check_user_subscriptions(bot, user_id, check_type="bot")
    if not subscribed:
        text = "⚠️ <b>Для использования бота необходимо подписаться на наши каналы:</b>"
        await message.answer(
            text,
            reply_markup=get_sub_check_keyboard(unsubs, "bot", "basket"),
            parse_mode="HTML",
        )
        return

    user = get_user(user_id)
    balance = user["balance"] if user else 0
    claimed = bool(user["chat_reward_claimed"]) if user else False
    bot_username = await get_bot_username(bot)

    cooldown = get_free_cooldown_left(user_id, "basket")
    extra = get_extra_attempts(user_id, "basket")
    text = format_card_text("basket", balance)
    keyboard = get_game_keyboard("basket", user_id, bot_username, cooldown, claimed, extra)

    await message.answer(text=text, reply_markup=keyboard)


# --- 2. Проверка подписки ---
@router.callback_query(F.data.startswith("sub_check:"))
async def handle_sub_check(callback: CallbackQuery, bot: Bot):
    _, check_type, game_key = callback.data.split(":")
    user_id = callback.from_user.id

    subscribed, unsubs = await check_user_subscriptions(bot, user_id, check_type=check_type)
    if not subscribed:
        await callback.answer("❌ Вы подписались не на все каналы!", show_alert=True)
        return

    await callback.answer("✅ Подписка подтверждена!")
    user = get_user(user_id)
    balance = user["balance"] if user else 0
    claimed = bool(user["chat_reward_claimed"]) if user else False
    bot_username = await get_bot_username(bot)

    cooldown = get_free_cooldown_left(user_id, game_key)
    extra = get_extra_attempts(user_id, game_key)
    text = format_card_text(game_key, balance)
    keyboard = get_game_keyboard(game_key, user_id, bot_username, cooldown, claimed, extra)

    await callback.message.edit_text(text=text, reply_markup=keyboard)


# --- 3. Навигация между играми ---
@router.callback_query(F.data.startswith("nav:"))
async def handle_navigation(callback: CallbackQuery, bot: Bot):
    game_key = callback.data.split(":")[1]
    user_id = callback.from_user.id
    user = get_user(user_id)
    balance = user["balance"] if user else 0
    claimed = bool(user["chat_reward_claimed"]) if user else False
    bot_username = await get_bot_username(bot)

    cooldown = get_free_cooldown_left(user_id, game_key)
    extra = get_extra_attempts(user_id, game_key)
    text = format_card_text(game_key, balance)
    keyboard = get_game_keyboard(game_key, user_id, bot_username, cooldown, claimed, extra)

    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramAPIError:
        pass
    await callback.answer()


# --- 4. Бесплатная игра (Раз в 3 часа) ---
@router.callback_query(F.data.startswith("play_free:"))
async def handle_play_free(callback: CallbackQuery, bot: Bot):
    game_key = callback.data.split(":")[1]
    user_id = callback.from_user.id

    if user_id in active_players:
        await callback.answer("Броски уже выполняются! Подождите.", show_alert=True)
        return

    subscribed, unsubs = await check_user_subscriptions(bot, user_id, check_type="free_game")
    if not subscribed:
        await callback.answer("Для получения бесплатной попытки подпишитесь на каналы!", show_alert=True)
        text = "🎁 <b>Для получения бесплатной попытки подпишитесь на каналы:</b>"
        await callback.message.answer(
            text,
            reply_markup=get_sub_check_keyboard(unsubs, "free_game", game_key),
            parse_mode="HTML",
        )
        return

    cooldown = get_free_cooldown_left(user_id, game_key)
    if cooldown > 0:
        await callback.answer(f"Бесплатная игра доступна раз в 3 часа! Подождите {format_time_left(cooldown)}.",
                              show_alert=True)
        return

    set_free_game_used_now(user_id, game_key)
    g = GAMES[game_key]
    shots = g["shots_count"]

    await callback.answer(f"Запуск {shots} бесплатных бросков!")

    user = get_user(user_id)
    balance = user["balance"] if user else 0
    claimed = bool(user["chat_reward_claimed"]) if user else False
    extra = get_extra_attempts(user_id, game_key)
    bot_username = await get_bot_username(bot)

    new_cooldown = 3 * 3600
    text = format_card_text(game_key, balance)
    keyboard = get_game_keyboard(game_key, user_id, bot_username, new_cooldown, claimed, extra)
    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramAPIError:
        pass

    await run_game_series(bot, callback.message.chat.id, user_id, game_key, shots, callback.from_user.username)


@router.callback_query(F.data.startswith("cooldown_info:"))
async def handle_cooldown_info(callback: CallbackQuery):
    seconds = int(callback.data.split(":")[1])
    await callback.answer(f"⏳ Бесплатная игра доступна раз в 3 часа!\nОсталось ждать: {format_time_left(seconds)}",
                          show_alert=True)


# --- 5. Попытки от администрации ---
@router.callback_query(F.data.startswith("play_extra:"))
async def handle_play_extra(callback: CallbackQuery, bot: Bot):
    game_key = callback.data.split(":")[1]
    user_id = callback.from_user.id

    if user_id in active_players:
        await callback.answer("Броски уже выполняются! Подождите.", show_alert=True)
        return

    extra = get_extra_attempts(user_id, game_key)
    if extra <= 0:
        await callback.answer("У вас нет бонусных попыток от админа!", show_alert=True)
        return

    add_extra_attempts(user_id, game_key, -1)
    new_extra = extra - 1

    g = GAMES[game_key]
    shots = g["shots_count"]

    await callback.answer(f"Запуск! Осталось попыток: {new_extra}")

    user = get_user(user_id)
    balance = user["balance"] if user else 0
    claimed = bool(user["chat_reward_claimed"]) if user else False
    cooldown = get_free_cooldown_left(user_id, game_key)
    bot_username = await get_bot_username(bot)

    text = format_card_text(game_key, balance)
    keyboard = get_game_keyboard(game_key, user_id, bot_username, cooldown, claimed, new_extra)
    try:
        await callback.message.edit_text(text=text, reply_markup=keyboard)
    except TelegramAPIError:
        pass

    await run_game_series(bot, callback.message.chat.id, user_id, game_key, shots, callback.from_user.username)


# --- 6. Покупка попыток: проверка баланса или send_invoice ---
@router.callback_query(F.data.startswith("buy_attempt:"))
async def handle_buy_attempt(callback: CallbackQuery, bot: Bot):
    _, game_key, count_str, stars_str = callback.data.split(":")
    count = int(count_str)
    stars = int(stars_str)
    user_id = callback.from_user.id
    g = GAMES[game_key]

    user = get_user(user_id)
    current_balance = user["balance"] if user else 0

    if current_balance >= stars:
        update_balance(user_id, -stars)
        new_balance = current_balance - stars

        await callback.answer(f"Списано {stars} ⭐ с баланса бота!")
        await callback.message.answer(
            f"💳 Оплачено с баланса бота: <b>{stars} ⭐</b>.\nЗапускаем ваши {count} {g['single_name'] if count == 1 else g['item_name']}:",
            parse_mode="HTML")

        cooldown = get_free_cooldown_left(user_id, game_key)
        extra = get_extra_attempts(user_id, game_key)
        claimed = bool(user["chat_reward_claimed"]) if user else False
        bot_username = await get_bot_username(bot)

        text = format_card_text(game_key, new_balance)
        keyboard = get_game_keyboard(game_key, user_id, bot_username, cooldown, claimed, extra)
        try:
            await callback.message.edit_text(text=text, reply_markup=keyboard)
        except TelegramAPIError:
            pass

        await run_game_series(bot, callback.message.chat.id, user_id, game_key, count, callback.from_user.username)
        return

    label_text = f"{count} {g['single_name'] if count == 1 else g['item_name']}"
    prices = [LabeledPrice(label=label_text, amount=stars)]

    await bot.send_invoice(
        chat_id=user_id,
        title=f"Покупка: {g['title']}",
        description=f"Приобретение {count} {g['single_name'] if count == 1 else g['item_name']} для игры. Серия запустится сразу после оплаты!",
        payload=f"buy_play:{game_key}:{count}:{stars}",
        currency="XTR",
        prices=prices,
        provider_token="",
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload
    parts = payload.split(":")
    if len(parts) == 4 and parts[0] == "buy_play":
        game_key = parts[1]
        count = int(parts[2])
        stars = int(parts[3])
        user_id = message.from_user.id
        g = GAMES[game_key]

        await message.answer(
            f"✅ Оплата через Telegram Stars прошла успешно! Списано: {stars} ⭐.\nЗапускаем ваши {count} {g['single_name'] if count == 1 else g['item_name']}:"
        )
        await run_game_series(bot, message.chat.id, user_id, game_key, count, message.from_user.username)


# --- 7. Раздел «Мои заявки» для игроков ---
@router.callback_query(F.data == "my_claims")
async def handle_user_claims(callback: CallbackQuery):
    user_id = callback.from_user.id
    claims = get_user_claims(user_id)

    if not claims:
        await callback.answer("У вас пока нет заявок на подарки!", show_alert=True)
        return

    text = "📋 <b>Ваши заявки на получение подарков:</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for c in claims:
        status_map = {
            "pending": "В ожидании ⏳ (выдача от 15 мин до 7 дней)",
            "approved": "Одобрена ✅ (Ожидайте выдачи)",
            "rejected": "Отклонена ❌"
        }
        st = status_map.get(c["status"], c["status"])
        text += (
            f"<b>Заявка #{c['id']}</b>\n"
            f"🎁 Приз: <b>{c['prize_name']}</b>\n"
            f"🎮 Режим: {c['game_title']}\n"
            f"📅 Дата: {c['created_at']}\n"
            f"📊 Статус: <b>{st}</b>\n"
            "──────────────────────\n"
        )

    await callback.message.edit_text(text, reply_markup=get_back_keyboard("basket"), parse_mode="HTML")
    await callback.answer()


# --- 8. Добавление в чаты (+3 ⭐) ---
@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=MEMBER | ADMINISTRATOR)
)
async def handle_chat_addition(event: ChatMemberUpdated, bot: Bot):
    chat = event.chat
    if chat.type not in ["group", "supergroup"]:
        return

    try:
        admins = await bot.get_chat_administrators(chat.id)
        owner = next(
            (admin.user for admin in admins if admin.status in ["creator", ChatMemberStatus.CREATOR]), None
        )
        if not owner:
            return

        if can_claim_chat_reward(owner.id, chat.id):
            claim_chat_reward(owner.id, chat.id)
            await bot.send_message(
                chat_id=owner.id,
                text=(
                    f"🎉 <b>Награда начислена!</b>\n"
                    f"Вы добавили бота в свой чат <b>«{escape(chat.title)}»</b>.\n"
                    f"Начислено: <b>+{CHAT_REWARD_STARS} ⭐</b> на баланс!\n\n"
                    f"<i>(Награда выдаётся строго 1 раз на аккаунт)</i>"
                ),
                parse_mode="HTML",
            )
        else:
            try:
                await bot.send_message(
                    chat_id=owner.id,
                    text="⚠️ Вы уже получали награду за привязку чата или данный чат уже использовался ранее. Повторное начисление невозможно.",
                )
            except TelegramAPIError:
                pass
    except TelegramAPIError as err:
        logger.warning("Ошибка проверки администраторов чата %s: %s", chat.id, err)


# --- 9. Реферальный раздел (+2 ⭐) ---
@router.callback_query(F.data == "ref_section")
async def show_ref_section(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    bot_username = await get_bot_username(bot)
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    ref_count = get_referrals_count(user_id)

    text = (
        "🤝 <b>Реферальная программа</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Приглашайте друзей и получайте <b>+{REFERRAL_REWARD_STARS} ⭐</b> за каждого нового пользователя!\n\n"
        f"👥 Вы пригласили: <b>{ref_count}</b> чел.\n\n"
        f"🔗 <b>Ваша ссылка для приглашения:</b>\n<code>{ref_link}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Скопируйте ссылку и отправьте её другу!"
    )
    await callback.message.edit_text(
        text=text, reply_markup=get_back_keyboard("basket"), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "chat_claimed_info")
async def handle_chat_claimed_info(callback: CallbackQuery):
    await callback.answer(f"Вы уже получили разовую награду +{CHAT_REWARD_STARS} ⭐ за чат!", show_alert=True)


# =========================================================================
# ======================== АДМИН-ПАНЕЛЬ ===================================
# =========================================================================

@router.message(Command("admin"))
@router.callback_query(F.data == "admin_panel")
async def handle_admin_main(event: Message | CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    if user_id != ADMIN_ID:
        if isinstance(event, CallbackQuery):
            await event.answer("Доступ ограничен.", show_alert=True)
        return

    await state.clear()
    users_count = get_total_users_count()
    pending = get_pending_claims_count()
    text = (
        "👑 <b>Панель Управления Администратора</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: <b>{users_count}</b>\n"
        f"⏳ Ожидающих заявок на призы: <b>{pending}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите нужное действие ниже:"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(
            text, reply_markup=get_admin_main_keyboard(pending), parse_mode="HTML"
        )
        await event.answer()
    else:
        await event.answer(
            text, reply_markup=get_admin_main_keyboard(pending), parse_mode="HTML"
        )


@router.callback_query(F.data == "adm:cancel")
async def handle_admin_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    pending = get_pending_claims_count()
    await callback.message.edit_text(
        "❌ Действие отменено.", reply_markup=get_admin_main_keyboard(pending)
    )
    await callback.answer()


# --- Очистка заявок ---
@router.callback_query(F.data == "adm:clear_claims_confirm")
async def adm_clear_claims_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    text = (
        "⚠️ <b>ВЫ УВЕРЕНЫ, ЧТО ХОТИТЕ УДАЛИТЬ ВСЕ ЗАЯВКИ?</b>\n\n"
        "• Все созданные заявки будут безвозвратно удалены из базы данных.\n"
        "• Нумерация заявок начнётся <b>заново с #1</b>."
    )
    await callback.message.edit_text(text, reply_markup=get_admin_clear_confirm_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm:clear_claims_execute")
async def adm_clear_claims_execute(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    clear_all_claims()
    await callback.answer("Все заявки удалены! Нумерация сброшена в #1.", show_alert=True)
    users_count = get_total_users_count()
    text = (
        "👑 <b>Панель Управления Администратора</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: <b>{users_count}</b>\n"
        f"⏳ Ожидающих заявок на призы: <b>0</b>\n"
        f"⚙️ База данных: <code>sqlite3 (Online)</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>База заявок успешно очищена. Следующая заявка будет #1.</b>"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_main_keyboard(0), parse_mode="HTML")


# --- Тестовая победа ---
@router.callback_query(F.data == "adm:test_win")
async def adm_test_win(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        return

    user_id = callback.from_user.id
    username = callback.from_user.username
    prize = random.choice(PRIZES)
    claim_id = create_prize_claim(user_id=user_id, username=username, game_title="🏀 Баскет (ТЕСТ)", prize_name=prize)

    await callback.answer("Тестовая заявка создана!")
    await callback.message.answer(
        f"🎉 <b>ТЕСТОВЫЙ ВЫИГРЫШ!</b>\n\n"
        f"🎁 Приз: <b>{prize}</b>\n"
        f"📋 Заявка: <code>#{claim_id}</code>\n"
        "Заявка поступила в список заявок!",
        parse_mode="HTML"
    )

    pending = get_pending_claims_count()
    try:
        await callback.message.edit_text(
            "👑 <b>Панель Администратора</b>\n\nТестовая заявка успешно добавлена в очередь!",
            reply_markup=get_admin_main_keyboard(pending),
            parse_mode="HTML"
        )
    except TelegramAPIError:
        pass


# --- Список заявок ---
@router.callback_query(F.data.startswith("adm:claims:"))
async def adm_claims_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    page = int(callback.data.split(":")[2])
    claims, total = get_claims_page(page=page, per_page=8)

    if total == 0:
        await callback.answer("Заявок пока нет!", show_alert=True)
        return

    text = (
        "📋 <b>Список заявок на выдачу призов</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Статусы: ⏳ — ожидает, ✅ — выдано, ❌ — отклонено.\n"
        "Нажмите на заявку для просмотра и принятия решения:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_claims_keyboard(claims, page, total, per_page=8),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_claim_view:"))
async def adm_claim_view_item(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    _, claim_id_str, page_str = callback.data.split(":")
    claim_id = int(claim_id_str)
    page = int(page_str)

    claim = get_claim_by_id(claim_id)
    if not claim:
        await callback.answer("Заявка не найдена!", show_alert=True)
        return

    status_name = "⏳ В ожидании" if claim["status"] == "pending" else (
        "✅ Одобрена / Выдана" if claim["status"] == "approved" else "❌ Отклонена")

    text = (
        f"📋 <b>Карточка Заявки #{claim['id']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Игрок:</b> @{claim['username']} (ID: <code>{claim['user_id']}</code>)\n"
        f"🎮 <b>Режим:</b> {claim['game_title']}\n"
        f"🎁 <b>Приз:</b> <b>{claim['prize_name']}</b>\n"
        f"📅 <b>Дата:</b> {claim['created_at']}\n"
        f"📊 <b>Статус:</b> {status_name}\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_claim_action_keyboard(claim_id, page, claim["status"]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_claim_act:"))
async def adm_claim_perform_action(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        return
    _, claim_id_str, action, page_str = callback.data.split(":")
    claim_id = int(claim_id_str)
    page = int(page_str)

    claim = get_claim_by_id(claim_id)
    if not claim:
        await callback.answer("Заявка не найдена!", show_alert=True)
        return

    if action == "approve":
        update_claim_status(claim_id, "approved")
        try:
            user_notify = (
                f"🎉 <b>Ваша заявка #{claim_id} на {claim['prize_name']} одобрена!</b>\n\n"
                "📦 <b>Ожидайте выдачи</b> администратором."
            )
            await bot.send_message(chat_id=claim["user_id"], text=user_notify, parse_mode="HTML")
        except TelegramAPIError as err:
            logger.warning("Не удалось отправить уведомление пользователю: %s", err)
        await callback.answer("✅ Заявка одобрена, пользователь уведомлен!")

    elif action == "reject":
        update_claim_status(claim_id, "rejected")
        try:
            user_notify = (
                f"❌ <b>Ваша заявка #{claim_id} на {claim['prize_name']} отклонена</b> администратором."
            )
            await bot.send_message(chat_id=claim["user_id"], text=user_notify, parse_mode="HTML")
        except TelegramAPIError:
            pass
        await callback.answer("❌ Заявка отклонена!", show_alert=True)

    claims, total = get_claims_page(page=page, per_page=8)
    text = (
        "📋 <b>Список заявок на выдачу призов</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Статусы: ⏳ — ожидает, ✅ — выдано, ❌ — отклонено.\n"
        "Нажмите на заявку для просмотра и принятия решения:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_claims_keyboard(claims, page, total, per_page=8),
        parse_mode="HTML"
    )


# --- Выдача звёзд на баланс ---
@router.callback_query(F.data == "adm:give_stars")
async def adm_give_stars_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.give_stars_target)
    await callback.message.edit_text(
        "⭐ <b>Введите @username или ID пользователя для начисления звёзд:</b>",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.give_stars_target)
async def adm_give_stars_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден в БД. Попробуйте снова или нажмите отмену:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    await state.update_data(target_id=user["user_id"], target_name=user["username"] or user["user_id"])
    await state.set_state(AdminStates.give_stars_count)
    await message.answer(
        f"👤 Пользователь: <b>{user['username'] or user['user_id']}</b> (Текущий баланс: {user['balance']} ⭐)\n"
        "Введите количество звёзд для начисления (положительное число):",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.give_stars_count)
async def adm_give_stars_apply(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    val = message.text.strip()
    if not val.isdigit() or int(val) <= 0:
        await message.answer("❌ Введите корректное положительное число!", reply_markup=get_cancel_admin_keyboard())
        return

    count = int(val)
    data = await state.get_data()
    target_id = data["target_id"]
    update_balance(target_id, count)

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎁 <b>Администратор начислил вам звёзды!</b>\nНа ваш баланс поступило: <b>+{count} ⭐</b>.",
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass

    pending = get_pending_claims_count()
    await message.answer(
        f"✅ Пользователю <code>{target_id}</code> успешно начислено <b>+{count} ⭐</b>!",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )
    await state.clear()


# --- Снятие звёзд с баланса ---
@router.callback_query(F.data == "adm:take_stars")
async def adm_take_stars_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.take_stars_target)
    await callback.message.edit_text(
        "🔻 <b>Введите @username или ID пользователя для списания звёзд:</b>",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.take_stars_target)
async def adm_take_stars_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден в БД. Попробуйте снова или нажмите отмену:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    await state.update_data(target_id=user["user_id"], target_name=user["username"] or user["user_id"])
    await state.set_state(AdminStates.take_stars_count)
    await message.answer(
        f"👤 Пользователь: <b>{user['username'] or user['user_id']}</b> (Текущий баланс: {user['balance']} ⭐)\n"
        "Введите количество звёзд, которое нужно <b>забрать</b> (положительное число):",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.take_stars_count)
async def adm_take_stars_apply(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    val = message.text.strip()
    if not val.isdigit() or int(val) <= 0:
        await message.answer("❌ Введите положительное целое число для списания!",
                             reply_markup=get_cancel_admin_keyboard())
        return

    count = int(val)
    data = await state.get_data()
    target_id = data["target_id"]

    update_balance(target_id, -count)

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"⚠️ <b>Администратор списал с вашего баланса:</b> <b>-{count} ⭐</b>.",
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass

    pending = get_pending_claims_count()
    await message.answer(
        f"✅ С баланса пользователя <code>{target_id}</code> успешно списано <b>-{count} ⭐</b>!",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )
    await state.clear()


# --- Бан с указанием причины ---
@router.callback_query(F.data == "adm:ban")
async def adm_ban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.ban_user_target)
    await callback.message.edit_text(
        "⛔ <b>Введите @username или ID пользователя для блокировки:</b>",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.ban_user_target)
async def adm_ban_get_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден. Попробуйте снова или нажмите отмену:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    await state.update_data(target_id=user["user_id"], target_name=user["username"] or user["user_id"])
    await state.set_state(AdminStates.ban_user_reason)
    await message.answer(
        f"👤 Блокировка игрока: <b>{user['username'] or user['user_id']}</b> (ID: <code>{user['user_id']}</code>).\n\n"
        "💬 <b>Введите причину блокировки</b> (она будет видна игроку):",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.ban_user_reason)
async def adm_ban_apply_reason(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    reason = message.text.strip()
    data = await state.get_data()
    target_id = data["target_id"]
    target_name = data["target_name"]

    set_ban_status(target_id, is_banned=True, reason=reason)

    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                f"⛔ <b>Ваш аккаунт заблокирован администратором!</b>\n"
                f"💬 <b>Причина:</b> <i>{escape(reason)}</i>"
            ),
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass

    pending = get_pending_claims_count()
    await message.answer(
        f"✅ Пользователь <b>{target_name}</b> (ID: <code>{target_id}</code>) заблокирован!\n"
        f"💬 Причина: <i>{escape(reason)}</i>",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )
    await state.clear()


# --- Разбан ---
@router.callback_query(F.data == "adm:unban")
async def adm_unban_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.unban_user_target)
    await callback.message.edit_text(
        "✅ Введите <b>@username</b> или <b>ID пользователя</b> для разблокировки:",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.unban_user_target)
async def adm_unban_process(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден. Попробуйте снова:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    set_ban_status(user["user_id"], is_banned=False, reason=None)
    try:
        await bot.send_message(
            chat_id=user["user_id"],
            text="🎉 Ваш аккаунт разблокирован! Нажмите /start для продолжения.",
        )
    except TelegramAPIError:
        pass

    pending = get_pending_claims_count()
    await message.answer(
        f"✅ Пользователь <b>{user['username'] or user['user_id']}</b> (ID: <code>{user['user_id']}</code>) успешно разблокирован!",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )
    await state.clear()


# --- Выдача попыток ---
@router.callback_query(F.data == "adm:give_attempts")
async def adm_give_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.give_attempts_target)
    await callback.message.edit_text(
        "🎁 Введите <b>@username</b> или <b>ID пользователя</b>, которому нужно начислить попытки:",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.give_attempts_target)
async def adm_give_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден в БД. Попробуйте снова:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    await state.update_data(
        target_id=user["user_id"], target_name=user["username"] or user["user_id"]
    )
    await state.set_state(AdminStates.give_attempts_game)

    buttons = []
    for k, v in GAMES.items():
        buttons.append(
            [InlineKeyboardButton(text=v["title"], callback_data=f"adm_give_g:{k}")]
        )
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")])

    await message.answer(
        f"👤 Игрок: <b>{user['username'] or user['user_id']}</b>\n"
        "Выберите режим игры для начисления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_give_g:"))
async def adm_give_game_chosen(callback: CallbackQuery, state: FSMContext):
    game_key = callback.data.split(":")[1]
    await state.update_data(game_key=game_key)
    await state.set_state(AdminStates.give_attempts_count)
    g = GAMES[game_key]
    await callback.message.edit_text(
        f"Режим: <b>{g['title']}</b>\nВведите количество начисляемых попыток (число):",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.give_attempts_count)
async def adm_give_count_apply(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer(
            "❌ Введите положительное целое число!",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    count = int(message.text)
    data = await state.get_data()
    target_id = data["target_id"]
    game_key = data["game_key"]
    g = GAMES[game_key]

    add_extra_attempts(target_id, game_key, count)

    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                f"🎁 <b>Администратор начислил вам бонусные попытки!</b>\n\n"
                f"В режиме <b>{g['title']}</b> вам начислено: <b>+{count}</b> попыток!\n"
                f"В меню появилась кнопка «🎁 Бесплатные попытки от админа». Заходите играть!"
            ),
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass

    pending = get_pending_claims_count()
    await message.answer(
        f"✅ Успешно начислено <b>{count}</b> попыток в режим <b>{g['title']}</b> для пользователя <code>{target_id}</code>!",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )
    await state.clear()


# --- Рассылка всем ---
@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.broadcast_text)
    await callback.message.edit_text(
        "📢 <b>Введите текст сообщения для рассылки всем пользователям:</b>",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.broadcast_text)
async def adm_broadcast_run(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text
    users = get_all_users()
    count_success = 0
    await message.answer(f"⏳ Начинаю рассылку на {len(users)} пользователей...")

    for u in users:
        try:
            await bot.send_message(
                chat_id=u["user_id"], text=text, parse_mode="HTML"
            )
            count_success += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            pass

    await state.clear()
    pending = get_pending_claims_count()
    await message.answer(
        f"✅ Рассылка завершена!\nУспешно доставлено: <b>{count_success} / {len(users)}</b>",
        reply_markup=get_admin_main_keyboard(pending),
        parse_mode="HTML",
    )


# --- Личное сообщение ---
@router.callback_query(F.data == "adm:direct_msg")
async def adm_direct_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.direct_msg_target)
    await callback.message.edit_text(
        "✉️ Введите <b>@username</b> или <b>ID пользователя</b>, которому хотите отправить сообщение:",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.direct_msg_target)
async def adm_direct_get_target(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    user = get_user_by_query(message.text)
    if not user:
        await message.answer(
            "❌ Пользователь не найден в базе данных! Попробуйте снова или нажмите отмену:",
            reply_markup=get_cancel_admin_keyboard(),
        )
        return

    await state.update_data(
        target_id=user["user_id"], target_name=user["username"] or user["user_id"]
    )
    await state.set_state(AdminStates.direct_msg_text)
    await message.answer(
        f"👤 Пользователь найден: <b>{user['username'] or user['user_id']}</b> (ID: <code>{user['user_id']}</code>).\n"
        "Введите текст сообщения:",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.direct_msg_text)
async def adm_direct_send(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_id = data["target_id"]
    pending = get_pending_claims_count()
    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"📩 <b>Сообщение от администрации:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer(
            f"✅ Сообщение успешно доставлено пользователю <code>{target_id}</code>!",
            reply_markup=get_admin_main_keyboard(pending),
            parse_mode="HTML",
        )
    except TelegramAPIError as err:
        await message.answer(
            f"❌ Ошибка отправки сообщения: {err}",
            reply_markup=get_admin_main_keyboard(pending),
        )
    await state.clear()


# --- Управление каналами ---
@router.callback_query(F.data == "adm:channels")
async def adm_channels_list(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.clear()
    channels = get_channels(active_only=False)
    text = (
        "⚙️ <b>Управление обязательными подписками</b>\n\n"
        "Здесь можно настроить каналы:\n"
        "• <b>Бот</b> — обязательны для входа и использования бота.\n"
        "• <b>Попытка</b> — обязательны для получения бесплатной серии бросков.\n\n"
        "Нажмите на канал для изменения статуса или удаления:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_channels_keyboard(channels),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "adm:add_channel")
async def adm_add_channel_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminStates.add_channel_title)
    await callback.message.edit_text(
        "📝 Введите <b>название канала</b> (отображаемое на кнопке):",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.add_channel_title)
async def adm_add_channel_title_step(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.add_channel_username)
    await message.answer(
        "🆔 Введите <b>юзернейм канала</b> (например <code>durov</code> или <code>@durov</code>):\n"
        "<i>(Бот должен быть предварительно добавлен в канал администратором!)</i>",
        reply_markup=get_cancel_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(AdminStates.add_channel_username)
async def adm_add_channel_username_step(message: Message, state: FSMContext, bot: Bot):
    raw_input = message.text.strip()
    raw_username = raw_input.replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip()

    try:
        chat = await bot.get_chat(f"@{raw_username}")
        actual_username = chat.username if chat.username else raw_username
        await state.update_data(channel_username=actual_username)
    except TelegramAPIError:
        await message.answer(
            f"❌ Не удалось получить доступ к каналу <code>@{raw_username}</code>.\n"
            f"Убедитесь, что канал существует и бот назначен в нём администратором!\n\n"
            "Попробуйте ввести юзернейм снова:",
            reply_markup=get_cancel_admin_keyboard(),
            parse_mode="HTML"
        )
        return

    await state.set_state(AdminStates.add_channel_type)
    type_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Для доступа к боту", callback_data="adm_ch_type:bot"
                ),
                InlineKeyboardButton(
                    text="🔥 Для бесплатной попытки",
                    callback_data="adm_ch_type:free_game",
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]
    )
    await message.answer(
        f"✅ Канал найден: <b>{escape(chat.title)}</b> (<code>@{actual_username}</code>)\n\n"
        "🎯 Выберите <b>тип подписки</b>:",
        reply_markup=type_keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_ch_type:"))
async def adm_add_channel_finalize(callback: CallbackQuery, state: FSMContext):
    check_type = callback.data.split(":")[1]
    data = await state.get_data()
    add_channel(
        channel_username=data["channel_username"],
        title=data["title"],
        check_type=check_type,
    )
    await state.clear()
    await callback.answer("✅ Канал добавлен!")
    channels = get_channels(active_only=False)
    await callback.message.edit_text(
        "✅ <b>Канал успешно добавлен в систему ОП!</b>",
        reply_markup=get_admin_channels_keyboard(channels),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_ch_view:"))
async def adm_channel_item_view(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[1])
    channels = get_channels(active_only=False)
    ch = next((c for c in channels if c["id"] == ch_id), None)
    if not ch:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    status = "🟢 Активен" if ch["is_active"] else "🔴 Отключен"
    type_name = (
        "Для использования бота"
        if ch["check_type"] == "bot"
        else "Для бесплатной попытки"
    )

    username_clean = ch['channel_username']
    channel_url = f"https://t.me/{username_clean}"
    safe_title = escape(str(ch['title']))

    text = (
        f"📢 <b>Кнопка:</b> {safe_title}\n"
        f"🔗 <b>Юзернейм:</b> <code>@{username_clean}</code>\n"
        f"🌐 <b>Ссылка:</b> <a href=\"{channel_url}\">{channel_url}</a>\n"
        f"🎯 <b>Назначение:</b> {type_name}\n"
        f"Статус: <b>{status}</b>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=get_admin_channel_item_keyboard(
            ch["id"], bool(ch["is_active"])
        ),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ch_toggle:"))
async def adm_channel_toggle(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[1])
    toggle_channel_status(ch_id)
    await callback.answer("Статус канала изменён!")
    channels = get_channels(active_only=False)
    await callback.message.edit_text(
        "⚙️ <b>Список каналов обновлён:</b>",
        reply_markup=get_admin_channels_keyboard(channels),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(F.data.startswith("adm_ch_delete:"))
async def adm_channel_delete(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[1])
    delete_channel(ch_id)
    await callback.answer("Канал удалён!", show_alert=True)
    channels = get_channels(active_only=False)
    await callback.message.edit_text(
        "⚙️ <b>Канал удалён. Список каналов:</b>",
        reply_markup=get_admin_channels_keyboard(channels),
        parse_mode="HTML",
    )