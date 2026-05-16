import base64
import os
import re
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
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

TOREAD_PROMPT = """Sei un assistente che salva link da leggere in Obsidian (Markdown).

Ricevi un URL e opzionalmente una descrizione dell'utente.
Rispondi SOLO con il contenuto markdown, niente altro.

Il frontmatter deve essere ESATTAMENTE:
---
tags: [toread]
date: {date}
url: {url}
status: pending
---

Poi aggiungi:
# Titolo descrittivo (deducilo dall'URL o dalla descrizione)

## Note
(includi solo se l'utente ha aggiunto una descrizione — altrimenti ometti la sezione)

Usa l'italiano."""

TOWATCH_PROMPT = """Sei un assistente che salva video da guardare in Obsidian (Markdown).

Ricevi un URL YouTube e opzionalmente una descrizione dell'utente.
Rispondi SOLO con il contenuto markdown, niente altro.

Il frontmatter deve essere ESATTAMENTE:
---
tags: [towatch]
date: {date}
url: {url}
status: pending
---

Poi aggiungi:
# Titolo descrittivo (deducilo dall'URL o dalla descrizione)

## Note
(includi solo se l'utente ha aggiunto una descrizione — altrimenti ometti la sezione)

Usa l'italiano."""

TOWATCH_TEXT_PROMPT = """Sei un assistente che crea il corpo di una nota Obsidian per un film o serie TV da guardare.
NON scrivere il frontmatter YAML — verrà aggiunto separatamente.
Rispondi SOLO con il corpo della nota, a partire dal titolo.

# Titolo chiaro e descrittivo

## Informazioni principali
(tipo: Film/Serie, anno se noto, regista/creatore, genere — NON includere piattaforme o dove guardarlo)

## Note personali
(includi SOLO se l'utente ha scritto opinioni o valutazioni esplicite — altrimenti ometti la sezione)

Usa l'italiano."""

URL_RE = re.compile(r'https?://\S+')
YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com"}
TOREAD_DOMAINS = {"reddit.com", "www.reddit.com", "substack.com"}


def url_tag(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if host in YOUTUBE_DOMAINS:
        return "towatch"
    return "toread"

TAG_TO_MOC = {
    **dict.fromkeys(["vino", "porto", "birra", "spirits", "bevanda", "cocktail"], "MOC - Bevande"),
    **dict.fromkeys(["libro", "film", "serie", "podcast", "musica", "fumetto"], "MOC - Cultura"),
    **dict.fromkeys(["viaggio", "luogo", "ristorante", "ricetta", "hotel", "posto"], "MOC - Viaggi"),
    **dict.fromkeys(["casa", "arredamento", "elettrodomestico", "cucina", "bagno", "giardino", "domotica"], "MOC - Casa"),
    **dict.fromkeys(["toread"], "MOC - Da leggere"),
    **dict.fromkeys(["towatch"], "MOC - Da vedere"),
    **dict.fromkeys(["stampa", "todo"], "MOC - Progetti"),
    **dict.fromkeys(["vittoria"], "MOC - Elucubrazioni"),
    **dict.fromkeys(["idee", "selfpublish"], "MOC - Self Publishing"),
}
_CODE_FENCE_RE = re.compile(r'^```(?:markdown)?\n(.*?)(?:\n```)?$', re.DOTALL)


def strip_code_fence(text: str) -> str:
    m = _CODE_FENCE_RE.match(text.strip())
    return m.group(1) if m else text


def extract_url(text: str) -> tuple[str | None, str]:
    """Estrae il primo URL dal testo. Restituisce (url, testo_rimanente)."""
    match = URL_RE.search(text)
    if not match:
        return None, text
    url = match.group()
    rest = (text[:match.start()] + text[match.end():]).strip()
    return url, rest


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


def append_moc_link(content: str, tag: str) -> str:
    moc = TAG_TO_MOC.get(tag)
    if moc and f"[[{moc}]]" not in content:
        content = content.rstrip() + f"\n\n→ [[{moc}]]"
    return content


async def save_and_reply(update: Update, content: str, date: str):
    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else "nota"
    slug = re.sub(r"[^\w\s-]", "", title).strip()
    slug = re.sub(r"\s+", "-", slug).lower()[:50]
    filename = f"{date}_{slug}.md"

    notes_dir = VAULT_PATH / "note"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / filename).write_text(content, encoding="utf-8")

    preview = content[:500] + ("..." if len(content) > 500 else "")
    await update.message.reply_text(f"Salvato: {filename}\n\n{preview}")


_JW_QUERY = """
query GetTitleOffers($country: Country!, $language: Language!, $filter: TitleFilter!) {
  popularTitles(country: $country, first: 1, filter: $filter) {
    edges {
      node {
        ... on Movie {
          content(country: $country, language: $language) { title }
          offers(country: $country, platform: WEB) {
            monetizationType
            package { clearName }
          }
        }
        ... on Show {
          content(country: $country, language: $language) { title }
          offers(country: $country, platform: WEB) {
            monetizationType
            package { clearName }
          }
        }
      }
    }
  }
}
"""


async def fetch_youtube_title(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            resp = await http.get(f"https://www.youtube.com/oembed?url={url}&format=json")
            resp.raise_for_status()
            return resp.json().get("title")
    except Exception:
        return None


async def query_justwatch(title: str) -> list[str]:
    """Cerca piattaforme streaming FLATRATE su JustWatch IT. Ritorna lista vuota in caso di errore."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                "https://apis.justwatch.com/graphql",
                json={
                    "query": _JW_QUERY,
                    "variables": {"country": "IT", "language": "it", "filter": {"searchQuery": title}},
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            edges = resp.json().get("data", {}).get("popularTitles", {}).get("edges", [])
            if not edges:
                return []
            offers = edges[0]["node"].get("offers", [])
            platforms = sorted({o["package"]["clearName"] for o in offers if o.get("monetizationType") == "FLATRATE"})
            return platforms
    except Exception:
        return []


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(str(update.effective_chat.id)):
        return

    date = datetime.now().strftime("%Y-%m-%d")
    text = update.message.text

    url, rest = extract_url(text)
    if url:
        tag = url_tag(url)
        prompt_template = TOWATCH_PROMPT if tag == "towatch" else TOREAD_PROMPT
        await update.message.reply_text(f"Link salvato come [{tag}]...")
        try:
            user_content = rest or url
            if tag == "towatch":
                yt_title = await fetch_youtube_title(url)
                if yt_title:
                    user_content = f"Titolo del video: {yt_title}\n{user_content}".strip()
            prompt = prompt_template.replace("{date}", date).replace("{url}", url)
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            content = append_moc_link(strip_code_fence(message.content[0].text), tag)
            await save_and_reply(update, content, date)
        except Exception as e:
            await update.message.reply_text(f"Errore: {e}")
        return

    tag, body = extract_tag(text)

    if tag == "towatch":
        platforms = await query_justwatch(body)
        plat_note = f" ({', '.join(platforms)})" if platforms else " (non trovato su JustWatch)"
        await update.message.reply_text(f"Strutturando [towatch]{plat_note}...")
        platforms_str = "[" + ", ".join(platforms) + "]" if platforms else "[]"
        frontmatter = f"---\ntags: [towatch]\ndate: {date}\nstatus: pending\nplatforms: {platforms_str}\n---\n\n"
        system = TOWATCH_TEXT_PROMPT
    else:
        await update.message.reply_text(f"Strutturando [{tag}]...")
        frontmatter = ""
        system = build_prompt(tag, date)

    try:
        content_parts = await build_claude_content(body or text, None, date)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": content_parts}],
        )
        body_text = strip_code_fence(message.content[0].text)
        content = frontmatter + body_text if frontmatter else body_text
        await save_and_reply(update, append_moc_link(content, tag), date)
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
        await save_and_reply(update, append_moc_link(strip_code_fence(message.content[0].text), tag), date)
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
