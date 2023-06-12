import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Sequence

import uvicorn
from mysql.connector import connect, Error
from mysql.connector.abstracts import MySQLConnectionAbstract
from pyrogram import Client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram import __version__ as TG_VER
from telegram.constants import ParseMode
from telegram.ext import (
    MessageHandler,
    filters,
    Application,
    CallbackContext,
    CommandHandler,
    ContextTypes,
    ExtBot,
    ChatMemberHandler
)

try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]

if __version_info__ < (20, 0, 0, "alpha", 1):
    raise RuntimeError(
        f"This example is not compatible with your current PTB version {TG_VER}. To view the "
        f"{TG_VER} version of this example, "
        f"visit https://docs.python-telegram-bot.org/en/v{TG_VER}/examples.html"
    )

# Enable logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

host = "localhost"
user = "root"
pswd = "1"
db = "box"
sticker_unique_id = "AgADqiEAAul_6Uo"

# TODO: fill it
api_id = 0
api_hash = ""
bot_token = ""

client = Client("my_bot", api_id=api_id, api_hash=api_hash)
temp_points = {}


def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member


async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the chats the bot is in."""
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    # Let's check who is responsible for the change
    cause_name = update.effective_user.full_name

    try:
        with connect(
                host=host,
                user=user,
                password=pswd,
                database=db
        ) as connection:
            with connection.cursor() as cursor:
                chat = update.effective_chat
                if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
                    if not was_member and is_member:
                        logger.info("%s added the bot to the group %s", cause_name, chat.title)
                        context.bot_data.setdefault("group_ids", set()).add(chat.id)
                        insert_query = """
                        INSERT IGNORE INTO chats 
                        (chat_id) 
                        VALUES 
                          (%s);
                        """

                        cursor.execute(insert_query, (chat.id,))
                    elif was_member and not is_member:
                        logger.info("%s removed the bot from the group %s", cause_name, chat.title)
                        context.bot_data.setdefault("group_ids", set()).discard(chat.id)
                        delete_query = """
                        DELETE FROM chats WHERE chat_id=%s;
                        """
                        cursor.execute(delete_query, (chat.id,))
                    connection.commit()
    except Error as e:
        print(e)


def get_results_from_db(chat_id: int, month=False, week=False, day=False) -> Sequence:
    try:
        with connect(
                host=host,
                user=user,
                password=pswd,
                database=db
        ) as connection:
            with connection.cursor() as cursor:
                if month:
                    select_query = """
                    select count(op_id) AS sum, user_id from operations where chat_id=%s and (date > NOW() - INTERVAL 1 MONTH) group by user_id order by sum DESC;
                    """
                elif week:
                    select_query = """
                    select count(op_id) AS sum, user_id from operations where chat_id=%s and (date > NOW() - INTERVAL 1 week) group by user_id order by sum DESC;
                    """
                elif day:
                    select_query = """
                    select count(op_id) AS sum, user_id from operations where chat_id=%s and (date > NOW() - INTERVAL 1 day) group by user_id order by sum DESC;
                    """
                else:
                    select_query = """
                    select count(op_id) AS sum, user_id from operations where chat_id=%s group by user_id order by sum DESC;
                    """

                cursor.execute(select_query, (chat_id,))
                results = cursor.fetchall()
    except Error as e:
        print(e)

    return results


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return
    results = get_results_from_db(update.message.chat_id)
    text = await text_results(results, update.message.chat_id)
    text = "мега результаты за все время\n\n" + text
    await context.bot.send_message(chat_id=update.message.chat_id, text=text)


async def show_results_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return
    results = get_results_from_db(update.message.chat_id, month=True)
    text = await text_results(results, update.message.chat_id)
    text = "результаты за месяц\n\n" + text
    await context.bot.send_message(chat_id=update.message.chat_id, text=text)


async def show_results_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return
    results = get_results_from_db(update.message.chat_id, week=True)
    text = await text_results(results, update.message.chat_id)
    text = "результаты за неделю\n\n" + text
    await context.bot.send_message(chat_id=update.message.chat_id, text=text)


async def show_results_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return
    results = get_results_from_db(update.message.chat_id, day=True)
    text = await text_results(results, update.message.chat_id)
    text = "результаты за день\n\n" + text
    await context.bot.send_message(chat_id=update.message.chat_id, text=text)


async def text_results(results: Sequence, chat_id: int) -> str:
    members = []
    async for member in client.get_chat_members(chat_id):
        members.append(member)
    text = "🏆"
    for r in results:
        for m in members:
            if r[1] == m.user.id:
                count = r[0]
                boxmasters = "боксмастерc"
                if count == 1:
                    boxmasters = "боксмастер"
                text += f'{m.user.first_name} {m.user.username} -- {r[0]} {boxmasters}\n'
                members.remove(m)
                break
    for m in members:
        if m.user.is_bot:
            continue
        text += f'{m.user.first_name} {m.user.username} лох без боксмастеров\n'

    return text


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return

    logger.info(update)
    if update.message.sticker.file_unique_id == sticker_unique_id:
        await update.effective_message.reply_text("Кому боксмастер?")
        temp_points[f'{update.message.from_user}_{update.message.chat_id}'] = {
            "date": time.strftime('%Y-%m-%d %H:%M:%S'),
            "from": update.message.from_user,
            "chat_id": update.message.chat_id,
        }


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type in [Chat.PRIVATE]:
        await update.message.reply_text("я не умею общаться пук пук")
        return

    key = f'{update.message.from_user}_{update.message.chat_id}'
    temp = temp_points.get(key)
    if temp is not None:
        if update.message.text.startswith("@"):
            name = update.message.text[len("@"):]
            async for member in client.get_chat_members(update.message.chat_id):
                if member.user.username == name:
                    if member.user.id == update.message.from_user.id:
                        await update.effective_message.reply_text("Э, мошенничество")
                        return
                    elif member.user.is_bot:
                        await update.effective_message.reply_text("Сори, боты не участвуют")
                        return
                    insert_query = """
                    insert into operations (user_id, chat_id, from_id, date) values (%s, %s, %s, %s);
                    """
                    try:
                        with connect(
                                host=host,
                                user=user,
                                password=pswd,
                                database=db
                        ) as connection:
                            with connection.cursor() as cursor:
                                cursor.execute(insert_query, (member.user.id,
                                                              update.message.chat_id,
                                                              update.message.from_user.id,
                                                              temp["date"]))
                            connection.commit()
                            del temp_points[key]
                            await update.message.reply_text(
                                f"записал боксмастер на счет {member.user.first_name} {member.user.username}")
                    except Error as e:
                        print(e)
                    return

            await update.message.reply_text("это ху? не нашел такого")


@dataclass
class WebhookUpdate:
    """Simple dataclass to wrap a custom update type"""

    user_id: int
    payload: str


class CustomContext(CallbackContext[ExtBot, dict, dict, dict]):
    """
    Custom CallbackContext class that makes `user_data` available for updates of type
    `WebhookUpdate`.
    """

    @classmethod
    def from_update(
            cls,
            update: object,
            application: "Application",
    ) -> "CustomContext":
        if isinstance(update, WebhookUpdate):
            return cls(application=application, user_id=update.user_id)
        return super().from_update(update, application)


async def start(update: Update, context: CustomContext) -> None:
    await update.message.reply_text("я тока в чатиках работаю")


async def webhook_update(update: WebhookUpdate, context: CustomContext) -> None:
    """Callback that handles the custom updates."""
    chat_member = await context.bot.get_chat_member(chat_id=update.user_id, user_id=update.user_id)
    payloads = context.user_data.setdefault("payloads", [])
    payloads.append(update.payload)
    combined_payloads = "</code>\n• <code>".join(payloads)
    text = (
        f"The user {chat_member.user.mention_html()} has sent a new payload. "
        f"So far they have sent the following payloads: \n\n• <code>{combined_payloads}</code>"
    )
    print(text)
    await context.bot.send_message(
        chat_id=context.bot_data["admin_chat_id"], text=text, parse_mode=ParseMode.HTML
    )


async def create_tables(connection: MySQLConnectionAbstract):
    create_movies_table_query = """
    CREATE table if not exists chats
(
    chat_id int,
    PRIMARY KEY (chat_id)
);
create table if not exists operations
(
    op_id int NOT NULL ,
    user_id int NOT NULL ,
    from_id int NOT NULL ,
    chat_id int NOT NULL ,
    date    datetime NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    PRIMARY KEY (op_id)
);

alter table operations
    modify op_id int auto_increment;

alter table operations
    auto_increment = 1;
    """

    with connection.cursor() as cursor:
        cursor.close()
        cursor.execute(create_movies_table_query)
        connection.commit()


async def main():
    """Set up the application and a custom webserver."""
    url = "https://box-master-mega.ru"
    admin_chat_id = -840120326
    port = 8080

    context_types = ContextTypes(context=CustomContext)
    # Here we set updater to None because we want our custom webhook server to handle the updates
    # and hence we don't need an Updater instance
    application = (
        Application.builder().token("6144617242:AAEr0x-PwRDqeRxmhXFWSRaHM5mMJY20KJI").updater(
            None).context_types(
            context_types).build()
    )
    # save the values in `bot_data` such that we may easily access them in the callbacks
    application.bot_data["url"] = url
    application.bot_data["admin_chat_id"] = admin_chat_id

    # register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(CommandHandler("all", show_results))
    application.add_handler(CommandHandler("month", show_results_month))
    application.add_handler(CommandHandler("week", show_results_week))
    application.add_handler(CommandHandler("day", show_results_day))
    application.add_handler(MessageHandler(callback=handle_sticker, filters=filters.Sticker.ALL))
    application.add_handler(MessageHandler(callback=handle_message, filters=filters.ALL))

    # Pass webhook settings to telegram
    await application.bot.set_webhook(url=f"{url}/telegram")

    # Set up webserver
    async def telegram(request: Request) -> Response:
        """Handle incoming Telegram updates by putting them into the `update_queue`"""
        await application.update_queue.put(
            Update.de_json(data=await request.json(), bot=application.bot)
        )
        return Response()

    async def health(_: Request) -> PlainTextResponse:
        """For the health endpoint, reply with a simple plain text message."""
        return PlainTextResponse(content="The bot is still running fine :)")

    starlette_app = Starlette(
        routes=[
            Route("/telegram", telegram, methods=["POST"]),
            Route("/healthcheck", health, methods=["GET"]),
        ]
    )
    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=starlette_app,
            port=port,
            use_colors=True,
            host="127.0.0.1",
        )
    )
    try:
        with connect(
                host=host,
                user=user,
                password=pswd,
                database=db
        ) as connection:
            await create_tables(connection)
    except Error as e:
        print(e)
    # Run application and webserver together
    async with application:
        await client.start()
        await application.start()
        await webserver.serve()
        await application.stop()


if __name__ == "__main__":
    client.run(main())
