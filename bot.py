import json
import os
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

DATA_FILE = 'users_data.json'
TOKEN = os.getenv('BOT_TOKEN', '8824905296:AAH5rcrPFvjhUQ8X_GHR-Xl5F8D0_XHRIco')
PROXY_URL = None


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("Узнать долг"), KeyboardButton("Добавить сумму")],
        [KeyboardButton("Настроить выплату"), KeyboardButton("Выплата")],
        [KeyboardButton("Сбросить всё")]
    ], resize_keyboard=True)


def get_freq_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("Каждые N дней/часов/минут")],
        [KeyboardButton("Каждую неделю в определенный день")],
        [KeyboardButton("Каждый месяц в определенную дату")],
        [KeyboardButton("Назад в главное меню")]
    ], resize_keyboard=True)


def get_back_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("Назад в главное меню")]
    ], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    if user_id not in data:
        data[user_id] = {'base_amount': 0, 'frequency_type': 'days', 'frequency_value': 0, 'frequency_day': None,
                         'extra_amount': 0, 'total_debt': 0}
        save_data(data)
    await update.message.reply_text("Привет! Я бот для учета карманных денег.", reply_markup=get_main_keyboard())


# === ОДИН универсальный обработчик всех текстовых сообщений ===
async def handle_all_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    data = load_data()
    mode = context.user_data.get('mode')

    # Кнопка "Назад" работает всегда
    if text == "Назад в главное меню":
        context.user_data.clear()
        await update.message.reply_text("Возврат в главное меню.", reply_markup=get_main_keyboard())
        return

    # === Кнопки главного меню ===
    if text == "Узнать долг":
        debt = data.get(user_id, {}).get('total_debt', 0)
        msg = "Папа тебе ничего не должен!" if debt == 0 else f"Текущий долг папы: {debt} руб."
        await update.message.reply_text(msg)
        return

    if text == "Добавить сумму":
        await update.message.reply_text("Введи сумму для добавления к долгу (например: 500)",
                                        reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'add'
        return

    if text == "Настроить выплату":
        await update.message.reply_text("Выбери тип периодичности:", reply_markup=get_freq_keyboard())
        context.user_data['mode'] = 'setup_freq'
        return

    if text == "Выплата":
        await update.message.reply_text("Введи сумму, которую папа перевел (например: 1000)",
                                        reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'pay'
        return

    if text == "Сбросить всё":
        data[user_id] = {'base_amount': 0, 'frequency_type': 'days', 'frequency_value': 0, 'frequency_day': None,
                         'extra_amount': 0, 'total_debt': 0}
        save_data(data)
        for job in context.job_queue.get_jobs_by_name(user_id):
            job.schedule_removal()
        await update.message.reply_text("Все данные сброшены!", reply_markup=get_main_keyboard())
        return

    # === Выбор типа периодичности ===
    if text == "Каждые N дней/часов/минут":
        context.user_data['freq_type'] = 'days'
        await update.message.reply_text(
            "Введи интервал:\n7 — каждые 7 дней\n12h — каждые 12 часов\n30m — каждые 30 минут",
            reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'setup_interval'
        return

    if text == "Каждую неделю в определенный день":
        context.user_data['freq_type'] = 'weekly'
        keyboard = [[InlineKeyboardButton(d, callback_data=f'day_{i}')] for i, d in
                    enumerate(['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'])]
        await update.message.reply_text("Выбери день недели:", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['mode'] = 'setup_day_inline'
        return

    if text == "Каждый месяц в определенную дату":
        context.user_data['freq_type'] = 'monthly'
        await update.message.reply_text("Введи число месяца (1-31):", reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'setup_day_number'
        return

    # === Обработка ввода в зависимости от режима ===
    if mode == 'add':
        try:
            amount = int(text)
            data[user_id]['total_debt'] += amount
            data[user_id]['extra_amount'] += amount
            save_data(data)
            await update.message.reply_text(f"Добавлено: {amount} руб. Долг: {data[user_id]['total_debt']} руб.",
                                            reply_markup=get_main_keyboard())
            context.user_data.pop('mode', None)
        except ValueError:
            await update.message.reply_text("Ошибка! Введи число.", reply_markup=get_back_keyboard())
        return

    if mode == 'pay':
        try:
            amount = int(text)
            if data[user_id]['total_debt'] >= amount:
                data[user_id]['total_debt'] -= amount
                save_data(data)
                await update.message.reply_text(f"Получено {amount} руб. Осталось: {data[user_id]['total_debt']} руб.",
                                                reply_markup=get_main_keyboard())
            else:
                await update.message.reply_text("Нельзя перевести больше долга!", reply_markup=get_back_keyboard())
            context.user_data.pop('mode', None)
        except ValueError:
            await update.message.reply_text("Ошибка! Введи число.", reply_markup=get_back_keyboard())
        return

    if mode == 'setup_interval':
        try:
            t = text.strip().lower()
            if t.endswith('h'):
                secs = int(t[:-1]) * 3600
                display = f"каждые {t[:-1]} часов"
            elif t.endswith('m'):
                secs = int(t[:-1]) * 60
                display = f"каждые {t[:-1]} минут"
            elif t.endswith('d'):
                secs = int(t[:-1]) * 86400
                display = f"каждые {t[:-1]} дней"
            else:
                secs = int(t) * 86400
                display = f"каждые {t} дней"

            context.user_data['interval_seconds'] = secs
            context.user_data['interval_display'] = display
            await update.message.reply_text("Введи сумму выплаты:", reply_markup=get_back_keyboard())
            context.user_data['mode'] = 'setup_amount'
        except ValueError:
            await update.message.reply_text("Ошибка! Введи число (например: 7, 12h, 30m)",
                                            reply_markup=get_back_keyboard())
        return

    if mode == 'setup_day_number':
        try:
            day = int(text) - 1
            if day < 0 or day > 30:
                raise ValueError
            context.user_data['frequency_day'] = day
            context.user_data['interval_display'] = f"каждого {text}-го числа месяца"
            await update.message.reply_text("Введи сумму выплаты:", reply_markup=get_back_keyboard())
            context.user_data['mode'] = 'setup_amount'
        except ValueError:
            await update.message.reply_text("Ошибка! Введи число от 1 до 31", reply_markup=get_back_keyboard())
        return

    if mode == 'setup_amount':
        try:
            amount = int(text)
            freq_type = context.user_data['freq_type']
            display = context.user_data['interval_display']

            data[user_id]['base_amount'] = amount
            data[user_id]['frequency_type'] = freq_type
            data[user_id]['frequency_day'] = context.user_data.get('frequency_day')
            save_data(data)

            for job in context.job_queue.get_jobs_by_name(user_id):
                job.schedule_removal()

            if freq_type == 'days':
                secs = context.user_data['interval_seconds']
                context.job_queue.run_repeating(add_money_job, interval=secs, first=secs, chat_id=user_id, name=user_id)
            elif freq_type == 'weekly':
                context.job_queue.run_repeating(check_weekly, interval=86400, first=3600, chat_id=user_id, name=user_id,
                                                data={'day': context.user_data['frequency_day'], 'amount': amount})
            elif freq_type == 'monthly':
                context.job_queue.run_repeating(check_monthly, interval=86400, first=3600, chat_id=user_id,
                                                name=user_id,
                                                data={'day': context.user_data['frequency_day'] + 1, 'amount': amount})

            await update.message.reply_text(f"Настроено! {amount} руб. {display}.", reply_markup=get_main_keyboard())
            context.user_data.clear()
        except ValueError:
            await update.message.reply_text("Ошибка! Введи число.", reply_markup=get_back_keyboard())
        return

    # Если ничего не подошло
    await update.message.reply_text("Не понимаю команду. Используй кнопки меню.", reply_markup=get_main_keyboard())


# === Обработчик выбора дня недели (inline) ===
async def handle_day_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = int(query.data.split('_')[1])
    context.user_data['frequency_day'] = day
    days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    context.user_data['interval_display'] = f"каждый {days[day]}"
    await query.message.reply_text("Введи сумму выплаты:", reply_markup=get_back_keyboard())
    context.user_data['mode'] = 'setup_amount'


# === Inline кнопки быстрого доступа ===
async def quick_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = load_data()

    if query.data == 'status':
        debt = data.get(user_id, {}).get('total_debt', 0)
        await query.message.reply_text("Папа ничего не должен!" if debt == 0 else f"Долг: {debt} руб.")
    elif query.data == 'add_extra':
        await query.message.reply_text("Введи сумму:", reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'add'
    elif query.data == 'pay':
        await query.message.reply_text("Введи сумму оплаты:", reply_markup=get_back_keyboard())
        context.user_data['mode'] = 'pay'


# === Job функции ===
async def add_money_job(context: ContextTypes.DEFAULT_TYPE):
    user_id = str(context.job.chat_id)
    data = load_data()
    if user_id in data:
        data[user_id]['total_debt'] += data[user_id]['base_amount']
        save_data(data)
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Начисление! +{data[user_id]['base_amount']} руб. Итого: {data[user_id]['total_debt']} руб.")


async def check_weekly(context: ContextTypes.DEFAULT_TYPE):
    if datetime.datetime.now().weekday() == context.job.data['day']:
        user_id = str(context.job.chat_id)
        data = load_data()
        data[user_id]['total_debt'] += context.job.data['amount']
        save_data(data)
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Начисление! +{context.job.data['amount']} руб. Итого: {data[user_id]['total_debt']} руб.")


async def check_monthly(context: ContextTypes.DEFAULT_TYPE):
    if datetime.datetime.now().day == context.job.data['day']:
        user_id = str(context.job.chat_id)
        data = load_data()
        data[user_id]['total_debt'] += context.job.data['amount']
        save_data(data)
        await context.bot.send_message(chat_id=user_id,
                                       text=f"Начисление! +{context.job.data['amount']} руб. Итого: {data[user_id]['total_debt']} руб.")


async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    for uid, ud in data.items():
        if ud['total_debt'] > 0:
            await context.bot.send_message(chat_id=uid, text=f"Напоминание: долг {ud['total_debt']} руб.!")


def main():
    if PROXY_URL:
        request = HTTPXRequest(proxy_url=PROXY_URL)
        app = Application.builder().token(TOKEN).request(request).build()
    else:
        app = Application.builder().token(TOKEN).build()

    # ВСЕ текстовые сообщения идут в ОДИН обработчик
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_text))
    app.add_handler(CallbackQueryHandler(handle_day_select, pattern='^day_'))
    app.add_handler(CallbackQueryHandler(quick_actions, pattern='^(status|add_extra|pay)$'))

    app.job_queue.run_daily(daily_reminder, time=datetime.time(hour=18, minute=0))

    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()