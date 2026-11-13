"""Agent B: DailyMed label matching and section extraction from FDA SPL XML."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import re
import xml.etree.ElementTree as ET
from .client import ApiClient

ROOT = 'https://dailymed.nlm.nih.gov/dailymed/services/v2'
SETID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
SECTIONS = {
    '34067-9': ('indications', 'Показания и применение'),
    '34070-3': ('contraindications', 'Противопоказания'),
    '43685-7': ('warnings', 'Предупреждения и меры предосторожности'),
    '34084-4': ('adverse', 'Нежелательные реакции'),
    '34073-7': ('interactions', 'Лекарственные взаимодействия'),
    '34068-7': ('dosage', 'Дозирование и применение'),
    '34066-1': ('boxed_warning', 'Предупреждение в рамке'),
    '34071-1': ('warnings', 'Предупреждения (OTC)'),
    '50570-1': ('otc_do_not_use', 'OTC: не применять'),
    '50569-3': ('otc_ask_doctor', 'OTC: проконсультироваться с врачом'),
    '50568-5': ('otc_ask_pharmacist', 'OTC: консультация врача / фармацевта'),
    '50567-7': ('otc_when_using', 'OTC: во время применения'),
    '50566-9': ('otc_stop_use', 'OTC: прекратить применение и обратиться к врачу'),
    '53414-9': ('otc_pregnancy', 'OTC: беременность / грудное вскармливание'),
    '55106-9': ('otc_active', 'OTC: действующие вещества по инструкции'),
    '55105-1': ('otc_purpose', 'OTC: назначение / категория'),
}
SECTION_TITLES = dict((key, label) for key, label in SECTIONS.values())

def _local(tag):
    return tag.rsplit('}', 1)[-1]

def _direct_child(node, local):
    return next((child for child in node if _local(child.tag) == local), None)

def _clean_text(node):
    if node is None:
        return ''
    return re.sub(r'\s+', ' ', ' '.join(node.itertext())).strip()

@dataclass(frozen=True)
class Label:
    setid: str
    title: str
    published: str = ''

    @property
    def url(self):
        return f'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={self.setid}'

    def as_dict(self):
        return {**asdict(self), 'url': self.url}

class DailyMedAgent:
    def __init__(self, client: ApiClient | None = None):
        self.client = client or ApiClient()

    def search(self, *, drug_name: str | None = None, rxcui: str | None = None, limit: int = 10) -> list[dict]:
        if not drug_name and not rxcui:
            return []
        params = {'pagesize': max(1, min(limit, 100)), 'page': 1}
        if rxcui:
            if not str(rxcui).isdigit():
                return []
            params['rxcui'] = str(rxcui)
        else:
            params['drug_name'] = drug_name
        data = self.client.get_json(f'{ROOT}/spls.json', params)
        rows, seen = [], set()
        for item in data.get('data', []) or []:
            setid = str(item.get('setid') or '').strip()
            if SETID_RE.fullmatch(setid) and setid not in seen:
                rows.append(Label(setid, str(item.get('title') or item.get('drug_name') or 'Без названия'), str(item.get('published_date') or '')).as_dict())
                seen.add(setid)
        return rows[:limit]

    def fetch_sections(self, setid: str) -> dict:
        if not SETID_RE.fullmatch(setid):
            raise ValueError('Некорректный DailyMed SETID')
        raw = self.client.get_xml(f'{ROOT}/spls/{setid}.xml')
        return parse_spl(raw)

def parse_spl(xml: bytes | str) -> dict:
    """Extract selected top-level LOINC sections, not guessed advice or generated text."""
    root = ET.fromstring(xml)
    sections: dict[str, str] = {}
    original_titles: dict[str, str] = {}
    for node in root.iter():
        if _local(node.tag) != 'section':
            continue
        code_node = _direct_child(node, 'code')
        code = code_node.attrib.get('code', '') if code_node is not None else ''
        if code not in SECTIONS:
            continue
        key, _ = SECTIONS[code]
        title = _clean_text(_direct_child(node, 'title'))
        text = _clean_text(_direct_child(node, 'text'))
        # A section can hold subsections but no direct <text>; collect their direct text.
        if not text:
            text = ' '.join(filter(None, (_clean_text(_direct_child(sub, 'text')) for sub in node.iter() if sub is not node and _local(sub.tag) == 'section')))
        text = text[:20000]
        if text and len(text) > len(sections.get(key, '')):
            sections[key] = text
            original_titles[key] = title or SECTIONS[code][1]
    return {'sections': sections, 'titles': original_titles}

