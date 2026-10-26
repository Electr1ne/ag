from typing import List, Tuple

def check_single_dice(game_key: str, val: int, is_single_attempt: bool = False) -> bool:
    if game_key == "football":
        return val == 5  # Идеальный гол в девятку (повышенная сложность)
    elif game_key == "basket":
        return val == 5  # Чистое попадание в корзину
    elif game_key == "darts":
        return val == 6  # Яблочко
    elif game_key == "bowling":
        return val == 6  # Страйк
    elif game_key == "slots":
        if is_single_attempt:
            return val == 64  # Строго 777
        return val in [1, 22, 43, 64]
    elif game_key == "dice":
        if is_single_attempt:
            return val == 6   # Строго 6
        return True
    return False

def evaluate_full_series(game_key: str, results: List[int]) -> Tuple[bool, str]:
    total_required = len(results)

    # 1. Если 1 попытка
    if total_required == 1:
        val = results[0]
        if check_single_dice(game_key, val, is_single_attempt=True):
            if game_key == "slots":
                return True, "🔥 ВЫПАЛО 777! Джекпот со слота! Ты забираешь подарок 🎁"
            elif game_key == "dice":
                return True, "🔥 ВЫПАЛА ШЕСТЕРКА (6)! Идеальный бросок! Ты забираешь подарок 🎁"
            return True, "🔥 ТОЧНОЕ ПОПАДАНИЕ! Ты забираешь подарок 🎁"
        else:
            if game_key == "slots":
                return False, "❌ Не выпало 777! Попробуйте еще раз!"
            elif game_key == "dice":
                return False, "❌ Не выпала 6! Для победы нужна только шестерка!"
            return False, "❌ Промах! Подарок ускользнул, попробуйте еще раз!"

    # 2. Если несколько попыток (серия)
    if game_key == "dice":
        if len(set(results)) == 1:
            return True, f"🎉 ВСЕ ЧИСЛА ОДИНАКОВЫЕ ({results[0]})! СУПЕРПРИЗ ВАШ 🎁"
        return False, f"❌ Выпали разные числа: {results}. Все кубики должны совпасть!"

    success_count = sum(1 for val in results if check_single_dice(game_key, val, is_single_attempt=False))

    if success_count == total_required:
        return True, f"🔥 ИДЕАЛЬНО! {success_count} из {total_required} попаданий! Победа 🎁"

    if game_key == "slots":
        return False, "❌ Не на всех спинах выпали одинаковые символы! Попробуйте еще раз!"

    return False, f"❌ Не все броски были точными: {success_count} из {total_required}."