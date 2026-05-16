import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

app = Flask(__name__)
VAULT_PATH = Path(os.getenv("VAULT_PATH", r"C:\Users\MiniMara\Documents\ClaudiOS"))
NOTES_DIR = VAULT_PATH / "note"

_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
_TITLE_RE = re.compile(r'^# (.+)$', re.MULTILINE)


def _get_tipo(front: dict) -> str:
    tags = front.get('tags', [])
    url = str(front.get('url', ''))
    if 'todo' in tags:
        return 'Todo'
    if 'towatch' in tags:
        return 'YouTube' if url else 'Film/Serie'
    if 'toread' in tags:
        if url:
            host = urlparse(url).netloc.lower()
            if 'reddit' in host:
                return 'Reddit'
            if 'youtube' in host or 'youtu.be' in host:
                return 'YouTube'
            if 'substack' in host:
                return 'Substack'
        return 'Articolo'
    return 'Nota'


def _parse_note(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return None
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        return None
    try:
        front = yaml.safe_load(fm.group(1))
    except Exception:
        return None
    tags = front.get('tags', [])
    if not any(t in tags for t in ('toread', 'towatch', 'todo')):
        return None
    title_m = _TITLE_RE.search(text)
    platforms = front.get('platforms', [])
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.strip('[]').split(',') if p.strip()]
    return {
        'filename': path.name,
        'title': title_m.group(1) if title_m else path.stem,
        'date': str(front.get('date', '')),
        'status': front.get('status', 'pending'),
        'tipo': _get_tipo(front),
        'url': str(front.get('url', '')),
        'platforms': platforms,
        'done_date': str(front.get('done_date', '')),
    }


def _load_notes(status: str) -> list[dict]:
    if not NOTES_DIR.exists():
        return []
    notes = [n for p in NOTES_DIR.glob('*.md') if (n := _parse_note(p)) and n['status'] == status]
    return sorted(notes, key=lambda n: n['date'], reverse=True)


@app.route('/')
def index():
    pending = _load_notes('pending')
    todos = [n for n in pending if n['tipo'] == 'Todo']
    media = [n for n in pending if n['tipo'] != 'Todo']
    return render_template('index.html', todos=todos, media=media, done=_load_notes('done'))


@app.route('/done/<filename>', methods=['POST'])
def mark_done(filename):
    path = NOTES_DIR / filename
    if not path.exists():
        return '', 404
    text = path.read_text(encoding='utf-8')
    today = datetime.now().strftime('%Y-%m-%d')
    new_text = text.replace('status: pending', f'status: done\ndone_date: {today}', 1)
    if new_text == text:
        new_text = text.replace('\n---\n', f'\nstatus: done\ndone_date: {today}\n---\n', 1)
    path.write_text(new_text, encoding='utf-8')
    return ''


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
