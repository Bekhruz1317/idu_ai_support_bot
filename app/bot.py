import csv
import logging
from io import StringIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import get_admin_id, get_bot_token, get_gemini_api_key
from .database import (
    bulk_insert_students,
    get_stats,
    get_student_by_id,
    init_db,
    insert_or_update_user,
    log_message,
)
from .gemini_client import ask_gemini

STUDENT_CSV_COLUMNS = (
    "first_name",
    "last_name",
    "group",
    "student_id",
    "lms_username",
    "srs_username",
    "email",
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# httpx logs every request URL including the bot token in path; silence at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOPICS = [
    ("timetable", "📅 Timetable"),
    ("deadlines", "⏳ Deadlines"),
    ("attendance", "✅ Attendance"),
    ("contacts", "📩 Contacts"),
]

WELCOME_TEXT = (
    "👋 Hello! I'm the IDU Student Support Bot.\n\n"
    "Ask me anything about the university — timetables, deadlines, attendance, "
    "contacts, or other student topics.\n"
    "I understand English, Uzbek, and Russian.\n\n"
    "Tap a topic below or send /menu any time."
)

HELP_TEXT = (
    "ℹ️ Just send me a question in plain language (English, Uzbek, or Russian), "
    "or tap a topic from /menu.\n"
    "Examples:\n"
    "• 'when is the coursework deadline for AI module?'\n"
    "• 'davomatim qayerda ko'rinadi'\n"
    "• 'где найти расписание?'"
)


def _topics_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"topic:{key}")]
        for key, label in TOPICS
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        await insert_or_update_user(user.id, user.username)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_topics_keyboard())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Choose a topic:", reply_markup=_topics_keyboard())


def _is_admin(user_id: int) -> bool:
    admin_id = get_admin_id()
    return admin_id != 0 and user_id == admin_id


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    stats = await get_stats()
    msg = (
        "📊 Bot Statistics:\n"
        f"Total Users: {stats['total_users']}\n"
        f"Total Messages: {stats['total_messages']}\n"
        f"Most Common Intent: {stats['most_common_intent']}"
    )
    await update.message.reply_text(msg)


def _format_student(s) -> str:
    return (
        "🎓 Student record:\n"
        f"• Name: {(s.first_name or '') + ' ' + (s.last_name or '')}".rstrip() + "\n"
        f"• Group: {s.group or '—'}\n"
        f"• Student ID: {s.student_id or '—'}\n"
        f"• LMS username: {s.lms_username or '—'}\n"
        f"• SRS username: {s.srs_username or '—'}\n"
        f"• Email: {s.email or '—'}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message.text or ""
    user = update.effective_user
    user_id = user.id if user else 0

    if user:
        await insert_or_update_user(user.id, user.username)

    if context.user_data.pop("awaiting_student_id", False):
        student = await get_student_by_id(msg.strip())
        if student is None:
            await update.message.reply_text(
                f"❌ No student found with ID '{msg.strip()}'."
            )
        else:
            await update.message.reply_text(_format_student(student))
        return

    result = await ask_gemini(user_id=user_id, text=msg)

    await log_message(
        user_id=user_id,
        message=msg,
        predicted_intent=result.get("intent", "other"),
        confidence=1.0,
    )

    await update.message.reply_text(result["answer"])


async def handle_topic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    user_id = user.id if user else 0
    if user:
        await insert_or_update_user(user.id, user.username)

    data = query.data or ""
    topic = data.split(":", 1)[1] if data.startswith("topic:") else "other"

    prompt = f"Please give me detailed information about {topic} at IDU."

    result = await ask_gemini(user_id=user_id, text=prompt)

    await log_message(
        user_id=user_id,
        message=f"[button] {topic}",
        predicted_intent=result.get("intent", "other"),
        confidence=1.0,
    )

    await query.message.reply_text(result["answer"])


async def upload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    context.user_data["awaiting_student_csv"] = True
    cols = ", ".join(STUDENT_CSV_COLUMNS)
    await update.message.reply_text(
        "📤 Send me a CSV file with these columns (header row required):\n"
        f"{cols}\n\n"
        "Type /cancel to abort."
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleared = (
        context.user_data.pop("awaiting_student_csv", None)
        or context.user_data.pop("awaiting_student_id", None)
    )
    if cleared:
        await update.message.reply_text("Cancelled.")
    else:
        await update.message.reply_text("Nothing to cancel.")


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_student_id"] = True
    await update.message.reply_text(
        "🔎 Please send your student ID.\n(Type /cancel to abort.)"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    if not context.user_data.get("awaiting_student_csv"):
        return

    doc = update.message.document
    if not doc:
        return

    file = await context.bot.get_file(doc.file_id)
    raw = await file.download_as_bytearray()
    try:
        text = bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        await update.message.reply_text("❌ File must be UTF-8 encoded.")
        return

    reader = csv.DictReader(StringIO(text))
    fieldnames = set(reader.fieldnames or [])
    missing = set(STUDENT_CSV_COLUMNS) - fieldnames
    if missing:
        await update.message.reply_text(
            f"❌ Missing columns: {', '.join(sorted(missing))}"
        )
        return

    rows = []
    for row in reader:
        rows.append(
            {col: (row.get(col) or "").strip() or None for col in STUDENT_CSV_COLUMNS}
        )

    try:
        count = await bulk_insert_students(rows)
    except Exception:
        logger.exception("Failed to insert students")
        await update.message.reply_text("❌ Failed to save records. Check the logs.")
        return

    context.user_data.pop("awaiting_student_csv", None)
    await update.message.reply_text(f"✅ Inserted {count} student records.")


async def post_init(app: Application) -> None:
    logger.info("Initializing async database...")
    await init_db()


def main() -> None:
    token = get_bot_token()
    get_gemini_api_key()  # fail fast if missing
    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("upload", upload_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(handle_topic_callback, pattern=r"^topic:"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running... Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
