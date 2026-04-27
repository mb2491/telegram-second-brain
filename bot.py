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

Analizza il messaggio, identifica la categoria (vino, ristorante, libro, film, ricetta, luogo, prodotto, persona, altro) ed estrai tutte le informazioni utili.

Rispondi SOLO con il contenuto markdown della nota, niente altro.

Formato:
---
tags: [categoria]
date: {data}
---
# Titolo chiaro e descrittivo

## Informazioni principali
(campi specifici per categoria)
Per vini: cantina, annata, denominazione/zona, prezzo se noto, abbinamento
Per ristoranti: nome, città, tipo cucina, piatti provati, prezzo medio
Per libri: autore, genere, editore
Adatta i campi al contenuto.

## Note personali
(impressioni, valutazione, consigli d'uso)

## Contesto
(dove/quando trovato, con chi — solo se presente nel messaggio)

Usa l'italiano. Il titolo deve essere utile per ricerche future (es. "Barolo 2019 - Cantina Mascarello")."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Bot attivo!\nIl tuo Chat ID e': {chat_id}\n\n"
        f"Copia questo numero nel file .env come ALLOWED_CHAT_ID, poi riavvia il bot."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        return

    if not update.message or not update.message.text:
        await update.message.reply_text("Manda solo testo per ora.")
        return

    await update.message.reply_text("Strutturando la nota...")

    date = datetime.now().strftime("%Y-%m-%d")

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Data: {date}\n\n{update.message.text}"}
            ],
        )

        content = message.content[0].text

        title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else "nota"
        slug = re.sub(r"[^\w\s-]", "", title).strip()
        slug = re.sub(r"\s+", "-", slug).lower()[:50]
        filename = f"{date}_{slug}.md"

        VAULT_PATH.mkdir(parents=True, exist_ok=True)
        (VAULT_PATH / filename).write_text(content, encoding="utf-8")

        preview = content[:500] + ("..." if len(content) > 500 else "")
        await update.message.reply_text(f"Salvato: {filename}\n\n{preview}")

    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"Bot avviato. Vault: {VAULT_PATH}")
    app.run_polling()


if __name__ == "__main__":
    main()
