const tg = window.Telegram?.WebApp;
if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation();
}

let glossaryData = null;
let countriesData = null;
let calendarData = null;
let acquirersData = null;

let currentCategory = 'all';
let currentRegion = 'all';

// Navigation
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => navigateTo(tab.dataset.page));
});

document.querySelectorAll('.card[data-page]').forEach(card => {
    card.addEventListener('click', () => navigateTo(card.dataset.page));
});

function navigateTo(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) {
        pageEl.classList.add('active');
    }

    const tabEl = document.querySelector(`.tab[data-page="${page}"]`);
    if (tabEl) tabEl.classList.add('active');

    if (page === 'glossary' && !glossaryData) loadGlossary();
    if (page === 'countries' && !countriesData) loadCountries();
    if (page === 'calendar' && !calendarData) loadCalendar();
    if (page === 'acquirers' && !acquirersData) loadAcquirers();
}

// Data loading (embedded JSON fetched from same origin or via bot API)
async function fetchData(filename) {
    try {
        const resp = await fetch(`data/${filename}`);
        if (resp.ok) return await resp.json();
    } catch(e) { /* fallback to empty */ }
    return null;
}

// Glossary
async function loadGlossary() {
    glossaryData = await fetchData('glossary.json');
    if (!glossaryData) {
        document.getElementById('glossary-list').innerHTML = '<div class="list-item"><div class="item-title">Данные загружаются через бота</div></div>';
        return;
    }

    const categories = [...new Set(glossaryData.terms.map(t => t.category))];
    const chipsEl = document.getElementById('glossary-categories');
    chipsEl.innerHTML = `<button class="chip active" data-cat="all">Все</button>` +
        categories.map(c => `<button class="chip" data-cat="${c}">${capitalize(c)}</button>`).join('');

    chipsEl.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chipsEl.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentCategory = chip.dataset.cat;
            renderGlossary();
        });
    });

    document.getElementById('glossary-search').addEventListener('input', renderGlossary);
    renderGlossary();
}

function renderGlossary() {
    if (!glossaryData) return;
    const search = document.getElementById('glossary-search').value.toLowerCase();
    let terms = glossaryData.terms;

    if (currentCategory !== 'all') {
        terms = terms.filter(t => t.category === currentCategory);
    }
    if (search) {
        terms = terms.filter(t =>
            t.term.toLowerCase().includes(search) ||
            t.term_ru.toLowerCase().includes(search) ||
            t.definition.toLowerCase().includes(search)
        );
    }

    const listEl = document.getElementById('glossary-list');
    listEl.innerHTML = terms.slice(0, 50).map((t, i) => `
        <div class="list-item" onclick="showTerm(${glossaryData.terms.indexOf(t)})">
            <div class="item-title">${t.term}</div>
            <div class="item-subtitle">${t.term_ru} · ${capitalize(t.category)}</div>
        </div>
    `).join('');

    if (terms.length === 0) {
        listEl.innerHTML = '<div class="list-item"><div class="item-title">Ничего не найдено</div></div>';
    }
    if (terms.length > 50) {
        listEl.innerHTML += `<div class="list-item"><div class="item-subtitle">Показано 50 из ${terms.length}</div></div>`;
    }
}

function showTerm(idx) {
    const t = glossaryData.terms[idx];
    const listEl = document.getElementById('glossary-list');
    listEl.innerHTML = `
        <div class="detail">
            <h3>${t.term}</h3>
            <div class="row"><span class="label">Русское название</span><span>${t.term_ru}</span></div>
            <div class="row"><span class="label">Категория</span><span class="item-badge badge-blue">${capitalize(t.category)}</span></div>
            <div class="section-title">Определение</div>
            <p style="font-size:13px;line-height:1.5">${t.definition}</p>
            ${t.example ? `<div class="section-title">Пример</div><p style="font-size:13px;color:var(--hint)">${t.example}</p>` : ''}
            ${t.related && t.related.length ? `<div class="section-title">Связанные</div><p style="font-size:13px">${t.related.join(', ')}</p>` : ''}
            <button class="chip active" style="margin-top:12px" onclick="renderGlossary()">← Назад</button>
        </div>
    `;
}

// Countries
async function loadCountries() {
    countriesData = await fetchData('countries.json');
    if (!countriesData) {
        document.getElementById('country-list').innerHTML = '<div class="list-item"><div class="item-title">Данные загружаются через бота</div></div>';
        return;
    }

    const regions = [...new Set(countriesData.countries.map(c => c.region))];
    const chipsEl = document.getElementById('country-regions');
    chipsEl.innerHTML = `<button class="chip active" data-reg="all">Все</button>` +
        regions.map(r => `<button class="chip" data-reg="${r}">${r}</button>`).join('');

    chipsEl.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chipsEl.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentRegion = chip.dataset.reg;
            renderCountries();
        });
    });

    document.getElementById('country-search').addEventListener('input', renderCountries);
    renderCountries();
}

function renderCountries() {
    if (!countriesData) return;
    const search = document.getElementById('country-search').value.toLowerCase();
    let countries = countriesData.countries;

    if (currentRegion !== 'all') {
        countries = countries.filter(c => c.region === currentRegion);
    }
    if (search) {
        countries = countries.filter(c =>
            c.name.toLowerCase().includes(search) ||
            c.name_ru.toLowerCase().includes(search) ||
            c.code.toLowerCase().includes(search)
        );
    }

    const listEl = document.getElementById('country-list');
    const detailEl = document.getElementById('country-detail');
    detailEl.classList.add('hidden');

    listEl.innerHTML = countries.slice(0, 50).map(c => {
        const risk = c.risk_level;
        const badgeClass = risk === 'low' ? 'badge-green' : risk === 'medium' ? 'badge-yellow' : 'badge-red';
        return `
            <div class="list-item" onclick="showCountry('${c.code}')">
                <div class="item-title">${c.name_ru} (${c.code})</div>
                <div class="item-subtitle">${c.region} · <span class="item-badge ${badgeClass}">${risk}</span></div>
            </div>
        `;
    }).join('');
}

function showCountry(code) {
    const c = countriesData.countries.find(x => x.code === code);
    if (!c) return;

    const detailEl = document.getElementById('country-detail');
    detailEl.classList.remove('hidden');

    function statusBadge(s) {
        const cls = s === 'allowed' ? 'badge-green' : s === 'restricted' ? 'badge-yellow' : 'badge-red';
        const label = s === 'allowed' ? 'Разрешено' : s === 'restricted' ? 'Ограничено' : 'Запрещено';
        return `<span class="item-badge ${cls}">${label}</span>`;
    }

    detailEl.innerHTML = `
        <h3>${c.name_ru} (${c.code})</h3>
        <div class="row"><span class="label">Регион</span><span>${c.region}</span></div>
        <div class="row"><span class="label">Риск</span><span class="item-badge ${c.risk_level === 'low' ? 'badge-green' : c.risk_level === 'medium' ? 'badge-yellow' : 'badge-red'}">${c.risk_level}</span></div>
        <div class="row"><span class="label">Банковская система</span><span>${c.banking_system}</span></div>
        <div class="section-title">Вертикали</div>
        <div class="row"><span class="label">Гемблинг</span>${statusBadge(c.gambling.status)}</div>
        <div class="row"><span class="label">Крипто</span>${statusBadge(c.crypto.status)}</div>
        <div class="row"><span class="label">Форекс</span>${statusBadge(c.forex.status)}</div>
        <div class="row"><span class="label">Adult</span>${statusBadge(c.adult.status)}</div>
        <div class="row"><span class="label">Nutra</span>${statusBadge(c.nutra.status)}</div>
        ${c.popular_acquirers.length ? `<div class="section-title">Эквайеры</div><p style="font-size:13px">${c.popular_acquirers.join(', ')}</p>` : ''}
        <button class="chip active" style="margin-top:12px" onclick="document.getElementById('country-detail').classList.add('hidden')">← Назад</button>
    `;

    detailEl.scrollIntoView({ behavior: 'smooth' });
}

// Calendar
const monthNames = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

async function loadCalendar() {
    calendarData = await fetchData('calendar.json');
    if (!calendarData) {
        document.getElementById('calendar-detail').innerHTML = '<div class="list-item"><div class="item-title">Данные загружаются через бота</div></div>';
        return;
    }

    const gridEl = document.getElementById('month-grid');
    const currentMonth = new Date().getMonth() + 1;

    gridEl.innerHTML = calendarData.months.map(m =>
        `<div class="month-card ${m.month === currentMonth ? 'selected' : ''}" onclick="showMonth(${m.month})">${m.name}</div>`
    ).join('');

    showMonth(currentMonth);
}

function showMonth(num) {
    if (!calendarData) return;
    const m = calendarData.months.find(x => x.month === num);
    if (!m) return;

    document.querySelectorAll('.month-card').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll('.month-card')[num - 1]?.classList.add('selected');

    const colorEmoji = c => c === 'green' ? '🟢' : c === 'yellow' ? '🟡' : '🔴';
    const detailEl = document.getElementById('calendar-detail');

    detailEl.innerHTML = `
        <div class="detail">
            <h3>${m.name}</h3>
            ${Object.entries(m.verticals).map(([k, v]) => `
                <div class="row">
                    <span class="label">${capitalize(k)}</span>
                    <span>${colorEmoji(v.color)} ${v.notes}</span>
                </div>
            `).join('')}
        </div>
    `;
}

// Acquirers
async function loadAcquirers() {
    acquirersData = await fetchData('acquirers.json');
    if (!acquirersData) {
        document.getElementById('acquirer-list').innerHTML = '<div class="list-item"><div class="item-title">Данные загружаются через бота</div></div>';
        return;
    }

    const verticals = [...new Set(acquirersData.acquirers.flatMap(a => a.verticals))];
    const chipsEl = document.getElementById('acquirer-filters');
    chipsEl.innerHTML = `<button class="chip active" data-vert="all">Все</button>` +
        verticals.slice(0, 8).map(v => `<button class="chip" data-vert="${v}">${capitalize(v)}</button>`).join('');

    chipsEl.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
            chipsEl.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            renderAcquirers(chip.dataset.vert);
        });
    });

    document.getElementById('acquirer-search').addEventListener('input', () => renderAcquirers());
    renderAcquirers();
}

function renderAcquirers(vertical = 'all') {
    if (!acquirersData) return;
    const search = document.getElementById('acquirer-search').value.toLowerCase();
    let acqs = acquirersData.acquirers;

    if (vertical !== 'all') {
        acqs = acqs.filter(a => a.verticals.includes(vertical));
    }
    if (search) {
        acqs = acqs.filter(a => a.name.toLowerCase().includes(search));
    }

    const listEl = document.getElementById('acquirer-list');
    const detailEl = document.getElementById('acquirer-detail');
    detailEl.classList.add('hidden');

    listEl.innerHTML = acqs.map((a, i) => {
        const riskClass = a.risk_level === 'low' ? 'badge-green' : a.risk_level === 'medium' ? 'badge-yellow' : 'badge-red';
        return `
            <div class="list-item" onclick="showAcquirer(${acquirersData.acquirers.indexOf(a)})">
                <div class="item-title">${a.name} ★${a.rating}</div>
                <div class="item-subtitle">${a.type} · ${a.regions.join(', ')}</div>
                <span class="item-badge ${riskClass}">${a.risk_level} risk</span>
            </div>
        `;
    }).join('');
}

function showAcquirer(idx) {
    const a = acquirersData.acquirers[idx];
    if (!a) return;

    const detailEl = document.getElementById('acquirer-detail');
    detailEl.classList.remove('hidden');

    detailEl.innerHTML = `
        <h3>${a.name} ★${a.rating}</h3>
        <div class="row"><span class="label">Тип</span><span>${a.type}</span></div>
        <div class="row"><span class="label">Регионы</span><span>${a.regions.join(', ')}</span></div>
        <div class="row"><span class="label">Мин. объём</span><span>${a.min_volume}</span></div>
        <div class="row"><span class="label">Rolling Reserve</span><span>${a.rolling_reserve}</span></div>
        <div class="row"><span class="label">CB Threshold</span><span>${a.chargeback_threshold}</span></div>
        <div class="row"><span class="label">Settlement</span><span>${a.settlement}</span></div>
        <div class="section-title">Вертикали</div>
        <p style="font-size:13px">${a.verticals.map(v => `<span class="item-badge badge-blue">${v}</span>`).join(' ')}</p>
        <div class="section-title">Плюсы</div>
        <p style="font-size:13px;color:#a5d6a7">${a.pros.map(p => '✓ ' + p).join('<br>')}</p>
        <div class="section-title">Минусы</div>
        <p style="font-size:13px;color:#ef9a9a">${a.cons.map(c => '✗ ' + c).join('<br>')}</p>
        <div class="section-title">Описание</div>
        <p style="font-size:13px;line-height:1.5">${a.description}</p>
        <button class="chip active" style="margin-top:12px" onclick="document.getElementById('acquirer-detail').classList.add('hidden')">← Назад</button>
    `;

    detailEl.scrollIntoView({ behavior: 'smooth' });
}

// Utils
function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
}
