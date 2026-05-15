# telegram_second_brain

Bot Telegram che trasforma messaggi informali in note strutturate per Obsidian.
Progetto hobby, codice semplice, nessun requisito di produzione.

## Cosa fa

- Riceve messaggi Telegram (testo o foto con didascalia)
- Prima parola = tag (es. `vino`, `libro`, `toread`)
- Claude Haiku struttura il contenuto in Markdown con frontmatter Obsidian
- Salva la nota in `VAULT_PATH/note/YYYY-MM-DD_titolo.md`
- URL rilevati automaticamente → tag `toread` con `status: pending` nel frontmatter
- Whitelist su `ALLOWED_CHAT_ID` (solo Mara)

## Tag → MOC

| Tag | MOC |
|-----|-----|
| vino, porto, birra, spirits, bevanda, cocktail | MOC - Bevande |
| libro, film, serie, podcast, musica, fumetto | MOC - Cultura |
| viaggio, luogo, ristorante, ricetta, hotel, posto | MOC - Viaggi |
| casa, arredamento, elettrodomestico, cucina, bagno, giardino, domotica | MOC - Casa |
| toread | MOC - Da leggere |
| stampa, todo | MOC - Progetti |
| vittoria | MOC - Elucubrazioni |
| idee, selfpublish | MOC - Self Publishing |

## File principali

- `bot.py` — tutto il codice del bot
- `.env` — credenziali (non committare mai)
- `.env.example` — template credenziali

## Variabili d'ambiente

```
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
VAULT_PATH=percorso/al/vault/Obsidian
ALLOWED_CHAT_ID=...
```

## Stato del progetto

### Fatto
- Bot funzionante: testo + foto
- Rilevamento automatico URL → toread
- Sistema tag → MOC
- Whitelist chat ID

### In corso
- Deploy su Raspberry Pi (da headless su PC a servizio sempre attivo)
- Sync vault Obsidian multi-device con Syncthing (PC fisso + Pi + laptop)

### Da fare
- Dashboard web per visualizzare le note `status: pending` (toread, towatch, ecc.)
  - Si aggiorna in tempo reale leggendo i file Markdown del vault
  - Stack da definire (discusso in precedenza ma non documentato — chiedere a Mara)

## Deploy su Raspberry Pi

### Prerequisiti Pi
```bash
sudo apt install python3-pip python3-venv
git clone <repo>
cd telegram_second_brain
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### .env sul Pi
```
VAULT_PATH=/home/pi/ClaudiOS
```

### Servizio systemd
```ini
[Unit]
Description=Telegram Second Brain Bot
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/telegram_second_brain
EnvironmentFile=/home/pi/telegram_second_brain/.env
ExecStart=/home/pi/telegram_second_brain/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Sync vault con Syncthing
- Installa Syncthing su Pi, PC fisso e laptop
- Sincronizza `VAULT_PATH` su tutti i device
- In LAN: peer-to-peer diretto. Da fuori casa: relay Syncthing (cifrato)
