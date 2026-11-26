"""
Rechtstexte liegen als einfache Textdateien unter templates/legal/*.txt
(eine Quelle für Website UND Bestellbestätigungs-Mail).

Format:  "## Überschrift"  ·  Absätze durch Leerzeilen getrennt  ·  "- " für Aufzählungen
"""
import re
from datetime import timezone
from zoneinfo import ZoneInfo
from markupsafe import Markup, escape

_URL = re.compile(r'(https?://[^\s)<]+?)(?=[.,;:]?(?:\s|<|\)|$))')


def _blocks(text):
    return [b.strip('\n') for b in re.split(r'\n\s*\n', str(text).strip()) if b.strip()]


def legal_html(text):
    out = []
    for block in _blocks(text):
        if block.startswith('## '):
            out.append(f'<h2 class="text-lg font-bold text-white mt-8 first:mt-0 mb-3">'
                       f'{escape(block[3:])}</h2>')
            continue
        lines = block.split('\n')
        para, items = [], []
        for line in lines:
            (items if line.startswith('- ') else para).append(line)
        html = ''
        if para:
            body = '<br>'.join(str(escape(l)) for l in para)
            body = _URL.sub(r'<a href="\1" class="text-[#8B2FC9] hover:text-[#39FF14] underline break-all">\1</a>', body)
            html += f'<p class="text-sm text-gray-300 leading-relaxed mb-3">{body}</p>'
        if items:
            lis = ''.join(f'<li>{escape(i[2:])}</li>' for i in items)
            html += f'<ul class="list-disc pl-5 space-y-1 text-sm text-gray-300 mb-3">{lis}</ul>'
        out.append(html)
    return Markup('\n'.join(out))


def legal_text(text):
    """Für Klartext-Mails: Überschriften unterstreichen statt '## '."""
    out = []
    for block in _blocks(text):
        if block.startswith('## '):
            title = block[3:]
            out.append(f'{title.upper()}\n{"-" * len(title)}')
        else:
            out.append(block)
    return '\n\n'.join(out)


_BERLIN = ZoneInfo('Europe/Berlin')


def berlin(dt, fmt='%d.%m.%Y %H:%M'):
    """In der DB liegen naive UTC-Zeiten → Anzeige in deutscher Zeit (MEZ/MESZ)."""
    if dt is None:
        return ''
    return dt.replace(tzinfo=timezone.utc).astimezone(_BERLIN).strftime(fmt)
