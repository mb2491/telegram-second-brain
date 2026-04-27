import base64
import os
import re
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
VAULT_PATH = Path(os.getenv("VAULT_PATH", r"C:\Users\MiniMara\Documents\ClaudiOS"))
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID", "")

client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Sei un assistente che trasforma messaggi informali in note strutturate per Obsidian (Markdown).

Rispondi SOLO con il contenuto markdown, niente altro.

REGOLA ASSOLUTA: il frontmatter deve iniziare ESATTAMENTE così, senza modifiche:
---
tags: [{tag}]
date: {date}
---

Non cambiare, non aggiungere, non sostituire il tag. Usa esattamente [{tag}].

Poi aggiungi:
# Titolo chiaro e descrittivo

## Informazioni principali
(campi adatti al contenuto — per vini/porte/birre: cantina/produttore, annata, zona, prezzo se noto; per libri: autore, genere; per film: regista, anno; adatta liberamente)

## Note personali
(includi SOLO se l'utente ha scritto opinioni o valutazioni esplicite — altrimenti ometti la sezione)

Usa l'italiano. Il titolo deve essere utile per ricerche future."""


def extract_tag(text: str | None) -> tuple[str, str]:
    """Prima parola = tag, resto = contenuto da strutturare."""
    if not text or not text.strip():
        return "nota", ""
    parts = text.strip().split(None, 1)
    tag = parts[0].lower()
    body = parts[1] if len(parts) > 1 else ""
    return tag, body


def is_allowed(chat_id: str) -> bool:
    return not ALLOWED_CHAT_ID or chat_id == ALLOWED_CHAT_ID


def build_prompt(tag: str, date: str) -> str:
    return SYSTEM_PROMPT.replace("{tag}", tag).replace("{date}", date)


async def build_claude_content(text: str | None, photo_bytes: bytes | None, date: str) -> list:
    parts = [{"type": "text", "text": f"Data: {date}"}]

    if photo_bytes:
        parts.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(photo_bytes).decode(),
            },
        })

    if text:
        parts.append({"type": "text", "text": text})

    return parts


async def save_and_reply(update: Update, content: str, date: str):
    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else "nota"
    slug = re.sub(r"[^\w\s-]", "", title).strip()
    slug = re.sub(r"\s+", "-", slug).lower()[:50]
    filename = f"{date}_{slug}.md"

    VAULT_PATH.mkdir(parents=True, exist_ok=True)
    (VAULT_PATH / filename).write_text(content, encoding="utf-8")

    preview = content[:500] + ("..." if len(content) > 500 else "")
    await update.message.reply_text(f"Salvato: {filename}\n\n{preview}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(str(update.effective_chat.id)):
        return

    tag, body = extract_tag(update.message.text)
    await update.message.reply_text(f"Strutturando [{tag}]...")
    date = datetime.now().strftime("%Y-%m-%d")

    try:
        content_parts = await build_claude_content(body or update.message.text, None, date)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=build_prompt(tag, date),
            messages=[{"role": "user", "content": content_parts}],
        )
        await save_and_reply(update, message.content[0].text, date)
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(str(update.effective_chat.id)):
        return

    if not update.message.caption or not update.message.caption.strip():
        await update.message.reply_text(
            "Aggiungi una didascalia con il tag come prima parola.\n"
            "Es: 'porto' oppure 'vino buono, da ricomprare'"
        )
        return

    tag, body = extract_tag(update.message.caption)
    await update.message.reply_text(f"Analizzo immagine [{tag}]...")
    date = datetime.now().strftime("%Y-%m-%d")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()

        content_parts = await build_claude_content(body if body else None, bytes(photo_bytes), date)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=build_prompt(tag, date),
            messages=[{"role": "user", "content": content_parts}],
        )
        await save_and_reply(update, message.content[0].text, date)
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Bot attivo!\nIl tuo Chat ID e': {update.effective_chat.id}\n\n"
        f"Uso: inizia ogni messaggio con il tag.\n"
        f"Es: 'porto Quinta do Crasto 2018'\n"
        f"Es: 'libro Il nome della rosa - Eco'\n"
        f"Es: 'film Dune parte 2'"
    )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print(f"Bot avviato. Vault: {VAULT_PATH}")
    app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
