# -*- coding: utf-8 -*-
import os

# Вставьте сюда токен, который вам выдал @BotFather,
# либо задайте переменную окружения BOT_TOKEN на хостинге (это приоритетнее).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8652080266:AAH6WQwUQlOimq-FD8--I44v1gQZ_zsZ9l8")

# Ваш числовой Telegram ID — сюда будут приходить жалобы на объявления,
# и только этот ID сможет пользоваться командами /block и /unblock.
# Чтобы узнать свой ID: напишите боту команду /myid после запуска.
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7211484627"))
print(ADMIN_ID)