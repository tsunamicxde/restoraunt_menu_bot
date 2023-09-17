import logging
import psycopg2
import json
import re

from config import host, port, db_name, user, password, TOKEN, PAYMENTS_TOKEN, channel_name
from menu import all_soups, all_meat, all_salads, all_snacks, all_desserts, \
                 all_coffee, all_alcohol_free, all_alcohol, all_hookah

from aiogram import Bot, Dispatcher, types, executor
from aiogram.types.message import ContentType
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage


bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)
dp.middleware.setup(LoggingMiddleware())


conn = psycopg2.connect(
    host=host,
    port=port,
    dbname=db_name,
    user=user,
    password=password
)
cursor = conn.cursor()

with open('create_orders_table.sql', 'r') as sql_config:
    create_table_query = sql_config.read()

cursor.execute(create_table_query)

conn.commit()


all_menu_categories = {
    'soups': all_soups,
    'meat': all_meat,
    'salads': all_salads,
    'snacks': all_snacks,
    'desserts': all_desserts,
    'coffee': all_coffee,
    'alcohol_free': all_alcohol_free,
    'alcohol': all_alcohol,
    'hookah': all_hookah
}


def call_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    soups = types.InlineKeyboardButton("Первые блюда 🫕", callback_data="soups")
    meat = types.InlineKeyboardButton("Мясные блюда 🥩", callback_data="meat")
    salads = types.InlineKeyboardButton("Салаты 🥗", callback_data="salads")
    snacks = types.InlineKeyboardButton("Закуски 🌮", callback_data="snacks")
    desserts = types.InlineKeyboardButton("Десерты 🍰", callback_data="desserts")
    coffee = types.InlineKeyboardButton("Кофе ☕️", callback_data="coffee")
    alcohol_free = types.InlineKeyboardButton("Безалкогольные напитки 🥤", callback_data="alcohol_free")
    alcohol = types.InlineKeyboardButton("Алкогольные напитки 🍾", callback_data="alcohol")
    hookah = types.InlineKeyboardButton("Кальяны", callback_data="hookah")
    markup.add(soups, meat, salads, snacks, desserts, coffee, alcohol_free, alcohol, hookah)
    return markup


@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    menu_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    menu_keyboard.row("Меню", "Мой заказ")

    user_id = message.chat.id
    await message.reply("Здравствуйте! Я бот, который запишет ваш заказ\n\n", reply_markup=menu_keyboard)
    keyboard = call_menu()
    await message.reply("Для заказа выберите интересующую вас категорию в меню:\n",
                        reply_markup=keyboard)

    try:
        insert_query = '''
                INSERT INTO orders (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO UPDATE
                SET user_id = EXCLUDED.user_id
                RETURNING user_id;
            '''

        cursor.execute(insert_query, (user_id,))
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        await message.reply("Что-то пошло не так")


@dp.message_handler(lambda message: re.match(r'/del\d+', message.text))
async def delete_dish(message: types.Message):
    user_id = message.chat.id
    try:
        try:
            index = int(message.text[4:])

            cursor.execute("SELECT \"order\" FROM orders WHERE user_id = %s;", (user_id,))
            order = cursor.fetchone()[0]

            if 0 <= index < len(order):
                deleted_dish_list = order.pop(index)
                new_data = json.dumps(order)
                try:
                    cursor.execute("UPDATE orders SET \"order\" = %s WHERE user_id = %s;", (new_data, user_id))
                    conn.commit()

                    await message.reply(f"Вы успешно удалили {list(deleted_dish_list.keys())[0]} стоимостью "
                                        f"{list(deleted_dish_list.values())[0]} из заказа.")
                    update_query = '''
                                                            UPDATE orders
                                                            SET
                                                                cost = cost - %s
                                                            WHERE user_id = %s;
                                                       '''

                    cursor.execute(update_query, (list(deleted_dish_list.values())[0], user_id))
                    conn.commit()
                except psycopg2.Error:
                    conn.rollback()
                    await message.reply("Что-то пошло не так")
                keyboard = call_menu()
                deleted_dish_list.clear()
                await message.reply("Выберите интересующую вас категорию в меню:\n",
                                    reply_markup=keyboard)
        except psycopg2.Error:
            await message.reply("Что-то пошло не так")
        else:
            await message.reply("Указанный индекс недопустим.")
    except (IndexError, ValueError):
        await message.reply("Используйте команду в формате /delete <индекс> для удаления блюда из заказа.")


@dp.callback_query_handler(lambda callback_query: True)
async def callback(call):
    user_id = call.message.chat.id
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    if call.data in all_menu_categories.keys():
        markup = types.InlineKeyboardMarkup(row_width=1)
        collection_name = f"all_{call.data}"
        all_types = globals().get(collection_name)

        for one_type in all_types:
            for key, value in one_type.items():
                button = types.InlineKeyboardButton(f"{key} [{value} руб]", callback_data=f"{key}")
                markup.add(button)

        go_back = types.InlineKeyboardButton("Назад <<", callback_data="go_back")
        markup.add(go_back)
        await bot.send_message(call.message.chat.id, f"Меню: ", reply_markup=markup)
    elif call.data == "accept_pay":
        try:
            cursor.execute("SELECT \"order\", cost FROM orders WHERE user_id = %s;", (user_id,))
            row = cursor.fetchone()
            current_orders = row[0]
            current_cost = row[1]

            order_text = ""
            for current_order in current_orders:
                for key, value in current_order.items():
                    order_text += f"\n{key} - {value} руб. /del{current_orders.index(current_order)}"

            price = types.LabeledPrice(label="Стоимость заказа", amount=current_cost * 100)

            await bot.send_invoice(call.message.chat.id,
                                   title="Оформление заказа",
                                   description="Оплата стоимости заказа",
                                   provider_token=PAYMENTS_TOKEN,
                                   currency="rub",
                                   is_flexible=False,
                                   prices=[price],
                                   start_parameter="order_pay",
                                   payload="order-payload")
        except psycopg2.Error:
            await bot.send_message(call.message.chat.id, "Что-то пошло не так")

    elif call.data == "go_back":
        keyboard = call_menu()
        await bot.send_message(call.message.chat.id, "Выберите интересующую вас категорию в меню:\n",
                               reply_markup=keyboard)
    else:
        for category, items in all_menu_categories.items():
            for item in items:
                for key, value in item.items():
                    if call.data in key:
                        user_id = call.message.chat.id

                        try:
                            update_query = '''
                                                                        UPDATE orders
                                                                        SET 
                                                                            "order" = "order" || %s::jsonb,
                                                                            cost = cost + %s
                                                                        WHERE user_id = %s;
                                                                   '''

                            cursor.execute(update_query, (json.dumps({key: value}), value, user_id))
                            conn.commit()
                        except psycopg2.Error:
                            conn.rollback()
                            await bot.send_message(call.message.chat.id, "Что-то пошло не так")

                        try:
                            cursor.execute("SELECT \"order\" FROM orders WHERE user_id = %s;", (user_id,))
                            current_data = cursor.fetchone()[0]

                            target_dict = {key: value}

                            index = current_data.index(target_dict)
                            await bot.send_message(call.message.chat.id,
                                                   f"Вы добавили {key} в заказ. Стоимость: {value}\n"
                                                   f"Удалить блюдо: /del{index}")
                        except psycopg2.Error:
                            await bot.send_message(call.message.chat.id, "Что-то пошло не так")
                        keyboard = call_menu()
                        await bot.send_message(call.message.chat.id,
                                               "Выберите интересующую вас категорию в меню:\n",
                                               reply_markup=keyboard)


@dp.message_handler(content_types=['text'])
async def text(message: types.Message):
    user_id = message.chat.id
    if message.text == "Меню":
        keyboard = call_menu()
        await message.reply("Выберите интересующую вас категорию в меню:\n",
                            reply_markup=keyboard)
    elif message.text == "Мой заказ":
        try:
            cursor.execute("SELECT \"order\", cost FROM orders WHERE user_id = %s;", (user_id,))
            row = cursor.fetchone()
            current_orders = row[0]
            current_cost = row[1]

            if current_cost > 0:
                order_text = "Ваш заказ:\n"
                for current_order in current_orders:
                    for key, value in current_order.items():
                        order_text += f"\n{key} - {value} руб. /del{current_orders.index(current_order)}"

                order_text += f"\n\nОбщая стоимость: {current_cost}"

                markup = types.InlineKeyboardMarkup(row_width=1)
                accept_pay_button = types.InlineKeyboardButton("Оплатить заказ", callback_data="accept_pay")
                markup.add(accept_pay_button)
                await message.reply(order_text, reply_markup=markup)
            else:
                await message.reply("Ваш заказ пуст")
        except psycopg2.Error:
            await bot.send_message(message.chat.id, "Что-то пошло не так")


@dp.pre_checkout_query_handler(lambda query: True)
async def pre_checkout_query(pre_checkout_q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
    user_id = message.chat.id

    await bot.send_message(message.chat.id,
                           f"Платёж на сумму {message.successful_payment.total_amount // 100}"
                           f" {message.successful_payment.currency} прошёл успешно")

    try:
        cursor.execute("SELECT \"order\", cost FROM orders WHERE user_id = %s;", (user_id,))
        row = cursor.fetchone()

        current_orders = row[0]
        current_cost = row[1]

        username = message.from_user.first_name
        order_text = f"Пользователь {username} оплатил заказ:\n"
        for current_order in current_orders:
            for key, value in current_order.items():
                order_text += f"\n{key} - {value} руб. /del{current_orders.index(current_order)}"

        order_text += f"\n\nНа сумму: {current_cost}"
        await bot.send_message(chat_id=channel_name, text=order_text)
    except psycopg2.Error:
        await bot.send_message(message.chat.id, "Что-то пошло не так")
    try:
        cursor.execute("UPDATE orders SET \"order\" = DEFAULT, cost = DEFAULT")
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        await bot.send_message(message.chat.id, "Что-то пошло не так")


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
