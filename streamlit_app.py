"""DrugLens | RxNorm + DailyMed. Run: streamlit run streamlit_app.py"""
from __future__ import annotations
import json
from datetime import datetime
import streamlit as st
import pandas as pd
from druglens.coordinator import Orchestrator, VerificationAgent
from druglens.dailymed_agent import SECTION_TITLES

st.set_page_config(page_title='DrugLens | RxNorm × DailyMed', page_icon='💊', layout='wide', initial_sidebar_state='expanded')
st.markdown('''
<style>
.block-container {padding-top: 1.8rem; max-width: 1280px;}
.hero {padding: 1.5rem 1.8rem 1.1rem; border: 1px solid #325267; border-radius: 18px;
  background: linear-gradient(112deg,#152939 0%,#121f32 58%,#183942 100%);}
.hero h1 {font-size: 2.1rem; margin-bottom: .35rem;}
.hero p {color: #b5d4dd; margin: 0;}
.note {font-size: .87rem; color: #a7bdc7;}
[data-testid="stMetricValue"] {font-size: 1.4rem;}
</style>''', unsafe_allow_html=True)

@st.cache_data(ttl=1800, show_spinner=False)
def lookup(term: str) -> dict:
    return Orchestrator().find(term)

@st.cache_data(ttl=1800, show_spinner=False)
def details(term: str, rxcui: str, name: str, tty: str) -> dict:
    return Orchestrator().detail(term, {'rxcui': rxcui, 'name': name, 'tty': tty}, [])

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_label(setid: str) -> dict:
    return Orchestrator().load_label({'setid': setid})

def render_search(term: str, slot: int) -> dict:
    result = lookup(term)
    st.subheader(f'{"A" if slot == 0 else "B"}. {term}')
    for err in result.get('errors', []):
        st.warning(err)
    choices = result['rxnorm'].get('concepts', [])
    if choices:
        st.caption(f'RxNorm: найдено {len(choices)} вариантов, метод: {result["rxnorm"]["method"]}')
        options = [None] + choices
        pos = st.selectbox(
            'Стандартизированная форма (RxNorm)',
            options=list(range(len(options))), index=1,
            format_func=lambda i: ('Не уточнять форму, искать по названию' if i == 0 else f'{options[i]["name"]} [{options[i]["tty"]}, RxCUI {options[i]["rxcui"]}]'),
            key=f'concept_{slot}',
        )
        selected = options[pos]
    else:
        selected = None
        st.info('RxNorm не вернул вариантов. Можно просмотреть инструкции DailyMed по текстовому названию.')

    selected_details = {'labels': result['by_name'], 'ingredient_concepts': [], 'match': 'по названию', 'errors': []}
    if selected:
        selected_details = details(term, selected['rxcui'], selected['name'], selected['tty'])
        if not selected_details['labels']:
            selected_details['labels'] = result['by_name']
            selected_details['match'] = 'по названию (инструкции для RxCUI отсутствуют)'
    for err in selected_details.get('errors', []):
        st.warning(err)
    if selected:
        st.markdown(f'**RxCUI:** `{selected["rxcui"]}` · **TTY:** `{selected["tty"]}`')
        ingredients = selected_details['ingredient_concepts']
        if ingredients:
            st.markdown('**Связанные действующие вещества RxNorm:** ' + ', '.join(f'{x["name"]} (`{x["rxcui"]}`)' for x in ingredients))
        else:
            st.caption('Связанные действующие вещества не подтверждены через API RxNorm для выбранного понятия.')
    else:
        ingredients = []
    st.caption('Поиск инструкций: ' + selected_details['match'])
    labels = selected_details['labels']
    chosen = None
    document = {'sections': {}, 'titles': {}}
    if labels:
        st.caption(f'DailyMed: найдено {len(labels)} инструкций (первые записи выдачи API)')
        index = st.selectbox('Конкретная инструкция SPL', range(len(labels)),
             format_func=lambda i: f'{labels[i]["title"][:110]} · {labels[i].get("published") or "дата не указана"}', key=f'label_{slot}')
        chosen = labels[index]
        st.markdown(f'[Открыть оригинал DailyMed]({chosen["url"]}) · SETID: `{chosen["setid"]}`')
        document = fetch_label(chosen['setid'])
        if document.get('error'):
            st.error(document['error'])
        elif not document.get('sections'):
            st.info('В XML SPL не обнаружены поддерживаемые разделы по кодам LOINC.')
    else:
        if result.get('errors') and not choices:
            st.warning('Нет подтверждённых результатов. Один или оба API могли быть недоступны.')
        else:
            st.info('По этому запросу DailyMed не вернул инструкций. Попробуйте другое название или RxCUI.')
    available_sections = document.get('sections', {})
    if available_sections:
        st.caption(f'Извлечено разделов: {len(available_sections)}')
        section = st.selectbox('Раздел инструкции', list(available_sections),
            format_func=lambda k: SECTION_TITLES.get(k, k), key=f'section_{slot}')
        content = available_sections[section]
        st.text_area('Оригинальный английский текст SPL (фрагмент)', value=content[:6500], height=225, disabled=True,
                     key=f'content_{slot}_{chosen["setid"]}_{section}')
        if len(content) > 6500:
            st.caption('Показаны первые 6500 символов выбранного раздела. Для полного текста откройте DailyMed.')
    return {'query': term, 'concept': selected, 'ingredients': ingredients,
            'label': chosen, 'document': document, 'match': selected_details['match']}

st.markdown('''<div class="hero"><h1>💊 DrugLens</h1>
<p>Два источника · два агента данных · проверяемое сравнение официальных инструкций</p></div>''', unsafe_allow_html=True)
st.caption('RxNorm нормализует названия и действующие вещества. DailyMed показывает маркировку лекарств для рынка США.')

with st.sidebar:
    st.header('🔎 Поиск препаратов')
    with st.form('search_form'):
        left_term = st.text_input('Препарат A', value='Advil', max_chars=100, help='Рекомендуются английские названия из американского RxNorm: Advil, Motrin, metformin.')
        right_term = st.text_input('Препарат B (необязательно)', value='Motrin', max_chars=100)
        submitted = st.form_submit_button('Найти и сравнить', use_container_width=True, type='primary')
    if submitted:
        if not left_term.strip():
            st.error('Введите название первого препарата.')
        else:
            st.session_state['terms'] = [left_term.strip(), right_term.strip()]
            for i in range(2):
                for prefix in ('concept', 'label', 'section', 'content'):
                    st.session_state.pop(f'{prefix}_{i}', None)
    st.divider()
    st.markdown('**Источники:**')
    st.markdown('• [RxNorm / RxNav](https://rxnav.nlm.nih.gov/)  \n• [DailyMed / NLM](https://dailymed.nlm.nih.gov/)')
    st.info('Поиск ориентирован на американские названия и лекарственные формы. Русские торговые названия могут отсутствовать.')
    if st.button('Сбросить кеш API', use_container_width=True):
        st.cache_data.clear()
        st.toast('Кеш очищен')

terms = st.session_state.get('terms', [])
if not terms:
    st.markdown('### Как работает сервис')
    st.markdown('**1.** Введите один или два препарата слева.  \n**2.** Выберите точную форму из RxNorm.  \n**3.** Выберите официальную инструкцию DailyMed и сравните разделы.')
    st.markdown('Примеры запросов: `Advil` и `Motrin`, `metformin` и `Glucophage`.')
    st.stop()

valid = [t for t in terms if t]
with st.spinner('Обращаемся к RxNorm и DailyMed…'):
    tab_search, tab_comparison, tab_arch = st.tabs(['📑 Инструкции и варианты', '⚖️ Сравнение', '🧩 Агенты и ограничения'])
    with tab_search:
        panels = st.columns(len(valid), gap='large')
        contexts = []
        for i, term in enumerate(valid):
            with panels[i]:
                contexts.append(render_search(term, i))
    with tab_comparison:
        if len(contexts) != 2:
            st.info('Чтобы сравнивать, укажите два препарата в боковой панели.')
        else:
            report = VerificationAgent.report(contexts[0], contexts[1])
            relation = report['ingredient_check']
            st.subheader('Проверка действующих веществ')
            st.info(relation['status'])
            if relation['common']:
                st.markdown('**Общие идентификаторы:** ' + ', '.join(relation['common']))
            if relation['left_only']:
                st.markdown('**Только A:** ' + ', '.join(relation['left_only']))
            if relation['right_only']:
                st.markdown('**Только B:** ' + ', '.join(relation['right_only']))
            st.caption('Совпадение RxNorm-ингредиентов не означает эквивалентность доз, форм, показаний или допустимость замены.')
            st.subheader('Сопоставление разделов DailyMed')
            frame = pd.DataFrame(report['section_comparison'])
            shown = frame[~frame['Статус'].str.startswith('В обеих инструкциях')]
            st.dataframe((shown if not shown.empty else frame)[['Раздел', 'Статус']], hide_index=True, use_container_width=True)
            a, b = st.columns(2, gap='large')
            available_keys = [key for key in SECTION_TITLES if any(ctx['document'].get('sections', {}).get(key) for ctx in contexts)]
            section_key = st.selectbox('Какой раздел просмотреть рядом?', available_keys or list(SECTION_TITLES),
                                       format_func=lambda key: SECTION_TITLES[key], key='compare_section')
            with a:
                st.markdown(f'**A · {contexts[0]["query"]}**')
                st.text_area('Оригинал A', value=contexts[0]['document'].get('sections', {}).get(section_key) or 'Раздел не извлечён', height=270, disabled=True)
            with b:
                st.markdown(f'**B · {contexts[1]["query"]}**')
                st.text_area('Оригинал B', value=contexts[1]['document'].get('sections', {}).get(section_key) or 'Раздел не извлечён', height=270, disabled=True)
            st.download_button('⬇️ Скачать проверяемый отчёт (JSON)',
                data=json.dumps(report, ensure_ascii=False, indent=2),
                file_name='druglens_comparison.json', mime='application/json', use_container_width=True)
    with tab_arch:
        st.markdown('''
### Архитектура агентов

1. **Агент RxNorm** ищет стандартизированные понятия и отдельным запросом получает идентификаторы действующих веществ.
2. **Агент DailyMed** ищет записи SPL по названию либо выбранному RxCUI и читает XML разделов.
3. **Оркестратор** запускает оба поиска параллельно, сопоставляет результаты по RxCUI и сохраняет ошибки каждого API отдельно.
4. **Агент проверки** сравнивает именно RxCUI действующих веществ и наличие/дословное совпадение разделов, не выдумывая медицинских выводов.

**Поток данных:** `Streamlit → Orchestrator → (RxNorm || DailyMed) → SPL parser → VerificationAgent → UI / JSON`

### Что приложение НЕ делает

- Не назначает лечение, не советует менять препараты и не обещает их взаимозаменяемость.
- Не переводит английские инструкции автоматически: сохранён исходный текст для проверяемости.
- Не оценивает риск побочных реакций по числу упоминаний.
- Не считает отсутствие раздела в извлечении отсутствием предупреждения в оригинале.

**Доказуемость:** каждый вывод сопровождается RxCUI, SPL Set ID и ссылками на первоисточники. Поиск по названию является менее строгим, чем поиск по конкретному RxCUI.
        ''')

st.divider()
st.warning('⚕️ Учебный исследовательский сервис. Не является медицинской консультацией, клинической рекомендацией или основанием для самостоятельной замены лекарств. Данные относятся прежде всего к США.')
st.caption('This product uses publicly available data from the U.S. National Library of Medicine (NLM), National Institutes of Health, Department of Health and Human Services; NLM is not responsible for the product and does not endorse or recommend this or any other product.')

