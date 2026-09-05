// Основной скрипт Video Bot

let currentTab = 'file';
let currentJobId = sessionStorage.getItem('currentJobId') || null;
let pollInterval = null;
let lastShownLog = '';
let logsPollingInterval = null;
let currentShorts = [];
window._sessionJobs = currentJobId ? [currentJobId] : [];

// Delete projects created by this page when it is closed. Active jobs are
// marked by the backend and removed immediately after processing finishes.
let closeCleanupSent = false;
window.addEventListener('pagehide', () => {
    if (closeCleanupSent) return;
    const jobIds = [...new Set(window._sessionJobs || [])].filter(Boolean);
    if (!jobIds.length) return;
    closeCleanupSent = true;
    const payload = new Blob(
        [JSON.stringify({ job_ids: jobIds })],
        { type: 'application/json' }
    );
    navigator.sendBeacon('/api/cleanup-after-close', payload);
    sessionStorage.removeItem('currentJobId');
});

// Этапы обработки
const stages = [
    { id: 'init', name: 'Инициализация', status: 'waiting' },
    { id: 'download', name: 'Скачивание видео', status: 'waiting' },
    { id: 'split', name: 'Нарезка на шортсы', status: 'waiting' },
    { id: 'content', name: 'Генерация контента', status: 'waiting' },
    { id: 'youtube', name: 'Загрузка на YouTube', status: 'waiting' },
    { id: 'done', name: 'Задача завершена', status: 'waiting' }
];

// Обновление интерактивного окна этапов
function updateStages(currentStatus) {
    const stagesList = document.getElementById('stages-list');
    if (!stagesList) return;

    let currentStageId = 'init';
    switch(currentStatus) {
        case 'downloading': currentStageId = 'download'; break;
        case 'processing': currentStageId = 'split'; break;
        case 'generating': currentStageId = 'content'; break;
        case 'uploading': currentStageId = 'youtube'; break;
        case 'completed': currentStageId = 'done'; break;
    }

    const stageIds = ['init', 'download', 'split', 'content', 'youtube', 'done'];
    const currentIdx = stageIds.indexOf(currentStageId);

    const stageNames = {
        'init': 'Инициализация',
        'download': 'Скачивание видео',
        'split': 'Нарезка на шортсы',
        'content': 'Генерация контента',
        'youtube': 'Загрузка на YouTube',
        'done': 'Завершено'
    };

    stagesList.innerHTML = stageIds.map(id => {
        const idx = stageIds.indexOf(id);
        let icon = '⏳';
        let colorClass = 'text-gray-500';
        if (idx < currentIdx) {
            icon = '✅';
            colorClass = 'text-green-500';
        } else if (idx === currentIdx) {
            icon = '🔄';
            colorClass = 'text-blue-400';
        }
        return `<div class="flex items-center gap-3" style="color:${idx < currentIdx ? '#22c55e' : idx === currentIdx ? '#60a5fa' : '#6b7280'}"><span style="font-size:1.25rem">${icon}</span><span style="font-size:0.875rem">${stageNames[id]}</span></div>`;
    }).join('');

    document.getElementById('progress-text').textContent = stageNames[currentStageId] || 'Обработка...';
}

// Переключение вкладок
function switchTab(tab) {
    currentTab = tab;
    document.getElementById('tab-file').className = tab === 'file'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-settings').className = tab === 'settings'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-integration').className = tab === 'integration'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('section-file').classList.toggle('hidden', tab !== 'file');
    document.getElementById('section-settings').classList.toggle('hidden', tab !== 'settings');
    document.getElementById('section-integration').classList.toggle('hidden', tab !== 'integration');
}

// Безопасное добавление обработчика
function safeAddListener(id, event, handler) {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener(event, handler);
        console.log('Добавлен обработчик:', id);
    } else {
        console.error('Элемент не найден:', id);
    }
}

async function loadFonts(preferredValue = null) {
    try {
        const res = await fetch('/api/fonts');
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Ошибка загрузки списка шрифтов');
        const sel = document.getElementById('subtitle-font');
        const items = Array.isArray(data.font_items)
            ? data.font_items
            : (data.fonts || []).map(font => ({ value: font, label: font }));
        if (!sel) return;

        const previous = preferredValue || sel.value;
        sel.innerHTML = items
            .map(item => '<option value="' + escapeHtml(item.value) + '">' + escapeHtml(item.label || item.value) + '</option>')
            .join('');

        const customFonts = items.filter(item => item.custom && item.url);
        let style = document.getElementById('dynamic-preview-fonts');
        if (!style) {
            style = document.createElement('style');
            style.id = 'dynamic-preview-fonts';
            document.head.appendChild(style);
        }
        style.textContent = customFonts.map(item =>
            '@font-face{font-family:"' + String(item.value).replace(/"/g, '') + '";' +
            'src:url("' + item.url + '?v=' + Date.now() + '") format("truetype");font-display:swap;}'
        ).join('\n');
        if (document.fonts?.load) {
            await Promise.allSettled(customFonts.map(item => document.fonts.load('16px "' + item.value + '"')));
        }

        const values = items.map(item => item.value);
        if (values.includes(previous)) sel.value = previous;
        else if (values.includes('Montserrat')) sel.value = 'Montserrat';
        else if (values.length) sel.value = values[0];

        const list = document.getElementById('font-user-list');
        if (list) {
            if (!customFonts.length) {
                list.innerHTML = '<div class="text-xs text-gray-500">У вас пока нет загруженных шрифтов.</div>';
            } else {
                list.innerHTML = customFonts.map(item => `
                    <div class="flex items-center gap-2 rounded-lg bg-gray-900/70 border border-gray-700 px-3 py-2">
                        <span class="flex-1 text-sm" style="font-family:'${escapeHtml(item.value)}'">${escapeHtml(item.font_name || item.label)}</span>
                        <button type="button" class="font-select-own px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-xs"
                            data-font-value="${escapeHtml(item.value)}">Выбрать</button>
                        <button type="button" class="font-delete-own px-3 py-1 rounded bg-red-600 hover:bg-red-700 text-xs"
                            data-font-name="${escapeHtml(item.font_name)}">Удалить</button>
                    </div>`
                ).join('');
                list.querySelectorAll('.font-select-own').forEach(button => {
                    button.addEventListener('click', () => {
                        sel.value = button.dataset.fontValue;
                        document.getElementById('font-upload-status').textContent = 'Шрифт выбран. Он будет использован в следующей задаче.';
                        updateSubtitlePreview();
                    });
                });
                list.querySelectorAll('.font-delete-own').forEach(button => {
                    button.addEventListener('click', () => deleteCustomFont(button.dataset.fontName));
                });
            }
        }
        updateSubtitlePreview();
    } catch (e) {
        console.error('Ошибка загрузки шрифтов:', e);
    }
}

async function deleteCustomFont(fontName) {
    if (!fontName || !confirm('Удалить шрифт «' + fontName + '»?')) return;
    const status = document.getElementById('font-upload-status');
    try {
        const response = await fetch('/api/fonts?font_name=' + encodeURIComponent(fontName), { method: 'DELETE' });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'Ошибка удаления шрифта');
        if (status) status.textContent = data.message || 'Шрифт удалён.';
        await loadFonts('Montserrat');
    } catch (error) {
        if (status) status.textContent = 'Ошибка: ' + error.message;
    }
}

async function uploadCustomFont() {
    const input = document.getElementById('font-upload-file');
    const status = document.getElementById('font-upload-status');
    const button = document.getElementById('font-upload-btn');
    const file = input?.files?.[0];
    if (!file) {
        if (status) status.textContent = 'Сначала выберите TTF-файл.';
        return;
    }
    if (!file.name.toLowerCase().endsWith('.ttf')) {
        if (status) status.textContent = 'Поддерживаются только файлы .ttf.';
        return;
    }
    const formData = new FormData();
    formData.append('font_file', file);
    if (button) button.disabled = true;
    if (status) status.textContent = 'Загрузка шрифта…';
    try {
        const response = await fetch('/api/fonts/upload', { method: 'POST', body: formData });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'Ошибка загрузки шрифта');
        await loadFonts(data.font_value);
        if (input) input.value = '';
        if (status) status.textContent = data.message || 'Шрифт загружен и выбран.';
    } catch (error) {
        if (status) status.textContent = 'Ошибка: ' + error.message;
    } finally {
        if (button) button.disabled = false;
    }
}

let previewVideoUrl = null;

function setPreviewVideo(file) {
    if (previewVideoUrl) {
        URL.revokeObjectURL(previewVideoUrl);
        previewVideoUrl = null;
    }
    const videos = [
        document.getElementById('preview-video-bg'),
        document.getElementById('preview-video-fg')
    ].filter(Boolean);

    if (!file || !file.type?.startsWith('video/')) {
        videos.forEach(video => {
            video.removeAttribute('src');
            video.style.display = 'none';
            video.load();
        });
        updateSubtitlePreview();
        return;
    }

    previewVideoUrl = URL.createObjectURL(file);
    videos.forEach(video => {
        video.src = previewVideoUrl;
        video.currentTime = 0;
        video.load();
        video.play().catch(() => {});
    });
    updateSubtitlePreview();
}
async function showDocsModal() {
    const modal = document.getElementById('docs-modal');
    const list = document.getElementById('docs-list');
    if (!modal || !list) return;
    modal.classList.remove('hidden');
    list.innerHTML = '<div class="text-gray-500 text-center py-8">Загрузка...</div>';
    try {
        const res = await fetch('/api/docs-list');
        const data = await res.json();
        if (data.status === 'success' && data.docs.length) {
            list.innerHTML = data.docs.map(d =>
                `<a href="/docs-file/${d.file}" class="block bg-gray-800 hover:bg-gray-750 rounded-xl p-4 border border-gray-700 hover:border-blue-500 transition no-underline">
                    <div class="text-blue-400 font-semibold text-base">${d.name}</div>
                    <div class="text-gray-400 text-xs mt-1">${d.desc}</div>
                </a>`
            ).join('');
        } else {
            list.innerHTML = '<div class="text-gray-500 text-center py-8">Нет документов</div>';
        }
    } catch (e) {
        list.innerHTML = '<div class="text-red-400 text-center py-8">Ошибка загрузки</div>';
    }
}

async function loadStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        const btn = document.getElementById('stats-btn');
        if (!btn) return;
        document.getElementById('stat-videos').textContent = data.total_videos || 0;
        document.getElementById('stat-shorts').textContent = data.total_shorts || 0;
        document.getElementById('stat-completed').textContent = data.completed || 0;
        document.getElementById('stat-failed').textContent = data.failed || 0;
        document.getElementById('stat-running').textContent = data.running || 0;
        document.getElementById('stat-jobs').textContent = data.total_jobs || 0;
        btn.classList.remove('hidden');
    } catch (e) {
        console.error('Ошибка загрузки статистики:', e);
    }
}

async function logout() {
    try {
        await fetch('/api/logout', {method: 'POST'});
    } catch (e) {}
    window.location.href = '/login';
}

const CROP_DESCS = {
    original: '16:9 — вписанный в кадр',
    square: '1:1 — квадратный кроп',
    vertical: '9:16 — заполнение кадра'
};
function getCropMode(tab) {
    const checked = document.querySelector('.crop-mode-btn[data-tab="' + tab + '"] input:checked');
    return checked?.value || 'square';
}
function getSmartMode(tab) {
    const checked = document.querySelector('input[name="smart-mode-' + tab + '"]:checked');
    return checked?.value || 'off';
}
function setCropMode(tab, mode) {
    document.querySelectorAll('.crop-mode-btn[data-tab="' + tab + '"]').forEach(b => {
        const isActive = b.dataset.crop === mode;
        b.style.background = isActive ? '#1F2937' : '#374151';
        b.style.opacity = isActive ? '1' : '0.6';
        const radio = b.querySelector('input[type="radio"]');
        if (radio) radio.checked = isActive;
    });
    const desc = document.getElementById('crop-desc-' + tab);
    if (desc) desc.textContent = CROP_DESCS[mode] || '';
    const blurCb = document.getElementById(tab === 'file' ? 'blurred-bg-file' : 'integration-blurred-bg');
    if (blurCb) {
        blurCb.disabled = mode === 'vertical';
        if (mode === 'vertical') { blurCb.checked = false; blurCb.parentElement?.classList.add('opacity-40'); }
        else blurCb.parentElement?.classList.remove('opacity-40');
    }
    const previewCrop = document.getElementById('preview-crop-mode');
    if (previewCrop && tab === 'file') previewCrop.value = mode;
    if (typeof updateEstimate === 'function') updateEstimate(tab);
    if (typeof updateSubtitlePreview === 'function') updateSubtitlePreview();
}

// Инициализация после загрузки страницы
document.addEventListener('DOMContentLoaded', async function() {
    console.log('Страница загружена');

    // Имя пользователя + кнопка панели доступа (только для админа)
    const _uname = localStorage.getItem('username');
    const unameEl = document.getElementById('username-display');
    if (unameEl && _uname) unameEl.textContent = _uname;
    if (localStorage.getItem('isAdmin') === '1') {
        const adminBtn = document.getElementById('admin-btn');
        if (adminBtn) adminBtn.classList.remove('hidden');
    }
    async function checkMe() {
        try {
            const res = await fetch('/api/me');
            const data = await res.json();
            if (data.username && unameEl) unameEl.textContent = data.username;
            const adminBtn = document.getElementById('admin-btn');
            if (adminBtn) adminBtn.classList.toggle('hidden', !data.admin);
        } catch (e) {}
    }
    checkMe();

    safeAddListener('tab-file', 'click', () => switchTab('file'));
    safeAddListener('tab-settings', 'click', () => switchTab('settings'));
    safeAddListener('tab-integration', 'click', () => switchTab('integration'));
    safeAddListener('create-btn-file', 'click', createShortsFromFile);
    safeAddListener('download-all-zip-btn', 'click', downloadAllAsZip);
    safeAddListener('save-settings-btn', 'click', saveSettings);
    safeAddListener('font-upload-btn', 'click', uploadCustomFont);
    safeAddListener('start-integration-btn', 'click', startIntegration);
    safeAddListener('upload-credentials-btn', 'click', uploadCredentials);
    safeAddListener('authorize-accounts-btn', 'click', authorizeAccounts);
    safeAddListener('save-preset-btn', 'click', savePreset);
    safeAddListener('delete-preset-btn', 'click', deletePreset);
    safeAddListener('logout-btn', 'click', logout);
    safeAddListener('load-preset', 'change', loadPresetFromSelect);
    safeAddListener('refresh-accounts-btn', 'click', loadAccountsList);
    safeAddListener('stats-btn', 'click', () => document.getElementById('stats-modal')?.classList.remove('hidden'));
    safeAddListener('stats-modal-close', 'click', () => document.getElementById('stats-modal')?.classList.add('hidden'));
    document.getElementById('stats-modal')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) e.target.classList.add('hidden');
    });
    safeAddListener('docs-btn', 'click', showDocsModal);
    safeAddListener('docs-modal-close', 'click', () => document.getElementById('docs-modal')?.classList.add('hidden'));
    document.getElementById('docs-modal')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) e.target.classList.add('hidden');
    });
    safeAddListener('video-file', 'change', (e) => {
        const fileName = document.getElementById('file-name');
        const folderMode = document.getElementById('folder-mode-file')?.checked;
        const first = folderMode ? (e.target.files[0] || null) : (e.target.files[0] || null);
        if (first) {
            if (folderMode && e.target.files.length > 1) {
                const firstPath = first.webkitRelativePath || '';
                const folderName = firstPath.split('/')[0] || 'папка';
                fileName.textContent = `Папка «${folderName}» — ${e.target.files.length} видео`;
            } else {
                fileName.textContent = 'Выбран: ' + first.name;
            }
            fileName.classList.remove('hidden');
        }
        readFileVideoDurations(Array.from(e.target.files || []), 'file');
        setPreviewVideo(first);
    });

    initTabs();
    await loadFonts();
    await loadStats();
    await loadSettings();
    loadApiKeys();

    // ── Оценка времени обработки ──
    const WHISPER_FACTORS = { base: 1, small: 3.5, medium: 7, 'large-v3-turbo': 4, 'large-v3': 14 };
    window._videoDurations = { url: null, file: null, integration: null };
    window._videoFolderInfo = { file: null, integration: null };

    // Smart mode selector
    const smartDescs = {
        off: 'Выкл — просто нарезка подряд',
        global: 'Топ — выбирает лучшие моменты из всего видео, но может пропустить концовку',
        parts: 'Сетка — равномерно покрывает всё видео, но локальный лучший может быть слабее',
        hybrid: 'Гибрид — равномерное покрытие + финальный отбор только лучших'
    };

    // Авто-длительность: галочка поверх выбора сегментов
    function applyAutoDurationUI(tab, checked) {
        const isAuto = !!checked;
        const rangeRow = document.getElementById('auto-range-' + tab);
        if (rangeRow) rangeRow.classList.toggle('hidden', !isAuto);
        const lengthMap = { url: 'short-length', file: 'short-length-file', integration: 'integration-short-length' };
        const len = document.getElementById(lengthMap[tab]);
        if (len) {
            len.disabled = isAuto;
            const parent = len.closest('div');
            if (parent) parent.classList.toggle('hidden', isAuto);
        }
        updateEstimate(tab);
    }

    function setSmartMode(tab, mode) {
        const input = document.querySelector('input[name="smart-mode-' + tab + '"][value="' + mode + '"]');
        if (!input || input.disabled) return;
        input.checked = true;
        document.querySelectorAll('.smart-mode-btn[data-tab="' + tab + '"]').forEach(b => {
            const active = b.dataset.mode === mode;
            b.style.background = active ? '#1F2937' : '#374151';
            b.style.opacity = active ? '1' : '0.6';
        });
        const desc = document.getElementById('smart-desc-' + tab);
        if (desc) desc.textContent = smartDescs[mode] || '';
        const autoDuration = document.getElementById('auto-duration-' + tab);
        if (autoDuration) {
            if (mode === 'off') {
                autoDuration.checked = false;
                autoDuration.disabled = true;
                applyAutoDurationUI(tab, false);
            } else {
                autoDuration.disabled = false;
            }
        }
        updateEstimate(tab);
    }

    document.querySelectorAll('.smart-mode-btn').forEach(btn => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            const tab = btn.dataset.tab;
            const mode = btn.dataset.mode;
            const sceneStart = document.getElementById('scene-start-' + tab);
            if (mode === 'off' && sceneStart?.checked) return;
            setSmartMode(tab, mode);
        });
        if (btn.querySelector(':checked')) {
            btn.style.background = '#1F2937';
            btn.style.opacity = '1';
        }
    });

    ['file', 'integration'].forEach(tab => {
        const checkbox = document.getElementById('scene-start-' + tab);
        const offInput = document.querySelector('input[name="smart-mode-' + tab + '"][value="off"]');
        const offButton = document.querySelector('.smart-mode-btn[data-tab="' + tab + '"][data-mode="off"]');
        if (!checkbox || !offInput) return;
        const syncSceneStart = () => {
            const smartPanel = document.querySelector('.smart-mode-btn[data-tab="' + tab + '"]')?.closest('div')?.parentElement;
            if (smartPanel) {
                const label = smartPanel.querySelector('label.text-sm');
                if (label) label.classList.toggle('hidden', checkbox.checked);
                const btnsRow = smartPanel.querySelector('.flex.rounded-xl');
                if (btnsRow) btnsRow.classList.toggle('hidden', checkbox.checked);
                const desc = document.getElementById('smart-desc-' + tab);
                if (desc) desc.classList.toggle('hidden', checkbox.checked);
            }
            offInput.disabled = checkbox.checked;
            if (checkbox.checked && getTabMode(tab) === 'off') setSmartMode(tab, 'global');
            updateEstimate(tab);
        };
        checkbox.addEventListener('change', syncSceneStart);
        syncSceneStart();
    });

    ['file', 'integration'].forEach(tab => {
        const cb = document.getElementById('auto-duration-' + tab);
        if (cb) cb.addEventListener('change', () => applyAutoDurationUI(tab, cb.checked));
        setSmartMode(tab, getTabMode(tab));
    });

    // ── Crop mode buttons ──
    document.querySelectorAll('.crop-mode-btn').forEach(btn => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            setCropMode(btn.dataset.tab, btn.dataset.crop);
        });
        if (btn.querySelector(':checked')) {
            btn.style.background = '#1F2937';
            btn.style.opacity = '1';
        }
    });

    // ── Оценка времени обработки ──
    function getVideoDurationSec(tab) {
        return window._videoDurations[tab] || null;
    }

    function fmtTime(sec) {
        if (sec < 60) return '~' + Math.max(1, Math.round(sec)) + ' сек';
        const m = sec / 60;
        if (m < 60) return '~' + Math.round(m) + ' мин';
        return '~' + (m / 60).toFixed(1) + ' ч';
    }

    function getTabMode(tab) {
        const radio = document.querySelector(`input[name="smart-mode-${tab}"]:checked`);
        return radio ? radio.value : 'off';
    }

    function updateEstimate(tab) {
        const box = document.getElementById('estimate-' + tab);
        if (!box) return;

        let videosCount = 1;
        if (tab === 'file') {
            const folderMode = document.getElementById('folder-mode-file')?.checked;
            const files = document.getElementById('video-file')?.files;
            if (folderMode && files && files.length > 1) videosCount = files.length;
        }
        const folderInfo = window._videoFolderInfo?.[tab];
        const knownDur = getVideoDurationSec(tab);
        const videoSec = knownDur || (1200 * videosCount);
        const firstVideoSec = folderInfo?.first || (knownDur ? knownDur / videosCount : 1200);
        const count = parseInt(document.getElementById(
            tab === 'url' ? 'shorts-count' : tab === 'file' ? 'shorts-count-file' : 'integration-shorts-count'
        )?.value) || 5;
        const len = parseInt(document.getElementById(
            tab === 'url' ? 'short-length' : tab === 'file' ? 'short-length-file' : 'integration-short-length'
        )?.value) || 45;
        const autoCb = document.getElementById('auto-duration-' + tab);
        const auto = !!(autoCb && autoCb.checked);
        const minLen = parseInt(document.getElementById('auto-min-' + tab)?.value) || 30;
        const maxLen = parseInt(document.getElementById('auto-max-' + tab)?.value) || 60;
        const segLen = auto ? (minLen + maxLen) / 2 : len;
        const whisper = document.getElementById('whisper-model')?.value || 'base';
        const mode = getTabMode(tab);

        const TRANSCRIBE_FACTORS = {
            base: 0.12,
            small: 0.20,
            medium: 0.35,
            'large-v3-turbo': 0.35,
            'large-v3': 0.55
        };
        const RENDER_FACTORS = { simple: 0.40, heavy: 0.55 };
        const SELECTION_TIME = { off: 0, global: 10, parts: 5, hybrid: 15 };

        const smart = mode !== 'off';
        const scan = smart ? videoSec * TRANSCRIBE_FACTORS.base : 0;
        const firstScan = smart ? firstVideoSec * TRANSCRIBE_FACTORS.base : 0;
        const transcribeSeg = (smart && whisper === 'base')
            ? 0
            : count * segLen * (TRANSCRIBE_FACTORS[whisper] || TRANSCRIBE_FACTORS.base);
        const transcribe = scan + transcribeSeg;

        const blurCb = document.getElementById(tab === 'url' ? 'blurred-bg-url' : tab === 'file' ? 'blurred-bg-file' : 'integration-blurred-bg');
        const cropMode = getCropMode(tab);
        const heavyRender = !!(blurCb?.checked || cropMode !== 'original');
        const render = count * segLen * (heavyRender ? RENDER_FACTORS.heavy : RENDER_FACTORS.simple);

        const selectionPerVideo = SELECTION_TIME[mode] || 0;
        const selection = selectionPerVideo * videosCount;
        const autoTime = auto ? count * 1.5 : 0;
        const aiEnabled = [
            document.getElementById('ai-gen-title')?.checked,
            document.getElementById('ai-gen-description')?.checked,
            document.getElementById('ai-gen-tags')?.checked
        ].filter(Boolean).length;
        const ai = count * aiEnabled * 0.7;
        const perSegment = (transcribeSeg + render + ai + autoTime) / Math.max(1, count);
        const firstShort = firstScan + selectionPerVideo + perSegment;
        const total = transcribe + render + selection + autoTime + ai;
        const adaptiveFolder = document.getElementById('adaptive-folder-allocation')?.checked !== false;
        const allocationLabel = adaptiveFolder ? 'по длительности' : 'поровну';
        const countLabel = videosCount > 1
            ? `${count} шт на всю папку (${videosCount} видео, ${allocationLabel})`
            : `${count} шт`;

        const parts = [];
        if (scan > 0) parts.push('Анализ всех исходников — ' + fmtTime(scan));
        if (mode !== 'off') parts.push('Отбор лучших моментов — ' + fmtTime(selection));
        if (transcribeSeg > 0) parts.push('Распознавание речи для субтитров (' + whisper + ') — ' + fmtTime(transcribeSeg));
        parts.push('Сборка видео — ' + fmtTime(render));
        if (auto) parts.push('Подбор длительности — ' + fmtTime(autoTime));
        parts.push('Метаданные AI — ' + fmtTime(ai));

        const modeLabel = (mode === 'off' ? 'простая нарезка' : mode) + (auto ? ' + авто-длительность' : '');
        const durText = knownDur
            ? (videosCount > 1 ? 'Общая длительность папки: ' : 'Длительность видео: ') + fmtTime(knownDur)
            : (tab === 'file' ? 'Длительность определится после выбора файла' : 'Длительность определится после ввода ссылки');

        box.innerHTML = `
            <div class="text-gray-400 text-xs mb-1">${durText}</div>
            <div class="text-gray-400 text-xs mb-1">Ориентировочно (${modeLabel}, ${countLabel}):</div>
            <div class="text-purple-300 font-semibold">⏱ Первый шортс (с анализом) — ${fmtTime(firstShort)}</div>
            <div class="text-gray-300 font-semibold">⏱ Всего — ${fmtTime(total)}</div>
            <div class="text-gray-500 text-xs mt-2">Что входит во время:</div>
            <div class="text-gray-500 text-xs space-y-0.5">${parts.map(p => '• ' + p).join('<br>')}</div>
        `;
    }
    function initEstimates() {
        ['file', 'integration'].forEach(tab => {
            const ids = [
                tab === 'file' ? 'shorts-count-file' : 'integration-shorts-count',
                tab === 'file' ? 'short-length-file' : 'integration-short-length',
                'auto-min-' + tab, 'auto-max-' + tab, 'auto-duration-' + tab, 'whisper-model'
            ];
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('input', () => updateEstimate(tab));
                    el.addEventListener('change', () => updateEstimate(tab));
                }
            });
        });
    }
    initEstimates();
    document.getElementById('adaptive-folder-allocation')?.addEventListener('change', () => updateEstimate('file'));
    ['file', 'integration'].forEach(tab => updateEstimate(tab));

    // ── Авто-определение длительности видео ──
    function readOneFileVideoDuration(file) {
        return new Promise(resolve => {
            if (!file) return resolve(0);
            const objUrl = URL.createObjectURL(file);
            const v = document.createElement('video');
            v.preload = 'metadata';
            v.muted = true;
            const finish = duration => {
                URL.revokeObjectURL(objUrl);
                resolve(isFinite(duration) && duration > 0 ? duration : 0);
            };
            v.onloadedmetadata = () => finish(v.duration);
            v.onerror = () => finish(0);
            v.src = objUrl;
        });
    }

    async function readFileVideoDurations(files, tab) {
        window._videoDurations[tab] = null;
        window._videoFolderInfo[tab] = null;
        const selected = Array.from(files || []).filter(Boolean);
        if (!selected.length) { updateEstimate(tab); return; }
        const durations = await Promise.all(selected.map(readOneFileVideoDuration));
        const valid = durations.filter(duration => duration > 0);
        if (valid.length) {
            window._videoDurations[tab] = valid.reduce((sum, duration) => sum + duration, 0);
            window._videoFolderInfo[tab] = {
                count: selected.length,
                first: durations[0] || valid[0],
                durations
            };
        }
        updateEstimate(tab);
    }
    let _urlDurTimer = null;
    const urlInput = document.getElementById('video-url');
    if (urlInput) {
        urlInput.addEventListener('input', () => {
            clearTimeout(_urlDurTimer);
            _urlDurTimer = setTimeout(async () => {
                const url = urlInput.value.trim();
                window._videoDurations.url = null;
                if (!url) { updateEstimate('url'); return; }
                const box = document.getElementById('estimate-url');
                if (box) box.innerHTML = '<div class="text-gray-400 text-xs">Проверяю длительность…</div>';
                try {
                    const res = await fetch('/api/video-info?url=' + encodeURIComponent(url));
                    const data = await res.json();
                    if (data.status === 'success' && data.duration) {
                        window._videoDurations.url = data.duration;
                    }
                } catch (e) {
                    console.error('Ошибка получения информации о видео:', e);
                }
                updateEstimate('url');
            }, 1200);
        });
    }


    // Переключатели
    document.getElementById('integration-source').addEventListener('change', (e) => {
        const isFile = e.target.value === 'file';
        document.getElementById('integration-url-input').classList.toggle('hidden', isFile);
        document.getElementById('integration-file-input').classList.toggle('hidden', !isFile);
        if (isFile) updateEstimate('integration');
    });

    document.getElementById('integration-video-file').addEventListener('change', (e) => {
        const file = e.target.files[0];
        readFileVideoDurations([file], 'integration');
        setPreviewVideo(file);
    });
    document.getElementById('distribution-mode').addEventListener('change', (e) => {
        const isCustom = e.target.value === 'custom';
        document.getElementById('custom-distribution-input').classList.toggle('hidden', !isCustom);
    });

    document.getElementById('enable-scheduled').addEventListener('change', (e) => {
        document.getElementById('scheduled-options').classList.toggle('hidden', !e.target.checked);
    });

    // Переключатели музыки
    document.getElementById('enable-audio').addEventListener('change', (e) => {
        document.getElementById('audio-settings').classList.toggle('hidden', !e.target.checked);
    });

    document.getElementById('enable-audio-file').addEventListener('change', (e) => {
        document.getElementById('audio-settings-file').classList.toggle('hidden', !e.target.checked);
    });

    // Минимальная дата - сегодня
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('schedule-start-date').setAttribute('min', today);
    document.getElementById('schedule-start-date').value = today;

    safeAddListener('tab-integration', 'click', () => {
        setTimeout(loadAccountsList, 100);
        setTimeout(loadPresets, 100);
    });

    // Загружаем список аккаунтов при загрузке
    loadAccountsList();

    // Обработчик для режима папки
    const folderCb = document.getElementById('folder-mode-file');
    const fileInput = document.getElementById('video-file');
    if (folderCb && fileInput) {
        folderCb.addEventListener('change', () => {
            try {
                const adaptiveRow = document.getElementById('adaptive-folder-row');
                const adaptiveInput = document.getElementById('adaptive-folder-allocation');
                if (adaptiveRow) adaptiveRow.classList.toggle('opacity-50', !folderCb.checked);
                if (adaptiveInput) adaptiveInput.disabled = !folderCb.checked;
                if (folderCb.checked) {
                    fileInput.setAttribute('webkitdirectory', '');
                    fileInput.setAttribute('multiple', '');
                    fileInput.removeAttribute('accept');
                    const p = document.querySelector('label[for="video-file"] p');
                    if (p) p.textContent = 'Выберите папку с видео';
                } else {
                    fileInput.removeAttribute('webkitdirectory');
                    fileInput.removeAttribute('multiple');
                    fileInput.setAttribute('accept', 'video/*');
                    const p = document.querySelector('label[for="video-file"] p');
                    if (p) p.textContent = 'Перетащите файл или нажмите';
                }
            } catch(e) { console.warn('Folder mode error:', e); }
            fileInput.value = '';
            window._videoDurations.file = null;
            window._videoFolderInfo.file = null;
            document.getElementById('file-name').classList.add('hidden');
            updateEstimate('file');
        });
        const adaptiveRow = document.getElementById('adaptive-folder-row');
        const adaptiveInput = document.getElementById('adaptive-folder-allocation');
        if (adaptiveRow) adaptiveRow.classList.toggle('opacity-50', !folderCb.checked);
        if (adaptiveInput) adaptiveInput.disabled = !folderCb.checked;
    }

    function bindFrameMode(blurId, tab) {
        const blur = document.getElementById(blurId);
        if (!blur) return;

        const sync = () => {
            const previewBlur = document.getElementById('preview-blur-bg');
            const previewCrop = document.getElementById('preview-crop-mode');
            if (previewBlur) previewBlur.checked = blur.checked;
            if (previewCrop) previewCrop.value = getCropMode(tab);
            updateEstimate(tab);
            updateSubtitlePreview();
        };
        blur.addEventListener('change', sync);
    }

    bindFrameMode('blurred-bg-file', 'file');
    bindFrameMode('integration-blurred-bg', 'integration');

    const previewBlurControl = document.getElementById('preview-blur-bg');
    const previewCropControl = document.getElementById('preview-crop-mode');
    if (previewBlurControl && previewCropControl) {
        previewBlurControl.addEventListener('change', () => {
            const blur = document.getElementById('blurred-bg-file');
            if (blur) blur.checked = previewBlurControl.checked;
            updateSubtitlePreview();
            updateEstimate('file');
        });
        previewCropControl.addEventListener('change', () => {
            setCropMode('file', previewCropControl.value);
            updateSubtitlePreview();
            updateEstimate('file');
        });
    }
    // Обработчики для баннера
    ['url', 'file', 'integration', 'settings'].forEach(tab => {
        const cb = document.getElementById('banner-enabled-' + tab);
        const settings = document.getElementById('banner-settings-' + tab);
        if (cb && settings) {
            cb.addEventListener('change', () => {
                settings.classList.toggle('hidden', !cb.checked);
            });
        }
        const opacity = document.getElementById('banner-opacity-' + tab);
        const val = document.getElementById('banner-opacity-val-' + tab);
        if (opacity && val) {
            opacity.addEventListener('input', () => {
                val.textContent = opacity.value;
                if (tab === 'settings') updateSubtitlePreview();
            });
        }
        if (tab === 'settings') {
            const fileInput = document.getElementById('banner-file-settings');
            if (fileInput) {
                fileInput.addEventListener('change', updateSubtitlePreview);
            }
        }
    });

    // Scene start lock: disable shorts_count when scene_start is checked
    function setupSceneStartLock(sceneId, countId) {
        const sceneCb = document.getElementById(sceneId);
        const countInput = document.getElementById(countId);
        if (!sceneCb || !countInput) return;
        sceneCb.addEventListener('change', () => {
            countInput.disabled = sceneCb.checked;
            if (sceneCb.checked) {
                countInput.setAttribute('data-prev-val', countInput.value);
                countInput.value = '';
                countInput.placeholder = 'авто';
            } else {
                countInput.value = countInput.getAttribute('data-prev-val') || '5';
                countInput.placeholder = '';
            }
        });
    }
    setupSceneStartLock('scene-start-file', 'shorts-count-file');
    setupSceneStartLock('scene-start-integration', 'integration-shorts-count');

    // Показ/скрытие настроек паузы баннера
    const bannerStyleSel = document.getElementById('banner-style-settings');
    const bannerPauseRow = document.getElementById('banner-pause-settings');
    const bannerFileInput = document.getElementById('banner-file-settings');
    const bannerNoFileHint = document.getElementById('banner-no-file-hint');
    if (bannerStyleSel && bannerPauseRow) {
        const syncBannerStyle = () => {
            const isPause = bannerStyleSel.value === 'pause';
            bannerPauseRow.classList.toggle('hidden', !isPause);
            // если выбран режим паузы, а файла баннера нет — предупреждаем
            if (isPause && bannerNoFileHint) {
                const hasFile = bannerFileInput && bannerFileInput.files && bannerFileInput.files.length > 0;
                bannerNoFileHint.classList.toggle('hidden', hasFile);
            }
        };
        bannerStyleSel.addEventListener('change', syncBannerStyle);
        if (bannerFileInput) bannerFileInput.addEventListener('change', syncBannerStyle);
        syncBannerStyle();
    }

    console.log('Инициализация завершена');
});

// API ключи (несколько ключей с авто-переключением)
async function loadApiKeys() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        const s = data.settings;
        const container = document.getElementById('api-keys-list');
        if (!container) return;

        const providers = [
            { id: 'groq', name: 'Groq', color: 'text-orange-400' },
            { id: 'openai', name: 'OpenAI', color: 'text-emerald-400' }
        ];

        const html = providers.map(p => {
            const keys = (s.api_keys && s.api_keys[p.id]) || [];
            const items = keys.length
                ? keys.map((k, idx) => `
                    <div class="flex items-center justify-between gap-2 px-3 py-2 bg-gray-800 rounded-lg border border-gray-700">
                        <span class="font-mono text-xs text-gray-300">${escapeHtml(k)}</span>
                        <button type="button" onclick="removeApiKey('${p.id}', ${idx})"
                            class="px-2 py-1 rounded bg-red-600 hover:bg-red-700 text-xs shrink-0">Удалить</button>
                    </div>`).join('')
                : '<div class="text-xs text-gray-600">Нет ключей</div>';
            return `
                <div>
                    <div class="text-xs text-gray-400 mb-1 font-semibold ${p.color}">${p.name}</div>
                    <div class="space-y-1.5">${items}</div>
                </div>`;
        }).join('');

        container.innerHTML = html;
    } catch (e) {
        console.error('Ошибка загрузки API ключей:', e);
    }
}

async function addApiKey() {
    const provider = document.getElementById('api-provider')?.value || 'groq';
    const keyInput = document.getElementById('api-key-input');
    const key = keyInput?.value?.trim();
    if (!key) return alert('Введите API ключ');

    try {
        const res = await fetch('/api/keys/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, key })
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || 'Ошибка');
        if (keyInput) keyInput.value = '';
        loadApiKeys();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function removeApiKey(provider, index) {
    if (!confirm('Удалить этот API ключ?')) return;
    try {
        const res = await fetch('/api/keys', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, index })
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || 'Ошибка');
        loadApiKeys();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

// Загрузка настроек
const _COLOR_NAMES = {
    white: '#ffffff', black: '#000000', yellow: '#ffff00', red: '#ff0000',
    green: '#00ff00', blue: '#0000ff', cyan: '#00ffff', magenta: '#ff00ff',
    orange: '#ffa500', gray: '#808080'
};

function parseColorValue(v) {
    // "black" / "#ff5733" / "black@0.8" / "#ff5733@0.5" / "none"
    if (!v || v === 'none') return { color: '#000000', alpha: 100, none: true };
    let c = String(v), alpha = 100;
    if (c.includes('@')) {
        const parts = c.split('@');
        c = parts[0];
        const a = parseFloat(parts[1]);
        if (!isNaN(a)) alpha = Math.max(0, Math.min(100, Math.round(a * 100)));
    }
    const key = c.toLowerCase();
    if (_COLOR_NAMES[key]) c = _COLOR_NAMES[key];
    else if (!/^#[0-9a-fA-F]{6}$/.test(c)) c = '#ffffff';
    return { color: c, alpha, none: false };
}

function buildColorValue(colorHex, alphaPct, none) {
    if (none) return 'none';
    const a = Math.max(0, Math.min(100, parseInt(alphaPct) || 0)) / 100;
    if (a >= 1) return colorHex;
    return colorHex + '@' + a.toFixed(2);
}

function applyColorSetting(storedVal, pickerId, alphaId, noneId, alphaLabelId) {
    const p = parseColorValue(storedVal);
    const picker = document.getElementById(pickerId);
    const alpha = document.getElementById(alphaId);
    const none = document.getElementById(noneId);
    if (picker) picker.value = p.color;
    if (alpha) {
        alpha.value = p.alpha;
        const lab = document.getElementById(alphaLabelId);
        if (lab) lab.textContent = p.alpha + '%';
    }
    if (none) none.checked = p.none;
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();

        if (data.status === 'success' && data.settings) {
            const s = data.settings;
            // Субтитры
            if (document.getElementById('subtitle-font')) {
                const fontSelect = document.getElementById('subtitle-font');
                const requestedFont = s.font || 'Montserrat';
                fontSelect.value = Array.from(fontSelect.options).some(option => option.value === requestedFont)
                    ? requestedFont
                    : (Array.from(fontSelect.options).some(option => option.value === 'Montserrat') ? 'Montserrat' : fontSelect.options[0]?.value || 'Arial');
                document.getElementById('subtitle-style').value = s.style || 'normal';
                document.getElementById('subtitle-fontsize').value = s.fontsize || 100;
                const fontsizeValue = document.getElementById('subtitle-fontsize-val');
                if (fontsizeValue) fontsizeValue.textContent = s.fontsize || 100;
                applyColorSetting(s.fontcolor, 'subtitle-color-picker', 'subtitle-color-alpha', null, 'subtitle-color-alpha-val');
                document.getElementById('subtitle-position').value = s.position || 1670;
                const positionValue = document.getElementById('subtitle-position-val');
                if (positionValue) positionValue.textContent = s.position || 1670;
                document.getElementById('subtitle-borderw').value = s.borderw || 3;
                applyColorSetting(s.bordercolor, 'subtitle-bordercolor-picker', 'subtitle-bordercolor-alpha', 'subtitle-bordercolor-none', 'subtitle-bordercolor-alpha-val');
                document.getElementById('subtitle-boxborder').value = s.boxborder ?? 0;
                applyColorSetting(s.boxcolor, 'subtitle-boxcolor-picker', 'subtitle-boxcolor-alpha', 'subtitle-boxcolor-none', 'subtitle-boxcolor-alpha-val');
                document.getElementById('subtitle-shadowx').value = s.shadowx || 2;
                document.getElementById('subtitle-shadowy').value = s.shadowy || 2;
                applyColorSetting(s.shadowcolor, 'subtitle-shadowcolor-picker', 'subtitle-shadowcolor-alpha', 'subtitle-shadowcolor-none', 'subtitle-shadowcolor-alpha-val');
                document.getElementById('subtitle-capitalize').checked = s.capitalize !== false;

                if (document.getElementById('subtitle-words-count')) {
                    document.getElementById('subtitle-words-count').value = s.words_count ?? 3;
                    document.getElementById('subtitle-word-fade').checked = s.word_fade !== false;
                }

                if (document.getElementById('whisper-model') && s.whisper_model) {
                    document.getElementById('whisper-model').value = s.whisper_model;
                }

                if (document.getElementById('api-provider') && s.api_provider) {
                    document.getElementById('api-provider').value = s.api_provider;
                }
            }

            // Баннер
            if (document.getElementById('banner-x-settings')) {
                document.getElementById('banner-x-settings').value = s.banner_x ?? '0';
                document.getElementById('banner-y-settings').value = s.banner_y ?? '0';
                document.getElementById('banner-w-settings').value = s.banner_w ?? '1080';
                document.getElementById('banner-h-settings').value = s.banner_h ?? '200';
                document.getElementById('banner-opacity-settings').value = s.banner_opacity ?? '100';
                const val = document.getElementById('banner-opacity-val-settings');
                if (val) val.textContent = s.banner_opacity ?? '100';
            }
            updateSubtitlePreview();
        }
    } catch (e) {
        console.error('Ошибка загрузки настроек:', e);
    }
}

// Настройки
async function saveSettings() {
    const btn = document.getElementById('save-settings-btn');
    btn.disabled = true;
    btn.textContent = 'Сохраняем...';

    try {
        const formData = new URLSearchParams();

        // Субтитры
        formData.append('font', document.getElementById('subtitle-font')?.value || 'Montserrat');
        formData.append('style', document.getElementById('subtitle-style')?.value || 'normal');
        formData.append('fontsize', document.getElementById('subtitle-fontsize')?.value || '100');
        formData.append('fontcolor', buildColorValue(
            document.getElementById('subtitle-color-picker')?.value || '#ffffff',
            document.getElementById('subtitle-color-alpha')?.value || '100', false));
        formData.append('position', document.getElementById('subtitle-position')?.value || '1670');
        formData.append('borderw', document.getElementById('subtitle-borderw')?.value || '3');
        formData.append('bordercolor', buildColorValue(
            document.getElementById('subtitle-bordercolor-picker')?.value || '#000000',
            document.getElementById('subtitle-bordercolor-alpha')?.value || '100',
            document.getElementById('subtitle-bordercolor-none')?.checked || false));
        formData.append('boxborder', document.getElementById('subtitle-boxborder')?.value || '0');
        formData.append('boxcolor', buildColorValue(
            document.getElementById('subtitle-boxcolor-picker')?.value || '#000000',
            document.getElementById('subtitle-boxcolor-alpha')?.value || '80',
            document.getElementById('subtitle-boxcolor-none')?.checked || false));
        formData.append('shadowx', document.getElementById('subtitle-shadowx')?.value || '2');
        formData.append('shadowy', document.getElementById('subtitle-shadowy')?.value || '2');
        formData.append('shadowcolor', buildColorValue(
            document.getElementById('subtitle-shadowcolor-picker')?.value || '#000000',
            document.getElementById('subtitle-shadowcolor-alpha')?.value || '100',
            document.getElementById('subtitle-shadowcolor-none')?.checked || false));
        formData.append('capitalize', document.getElementById('subtitle-capitalize')?.checked ?? false);
        formData.append('crop_mode', '9:16');

        const apiKeyVal = document.getElementById('api-key-input')?.value?.trim();
        const apiProvider = document.getElementById('api-provider')?.value;
        if (apiKeyVal && apiProvider) {
            formData.append('api_provider', apiProvider);
            formData.append('api_key', apiKeyVal);
        }
        const wordsCountVal = document.getElementById('subtitle-words-count')?.value;
        const wordFadeVal = document.getElementById('subtitle-word-fade')?.checked;
        const wordsCountBackend = wordsCountVal === 'all' ? '999' : (wordsCountVal || '5');
        formData.append('words_count', wordsCountBackend);
        formData.append('word_fade', wordFadeVal ? 'true' : 'false');
        formData.append('whisper_model', document.getElementById('whisper-model')?.value || 'base');

        // Баннер
        formData.append('banner_x', document.getElementById('banner-x-settings')?.value || '0');
        formData.append('banner_y', document.getElementById('banner-y-settings')?.value || '0');
        formData.append('banner_w', document.getElementById('banner-w-settings')?.value || '1080');
        formData.append('banner_h', document.getElementById('banner-h-settings')?.value || '200');
        formData.append('banner_opacity', document.getElementById('banner-opacity-settings')?.value || '100');

        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });

        const data = await response.json();
        if (data.status === 'success') {
            const keyInput = document.getElementById('api-key-input');
            if (keyInput) keyInput.value = '';
            await loadSettings();
            loadApiKeys();
            btn.textContent = '✓ Сохранено';
            setTimeout(() => {
                btn.textContent = 'Сохранить настройки';
                btn.disabled = false;
            }, 2000);
            return;
        }
    } catch (e) {
        alert('Ошибка сохранения настроек');
    }
    btn.disabled = false;
    btn.textContent = 'Сохранить настройки';
}

// Логи
const MAX_LOG_LINES = 200;

function addLog(message, type = 'info') {
    const logsContent = document.getElementById('logs-content');
    const timestamp = new Date().toLocaleTimeString('ru-RU');

    let color = 'text-green-400';
    let icon = '●';

    if (type === 'error') {
        color = 'text-red-400';
        icon = '✗';
    } else if (type === 'success') {
        color = 'text-green-400';
        icon = '✓';
    } else if (type === 'warning') {
        color = 'text-yellow-400';
        icon = '⚠';
    } else if (type === 'progress') {
        color = 'text-blue-400';
        icon = '⟳';
    }

    const displayMessage = String(message ?? '').slice(0, 1000);
    const logLine = document.createElement('div');
    logLine.className = `${color} mb-1`;
    logLine.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${icon} ${escapeHtml(displayMessage)}`;

    logsContent.appendChild(logLine);
    if (logsContent.children.length > MAX_LOG_LINES) {
        logsContent.removeChild(logsContent.firstChild);
    }
    logsContent.scrollTop = logsContent.scrollHeight;
}

function clearLogs() {
    document.getElementById('logs-content').innerHTML = '<div class="text-gray-500">Логи очищены</div>';
}

function updateLastLog(message, type = 'info') {
    const logsContent = document.getElementById('logs-content');
    const last = logsContent.lastElementChild;
    if (!last || last.classList.contains('text-gray-500')) {
        addLog(message, type);
        return;
    }
    let color = 'text-green-400';
    let icon = '●';
    if (type === 'progress') { color = 'text-blue-400'; icon = '⟳'; }
    else if (type === 'error') { color = 'text-red-400'; icon = '✗'; }
    else if (type === 'success') { color = 'text-green-400'; icon = '✓'; }
    else if (type === 'warning') { color = 'text-yellow-400'; icon = '⚠'; }
    const timestamp = new Date().toLocaleTimeString('ru-RU');
    last.className = `${color} mb-1`;
    const displayMessage = String(message ?? '').slice(0, 1000);
    last.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${icon} ${escapeHtml(displayMessage)}`;
    logsContent.scrollTop = logsContent.scrollHeight;
}

function startLogsPolling(jobId) {
    if (logsPollingInterval) clearInterval(logsPollingInterval);
    currentJobId = jobId;
    let shownLogs = 0;

    logsPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/logs/${jobId}?after=${shownLogs}&limit=300`);
            const data = await response.json();
            const logs = data.logs || [];
            for (const log of logs) {
                addLog(log.message, log.type || 'info');
            }
            shownLogs = Number.isFinite(data.next) ? data.next : shownLogs + logs.length;

            // Обновляем этапы интеграции
            updateIntegrationStages(data.status);

            if (data.status === 'completed') {
                addLog('Задача завершена!', 'success');
                stopLogsPolling();
            } else if (data.status === 'failed') {
                addLog('Задача завершена с ошибками', 'error');
                stopLogsPolling();
            }
        } catch (error) {
            console.error('Ошибка опроса:', error);
        }
    }, 2000);
}

// Обновление этапов интеграции
function updateIntegrationStages(currentStatus) {
    const stagesList = document.getElementById('integration-stages-list');
    if (!stagesList) return;

    const stages = [
        { id: 'init', name: 'Инициализация', status: 'waiting' },
        { id: 'download', name: 'Скачивание видео', status: 'waiting' },
        { id: 'split', name: 'Нарезка на шортсы', status: 'waiting' },
        { id: 'upload', name: 'Загрузка на YouTube', status: 'waiting' },
        { id: 'schedule', name: 'Отложенная публикация', status: 'waiting' },
        { id: 'done', name: 'Завершено', status: 'waiting' }
    ];

    let currentStageId = 'init';
    switch(currentStatus) {
        case 'downloading':
            currentStageId = 'download';
            break;
        case 'processing':
            currentStageId = 'split';
            break;
        case 'uploading':
            currentStageId = 'upload';
            break;
        case 'scheduling':
            currentStageId = 'schedule';
            break;
        case 'completed':
            currentStageId = 'done';
            break;
        default:
            currentStageId = 'init';
    }

    stages.forEach(stage => {
        if (stage.id === currentStageId) {
            stage.status = 'in_progress';
        } else if (stages.findIndex(s => s.id === currentStageId) > stages.findIndex(s => s.id === stage.id)) {
            stage.status = 'completed';
        } else {
            stage.status = 'waiting';
        }
    });

    stagesList.innerHTML = stages.map(stage => {
        let icon = '⏳';
        let color = 'text-gray-500';
        if (stage.status === 'completed') {
            icon = '✅';
            color = 'text-green-400';
        } else if (stage.status === 'in_progress') {
            icon = '🔄';
            color = 'text-blue-400';
        }
        return `
            <div class="flex items-center gap-3 ${color}">
                <span class="text-lg">${icon}</span>
                <span>${stage.name}</span>
            </div>
        `;
    }).join('');

    addLog(`Текущий этап: ${currentStatus}`, 'progress');
}

function stopLogsPolling() {
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }

    // Сбрасываем флаг интеграции
    integrationRunning = false;
    const btn = document.getElementById('start-integration-btn');
    if (btn) {
        btn.textContent = 'Запустить автопубликацию';
        btn.disabled = false;
    }
}

// Загрузка списка аккаунтов
function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[char]));
}

function parseEmails(value) {
    return String(value || '')
        .split(/[\n,;]+/)
        .map(email => email.trim())
        .filter(email => email && email.includes('@'));
}

function addEmailToAccountsField(email) {
    const accountsField = document.getElementById('youtube-accounts');
    if (!accountsField || !email) return;

    const emails = parseEmails(accountsField.value);
    if (!emails.includes(email)) {
        emails.push(email);
        accountsField.value = emails.join('\n');
    }
}

async function getEmailsForAuthorization() {
    const accountsField = document.getElementById('youtube-accounts');
    const manualEmailField = document.getElementById('manual-account-email');
    const emails = [
        ...parseEmails(accountsField ? accountsField.value : ''),
        ...parseEmails(manualEmailField ? manualEmailField.value : '')
    ];

    if (emails.length === 0) {
        try {
            const response = await fetch('/api/youtube/accounts');
            const data = await response.json();
            if (data.status === 'success') {
                emails.push(...data.accounts.map(acc => acc.email));
            }
        } catch (error) {
            console.error('Ошибка загрузки сохраненных аккаунтов:', error);
        }
    }

    return [...new Set(emails)];
}

async function loadAccountsList() {
    try {
        const response = await fetch('/api/youtube/accounts');
        const data = await response.json();

        const container = document.getElementById('accounts-list');
        const refreshBtn = document.getElementById('refresh-accounts-btn');

        // Кратковременно меняем текст кнопки
        if (refreshBtn) {
            const originalText = refreshBtn.textContent;
            refreshBtn.textContent = '✓ Обновлено';
            refreshBtn.disabled = true;
            setTimeout(() => {
                refreshBtn.textContent = originalText;
                refreshBtn.disabled = false;
            }, 1000);
        }

        if (data.status === 'success' && data.accounts.length > 0) {
            container.innerHTML = data.accounts.map(acc => `
                <div class="flex justify-between items-center gap-3 py-2 border-b border-gray-700">
                    <span class="min-w-0 truncate">${escapeHtml(acc.email)}</span>
                    <div class="flex items-center gap-3 shrink-0">
                        <span class="${acc.has_token ? 'text-green-400' : 'text-yellow-400'}">
                            ${acc.has_token ? '✓ Авторизован' : '⚠ Нужен токен'}
                        </span>
                        <button type="button" data-delete-account="${escapeHtml(acc.email)}"
                            class="px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 transition text-xs">
                            Удалить
                        </button>
                    </div>
                </div>
            `).join('');

            container.querySelectorAll('[data-delete-account]').forEach((btn) => {
                btn.addEventListener('click', () => deleteAccount(btn.dataset.deleteAccount));
            });
        } else {
            container.innerHTML = '<p class="text-gray-500">Нет сохранённых аккаунтов</p>';
        }
    } catch (e) {
        console.error('Ошибка загрузки аккаунтов:', e);
    }
}

async function deleteAccount(email) {
    if (!confirm(`Удалить аккаунт ${email}?`)) return;

    try {
        const response = await fetch('/api/youtube/accounts', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email})
        });
        const data = await response.json();

        if (data.status !== 'success') {
            throw new Error(data.message || 'Не удалось удалить аккаунт');
        }

        loadAccountsList();
    } catch (error) {
        alert('Ошибка удаления: ' + error.message);
    }
}

// Загрузка списка шаблонов
async function loadPresets() {
    try {
        const response = await fetch('/api/presets/list');
        const data = await response.json();

        const select = document.getElementById('load-preset');
        select.innerHTML = '<option value="">-- Выберите шаблон --</option>';

        if (data.status === 'success' && data.presets.length > 0) {
            data.presets.forEach(preset => {
                const option = document.createElement('option');
                option.value = preset.name;
                option.textContent = preset.name;
                select.appendChild(option);
            });
        }
    } catch (e) {
        console.error('Ошибка загрузки шаблонов:', e);
    }
}

// Создание Shorts из файла
async function createShortsFromFile() {
    const shortLength = document.getElementById('short-length-file')?.value || '45';
    const shortsCount = document.getElementById('shorts-count-file')?.value || '5';
    const btn = document.getElementById('create-btn-file');
    const folderMode = document.getElementById('folder-mode-file')?.checked;

    btn.disabled = true;
    btn.textContent = 'Загружаем...';

    try {
        const fileInput = document.getElementById('video-file');
        if (!fileInput.files[0]) {
            btn.disabled = false;
            btn.textContent = 'Создать Shorts';
            return alert(folderMode ? 'Выберите папку' : 'Выберите файл');
        }

        const formData = new FormData();
        if (folderMode) {
            for (const f of fileInput.files) {
                if (f.type.startsWith('video/')) {
                    formData.append('files', f);
                }
            }
            if (!formData.has('files')) {
                btn.disabled = false;
                btn.textContent = 'Создать Shorts';
                return alert('В папке нет видеофайлов');
            }
        } else {
            formData.append('file', fileInput.files[0]);
        }

        formData.append('short_length', shortLength);
        formData.append('shorts_count', shortsCount);
        if (folderMode) {
            formData.append('adaptive_folder_allocation', String(document.getElementById('adaptive-folder-allocation')?.checked !== false));
        }
        formData.append('smart_selection', document.querySelector('input[name="smart-mode-file"]:checked')?.value || 'off');
        formData.append('scene_start', String(document.getElementById('scene-start-file')?.checked || false));
        formData.append('subtitle_font', document.getElementById('subtitle-font')?.value || 'Montserrat');
        formData.append('auto_duration', String(document.getElementById('auto-duration-file')?.checked || false));
        formData.append('min_short_length', document.getElementById('auto-min-file')?.value || '30');
        formData.append('max_short_length', document.getElementById('auto-max-file')?.value || '60');
        formData.append('blurred_bg', String(document.getElementById('blurred-bg-file')?.checked || false));
        formData.append('crop_mode', getCropMode('file'));
        formData.append('filename_keywords', document.getElementById('filename-keywords')?.value?.trim() || '');

        // Баннер
        const bFile = document.getElementById('banner-enabled-file');
        formData.append('banner_enabled', String(bFile?.checked || false));
        if (bFile?.checked) {
            formData.append('banner_x', document.getElementById('banner-x-settings')?.value || '0');
            formData.append('banner_y', document.getElementById('banner-y-settings')?.value || '0');
            formData.append('banner_w', document.getElementById('banner-w-settings')?.value || '1080');
            formData.append('banner_h', document.getElementById('banner-h-settings')?.value || '200');
            formData.append('banner_opacity', document.getElementById('banner-opacity-settings')?.value || '100');
            formData.append('banner_style', document.getElementById('banner-style-settings')?.value || 'overlay');
            formData.append('banner_position', document.getElementById('banner-position-settings')?.value || '50');
            formData.append('banner_duration', document.getElementById('banner-duration-settings')?.value || '3');
            formData.append('banner_full_duration', String(document.getElementById('banner-full-duration')?.checked || false));
            const bannerFile = document.getElementById('banner-file-settings')?.files?.[0];
            if (bannerFile) formData.append('banner_file', bannerFile);
        }

        // Музыка
        const audioEnable = document.getElementById('enable-audio-file');
        formData.append('enable_audio', String(audioEnable?.checked || false));
        if (audioEnable?.checked) {
            const audioFile = document.getElementById('audio-file')?.files?.[0];
            if (audioFile) {
                formData.append('audio_file', audioFile);
                formData.append('audio_start', document.getElementById('audio-start-file')?.value || '0');
                formData.append('audio_end', document.getElementById('audio-end-file')?.value || '30');
                formData.append('music_volume', String((parseInt(document.getElementById('audio-volume-file')?.value || '70') / 100)));
                formData.append('replace_audio', String(document.getElementById('replace-audio-file')?.checked || false));
            }
        }

        // AI метаданные: чекбоксы для генерации заголовка, описания, тегов
        formData.append('ai_gen_title', String(document.getElementById('ai-gen-title')?.checked || false));
        formData.append('ai_gen_description', String(document.getElementById('ai-gen-description')?.checked || false));
        formData.append('ai_gen_tags', String(document.getElementById('ai-gen-tags')?.checked || false));

        document.getElementById('progress-section')?.classList.remove('hidden');
        document.getElementById('results-section')?.classList.add('hidden');
        document.getElementById('shorts-list').innerHTML = '';
        clearLogs();
        if (folderMode) {
            addLog(`Папка: ${fileInput.files.length} видео`, 'info');
        } else {
            const fileSizeMB = (fileInput.files[0].size / 1024 / 1024).toFixed(1);
            addLog(`Файл: ${fileInput.files[0].name} (${fileSizeMB} МБ)`, 'info');
        }

        const endpoint = folderMode ? '/api/upload-folder' : '/api/upload-file';

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                const loadedMB = (e.loaded / 1024 / 1024).toFixed(1);
                const totalMB = (e.total / 1024 / 1024).toFixed(1);
                btn.textContent = `${pct}% загружено`;
                document.getElementById('progress-bar').style.width = pct + '%';
                document.getElementById('progress-text').textContent = `Загрузка: ${loadedMB}/${totalMB} МБ (${pct}%)`;
                updateLastLog(`Загрузка: ${loadedMB}/${totalMB} МБ (${pct}%)`, 'progress');
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                const data = JSON.parse(xhr.responseText);
                currentJobId = data.job_id;
                sessionStorage.setItem('currentJobId', currentJobId);
                if (data.job_id && window._sessionJobs) window._sessionJobs.push(data.job_id);
                // Never leave the submitted File object selected: otherwise a
                // second click can silently upload the previous video again.
                fileInput.value = '';
                const selectedName = document.getElementById('file-name');
                if (selectedName) {
                    selectedName.textContent = '';
                    selectedName.classList.add('hidden');
                }
                addLog('Файлы загружены! Обработка...', 'success');
                btn.textContent = 'Обрабатываем...';
                startPolling();
            } else {
                addLog('Ошибка сервера: ' + xhr.status, 'error');
                btn.disabled = false;
                btn.textContent = 'Создать Shorts';
            }
        });

        xhr.addEventListener('error', () => {
            addLog('Ошибка сети при загрузке', 'error');
            btn.disabled = false;
            btn.textContent = 'Создать Shorts';
        });

        xhr.open('POST', endpoint);
        xhr.send(formData);
    } catch (e) {
        addLog('Ошибка: ' + e.message, 'error');
        btn.disabled = false;
        btn.textContent = 'Создать Shorts';
    }
}

async function cancelCurrentJob() {
    if (!confirm('Отменить текущую обработку?')) return;
    try {
        const res = await fetch('/api/jobs/cancel', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            addLog('Обработка отменена', 'warning');
            document.getElementById('cancel-job-btn')?.classList.add('hidden');
            document.getElementById('progress-section')?.classList.add('hidden');
            const fileBtn = document.getElementById('create-btn-file');
            const urlBtn = document.getElementById('create-btn');
            if (fileBtn) { fileBtn.disabled = false; fileBtn.textContent = 'Создать Shorts'; }
            if (urlBtn) { urlBtn.disabled = false; urlBtn.textContent = 'Создать Shorts'; }
            loadStats();
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    let shownLogs = 0;
    let staleCount = 0;

    document.getElementById('cancel-job-btn')?.classList.remove('hidden');

    pollInterval = setInterval(async () => {
        const res = await fetch(`/api/status/${currentJobId}`);
        const data = await res.json();

        const pb = document.getElementById('progress-bar');
        const pt = document.getElementById('progress-text');
        if (pb) pb.style.width = data.progress + '%';
        if (pt) {
            let statusText = getStatusText(data.status);
            if (data.status === 'processing' && data.target_count > 0) {
                statusText += ` ${data.completed_count || 0}/${data.target_count}`;
                if (Number.isFinite(data.eta_seconds)) {
                    statusText += ` · осталось ${fmtTime(data.eta_seconds)}`;
                }
            }
            pt.textContent = statusText;
        }

        updateStages(data.status);

        if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
            clearInterval(pollInterval);
            document.getElementById('cancel-job-btn')?.classList.add('hidden');
            const fileBtn = document.getElementById('create-btn-file');
            const urlBtn = document.getElementById('create-btn');
            if (fileBtn) { fileBtn.disabled = false; fileBtn.textContent = 'Создать Shorts'; }
            if (urlBtn) { urlBtn.disabled = false; urlBtn.textContent = 'Создать Shorts'; }
            if (data.status === 'completed') {
                showResults(data.shorts);
                addLog('Готово!', 'success');
            } else {
                addLog('Ошибка: ' + (data.error || data.status), 'error');
            }
            loadStats();
        }

        try {
            const logsRes = await fetch(`/api/logs/${currentJobId}?after=${shownLogs}&limit=300`);
            const logsData = await logsRes.json();
            const logs = logsData.logs || [];
            for (const log of logs) {
                addLog(log.message, log.type || 'info');
            }
            shownLogs = Number.isFinite(logsData.next) ? logsData.next : shownLogs + logs.length;
        } catch(e) {}
    }, 2000);
}

function getStatusText(status) {
    const texts = {
        'downloading': 'Скачивание...',
        'processing': 'Обработка...',
        'completed': 'Готово!',
        'failed': 'Ошибка',
        'queued': 'В очереди',
        'cancelled': 'Отменено'
    }
    return texts[status] || 'Обработка...';
}

function showResults(shorts) {
    currentShorts = shorts;
    document.getElementById('progress-section')?.classList.add('hidden');
    document.getElementById('results-section')?.classList.remove('hidden');

    const downloadBtn = document.getElementById('download-all-zip-btn');
    if (shorts.length > 0) {
        downloadBtn.classList.remove('hidden');
        downloadBtn.textContent = '📦 Подготовить ZIP (' + shorts.length + ')';
    }

    const container = document.getElementById('shorts-list');
    container.innerHTML = shorts.map(short => `
        <div class="card rounded-2xl p-6">
            <div class="flex gap-4 mb-4">
                <div class="w-32 h-56 bg-gray-800 rounded-lg flex items-center justify-center text-4xl">
                    Видео
                </div>
                <div class="flex-1">
                    <input type="text" class="w-full bg-transparent text-xl font-bold mb-2 border-b border-gray-700 focus:border-purple-500 focus:outline-none"
                        value="${short.title}" data-id="${short.id}" data-field="title">
                    <textarea class="w-full bg-transparent text-gray-400 text-sm mb-2 border-b border-gray-700 focus:border-purple-500 focus:outline-none resize-none"
                        rows="2" data-id="${short.id}" data-field="description">${short.description}</textarea>
                    <input type="text" class="w-full bg-transparent text-purple-400 text-sm border-b border-gray-700 focus:border-purple-500 focus:outline-none"
                        value="${short.tags.join(', ')}" data-id="${short.id}" data-field="tags">
                </div>
            </div>
            <div class="flex gap-3">
                <button onclick="saveChanges('${short.id}')" class="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-700 transition">
                    Сохранить
                </button>
                <a href="/api/download/${short.id}" class="px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 transition">
                    Скачать
                </a>
            </div>
        </div>
    `).join('');
}

async function saveChanges(shortId) {
    const card = document.querySelector(`[data-id="${shortId}"]`)?.closest('.card');
    if (!card) return alert('Ошибка: карточка не найдена');
    const title = card.querySelector('[data-field="title"]')?.value || '';
    const description = card.querySelector('[data-field="description"]')?.value || '';
    const tags = card.querySelector('[data-field="tags"]')?.value || '';

    await fetch(`/api/update-short/${shortId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `title=${encodeURIComponent(title)}&description=${encodeURIComponent(description)}&tags=${encodeURIComponent(tags)}`
    });

    alert('Сохранено!');
}

async function downloadAllAsZip() {
    if (!currentJobId) return alert('Нет готовой задачи для скачивания');

    const btn = document.getElementById('download-all-zip-btn');
    const originalText = btn.textContent;
    btn.textContent = 'Считаем ZIP-части...';
    btn.disabled = true;

    try {
        const response = await fetch('/api/download-zip/' + encodeURIComponent(currentJobId) + '/manifest');
        if (!response.ok) {
            let message = 'Ошибка ZIP: HTTP ' + response.status;
            try {
                const data = await response.json();
                message = data.message || data.detail || message;
            } catch (_) {}
            throw new Error(message);
        }

        const data = await response.json();
        const parts = data.parts || data.data?.parts || [];
        if (!parts.length) throw new Error('Сервер не нашёл готовых файлов');

        let container = document.getElementById('download-zip-parts');
        if (!container) {
            container = document.createElement('div');
            container.id = 'download-zip-parts';
            container.className = 'mt-3 p-4 rounded-xl bg-gray-900 border border-gray-700 space-y-2';
            btn.insertAdjacentElement('afterend', container);
        }
        container.replaceChildren();

        const title = document.createElement('div');
        title.className = 'text-sm font-semibold text-gray-200';
        title.textContent = parts.length === 1
            ? 'Архив готов к скачиванию:'
            : `Архив разделён на ${parts.length} части до 1,5 ГБ:`;
        container.appendChild(title);

        parts.forEach((part) => {
            const link = document.createElement('a');
            link.href = part.url;
            link.className = 'block px-4 py-3 rounded-lg bg-green-700 hover:bg-green-600 transition text-sm';
            const sizeGb = (Number(part.media_size || 0) / (1024 ** 3)).toFixed(2);
            const folders = Array.isArray(part.folders) ? part.folders.join(', ') : '';
            link.textContent = `⬇ ${part.filename} — ${sizeGb} ГБ${folders ? ' — ' + folders : ''}`;
            link.title = 'ZIP создастся на сервере после нажатия; это может занять некоторое время';
            container.appendChild(link);
        });

        const hint = document.createElement('div');
        hint.className = 'text-xs text-gray-500';
        hint.textContent = parts.length > 1
            ? 'Скачивайте части по очереди. Каждая ссылка загружает ZIP напрямую, без хранения всего архива в памяти браузера.'
            : 'ZIP загружается напрямую, без хранения всего архива в памяти страницы.';
        container.appendChild(hint);
    } catch (error) {
        console.error('ZIP download failed:', error);
        alert('Не удалось скачать ZIP: ' + error.message);
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}
// Запуск интеграции
let integrationRunning = false;

async function startIntegration() {
    if (integrationRunning) {
        console.log('Интеграция уже запущена, пропускаем...');
        return;
    }

    integrationRunning = true;
    const btn = document.getElementById('start-integration-btn');
    btn.disabled = true;
    btn.textContent = 'Запускаем...';

    try {
        const formData = new FormData();

        const source = document.getElementById('integration-source')?.value || 'url';
        formData.append('source', source);

        if (source === 'url') {
            const url = document.getElementById('integration-video-url')?.value || '';
            if (!url) {
                alert('Введите YouTube URL');
                btn.disabled = false;
                btn.textContent = 'Запустить автопубликацию';
                return;
            }
            formData.append('video_url', url);
        } else {
            const file = document.getElementById('integration-video-file').files[0];
            if (!file) {
                alert('Выберите файл');
                btn.disabled = false;
                btn.textContent = 'Запустить автопубликацию';
                return;
            }
            formData.append('video_file', file);
        }

        // Показываем окно этапов
        document.getElementById('integration-stages-window')?.classList.remove('hidden');

        const accounts = document.getElementById('youtube-accounts')?.value || '';
        if (!accounts.trim()) {
            alert('Добавьте хотя бы один YouTube аккаунт');
            btn.disabled = false;
            btn.textContent = 'Запустить автопубликацию';
            return;
        }
        formData.append('accounts', accounts);
        formData.append('distribution_mode', document.getElementById('distribution-mode')?.value || 'equal');
        formData.append('custom_distribution', document.getElementById('custom-distribution')?.value || '');
        formData.append('videos_per_day', document.getElementById('videos-per-day')?.value || '3');
        formData.append('short_length', document.getElementById('integration-short-length')?.value || '45');
        formData.append('shorts_count', document.getElementById('integration-shorts-count')?.value || '5');
        formData.append('blurred_bg', String(document.getElementById('integration-blurred-bg').checked));
        formData.append('crop_mode', getCropMode('integration'));
        formData.append('smart_selection', document.querySelector('input[name="smart-mode-integration"]:checked')?.value || 'off');
        formData.append('scene_start', String(document.getElementById('scene-start-integration')?.checked || false));
        formData.append('subtitle_font', document.getElementById('subtitle-font')?.value || 'Montserrat');
        formData.append('auto_duration', String(document.getElementById('auto-duration-integration')?.checked || false));
        formData.append('min_short_length', document.getElementById('auto-min-integration')?.value || '30');
        formData.append('max_short_length', document.getElementById('auto-max-integration')?.value || '60');

        // Баннер
        const bInt = document.getElementById('banner-enabled-integration');
        formData.append('banner_enabled', String(bInt?.checked || false));
        if (bInt?.checked) {
            formData.append('banner_x', document.getElementById('banner-x-settings')?.value || '0');
            formData.append('banner_y', document.getElementById('banner-y-settings')?.value || '0');
            formData.append('banner_w', document.getElementById('banner-w-settings')?.value || '1080');
            formData.append('banner_h', document.getElementById('banner-h-settings')?.value || '200');
            formData.append('banner_opacity', document.getElementById('banner-opacity-settings')?.value || '100');
            formData.append('banner_style', document.getElementById('banner-style-settings')?.value || 'overlay');
            formData.append('banner_position', document.getElementById('banner-position-settings')?.value || '50');
            formData.append('banner_duration', document.getElementById('banner-duration-settings')?.value || '3');
            formData.append('banner_full_duration', String(document.getElementById('banner-full-duration')?.checked || false));
            const bannerFile = document.getElementById('banner-file-settings')?.files?.[0];
            if (bannerFile) formData.append('banner_file', bannerFile);
        }

        // Музыка
        formData.append('enable_audio', document.getElementById('enable-audio').checked);
        if (document.getElementById('enable-audio')?.checked) {
            const audioFile = document.getElementById('integration-audio-file')?.files?.[0];
            if (audioFile) {
                formData.append('audio_file', audioFile);
                formData.append('audio_start', document.getElementById('audio-start')?.value || '0');
                formData.append('audio_end', document.getElementById('audio-end')?.value || '30');
                formData.append('music_volume', String((parseInt(document.getElementById('audio-volume')?.value || '70') / 100)));
                formData.append('replace_audio', document.getElementById('replace-audio')?.checked || false);
            }
        }

        // AI метаданные: чекбоксы для генерации заголовка, описания, тегов
        formData.append('ai_gen_title', String(document.getElementById('ai-gen-title')?.checked || false));
        formData.append('ai_gen_description', String(document.getElementById('ai-gen-description')?.checked || false));
        formData.append('ai_gen_tags', String(document.getElementById('ai-gen-tags')?.checked || false));

        // Теги
        formData.append('enable_required_tags', document.getElementById('enable-required-tags')?.checked || false);
        formData.append('required_tags', document.getElementById('required-tags')?.value || '');
        formData.append('enable_optional_tags', document.getElementById('enable-optional-tags')?.checked || false);

        // Отложенная публикация
        formData.append('enable_scheduled', document.getElementById('enable-scheduled')?.checked || false);
        if (document.getElementById('enable-scheduled')?.checked) {
            formData.append('schedule_start_date', document.getElementById('schedule-start-date')?.value || '');
            formData.append('schedule_start_time', document.getElementById('schedule-start-time')?.value || '12:00');
            formData.append('schedule_interval', document.getElementById('schedule-interval')?.value || '60');
        }

        const response = await fetch('/api/integration/start', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) throw new Error('Ошибка запуска');

        const data = await response.json();
        currentJobId = data.job_id;
        sessionStorage.setItem('currentJobId', currentJobId);
        if (data.job_id && window._sessionJobs) window._sessionJobs.push(data.job_id);

        // Показываем окно логов
        clearLogs();
        addLog(`Интеграция запущена! Job ID: ${data.job_id}`, 'success');

        // Начинаем polling логов
        startLogsPolling(data.job_id);

        btn.textContent = 'Запущено ✓';
        // НЕ сбрасываем кнопку сразу - ждем завершения задачи
    } catch (error) {
        alert('Ошибка: ' + error.message);
        btn.textContent = 'Запустить автопубликацию';
        btn.disabled = false;
        integrationRunning = false;
    }
}

// Загрузка учетных данных
async function uploadCredentials() {
    const btn = document.getElementById('upload-credentials-btn');
    const email = document.getElementById('manual-account-email').value.trim();
    const fileInput = document.getElementById('manual-credentials-file');

    if (!email) {
        alert('Введите email аккаунта');
        return;
    }
    if (!fileInput.files[0]) {
        alert('Выберите client_secret.json файл');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Загружаем...';

    try {
        const formData = new FormData();
        formData.append('email', email);
        formData.append('credentials', fileInput.files[0]);

        const response = await fetch('/api/youtube/upload-credentials', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.status === 'success') {
            alert('Аккаунт ' + email + ' добавлен!');
            addEmailToAccountsField(email);
            document.getElementById('manual-account-email').value = '';
            document.getElementById('manual-credentials-file').value = '';
            loadAccountsList();
        } else {
            alert('Ошибка: ' + data.message);
        }

        btn.disabled = false;
        btn.textContent = '✓ Добавить аккаунт';

    } catch (error) {
        alert('Ошибка: ' + error.message);
        btn.textContent = '✓ Добавить аккаунт';
        btn.disabled = false;
    }
}

// Авторизация аккаунтов
async function authorizeAccounts() {
    const btn = document.getElementById('authorize-accounts-btn');
    const emails = await getEmailsForAuthorization();

    if (emails.length === 0) {
        alert('Введите email аккаунта или сначала добавьте сохраненный аккаунт');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Авторизация...';

    try {
        for (let i = 0; i < emails.length; i++) {
            const email = emails[i];
            btn.textContent = `Авторизация ${i + 1}/${emails.length}: ${email}`;

            const response = await fetch('/api/youtube/authorize', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: email})
            });

            const data = await response.json();

            if (data.status === 'success') {
                console.log('OK ' + email + ' авторизован');
            } else if (data.status === 'needs_auth') {
                alert(`Откроется браузер для авторизации: ${email}\n\nВойдите в аккаунт и разрешите доступ.`);
                await new Promise(resolve => setTimeout(resolve, 2000));
            } else {
                alert(`Ошибка авторизации ${email}: ${data.message}`);
            }
        }

        alert(`Авторизация завершена! Авторизовано ${emails.length} аккаунтов.`);
        loadAccountsList();
        btn.textContent = '✓ Все аккаунты авторизованы';
        setTimeout(() => {
            btn.textContent = '🔐 Авторизовать';
            btn.disabled = false;
        }, 3000);

    } catch (error) {
        alert('Ошибка: ' + error.message);
        btn.textContent = '🔐 Авторизовать';
        btn.disabled = false;
    }
}

// Сохранение шаблона
async function savePreset() {
    const name = document.getElementById('preset-name').value.trim();
    if (!name) {
        alert('Введите название шаблона');
        return;
    }

    const preset = {
        name: name,
        // Субтитры
        subtitle_font: document.getElementById('subtitle-font')?.value || 'Montserrat',
        subtitle_fontsize: document.getElementById('subtitle-fontsize')?.value || '100',
        subtitle_position: document.getElementById('subtitle-position')?.value || '1670',
        subtitle_capitalize: document.getElementById('subtitle-capitalize')?.checked || false,
        subtitle_borderw: document.getElementById('subtitle-borderw')?.value || '0',
        subtitle_bordercolor: document.getElementById('subtitle-bordercolor-picker')?.value || '#000000',
        subtitle_bordercolor_alpha: document.getElementById('subtitle-bordercolor-alpha')?.value || '100',
        subtitle_bordercolor_none: document.getElementById('subtitle-bordercolor-none')?.checked || false,
        subtitle_boxborder: document.getElementById('subtitle-boxborder')?.value || '0',
        subtitle_boxcolor: document.getElementById('subtitle-boxcolor-picker')?.value || '#000000',
        subtitle_boxcolor_alpha: document.getElementById('subtitle-boxcolor-alpha')?.value || '80',
        subtitle_boxcolor_none: document.getElementById('subtitle-boxcolor-none')?.checked || false,
        subtitle_shadowx: document.getElementById('subtitle-shadowx')?.value || '2',
        subtitle_shadowy: document.getElementById('subtitle-shadowy')?.value || '2',
        subtitle_shadowcolor: document.getElementById('subtitle-shadowcolor-picker')?.value || '#000000',
        subtitle_shadowcolor_alpha: document.getElementById('subtitle-shadowcolor-alpha')?.value || '100',
        subtitle_shadowcolor_none: document.getElementById('subtitle-shadowcolor-none')?.checked || false,
        filename_keywords: document.getElementById('filename-keywords')?.value || '',
    };

    try {
        const response = await fetch('/api/presets/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(preset)
        });

        const data = await response.json();
        if (data.status === 'success') {
            alert('Шаблон сохранён!');
            document.getElementById('preset-name').value = '';
            loadPresets();
        } else {
            alert('Ошибка: ' + data.message);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

// Удаление шаблона
async function deletePreset() {
    const select = document.getElementById('load-preset');
    const name = select.value;
    if (!name) {
        alert('Выберите шаблон для удаления');
        return;
    }
    if (!confirm('Удалить шаблон «' + name + '»?')) return;

    try {
        const response = await fetch('/api/presets/delete?name=' + encodeURIComponent(name), {
            method: 'DELETE'
        });
        const data = await response.json();
        if (data.status === 'success') {
            alert('Шаблон удалён!');
            loadPresets();
        } else {
            alert('Ошибка: ' + (data.message || 'Не удалось удалить'));
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

// Загрузка шаблона из списка
async function loadPresetFromSelect(e) {
    const name = e.target.value;
    if (!name) return;

    try {
        const response = await fetch(`/api/presets/load?name=${encodeURIComponent(name)}`);
        const data = await response.json();

        if (data.status === 'success' && data.preset) {
            const p = data.preset;

            // Субтитры
            if (p.subtitle_font) document.getElementById('subtitle-font').value = p.subtitle_font;
            if (p.subtitle_fontsize) document.getElementById('subtitle-fontsize').value = p.subtitle_fontsize;
            if (p.subtitle_position) document.getElementById('subtitle-position').value = p.subtitle_position;
            if (p.subtitle_capitalize !== undefined) document.getElementById('subtitle-capitalize').checked = p.subtitle_capitalize;
            if (p.subtitle_borderw !== undefined) document.getElementById('subtitle-borderw').value = p.subtitle_borderw;
            if (p.subtitle_bordercolor) document.getElementById('subtitle-bordercolor-picker').value = p.subtitle_bordercolor;
            if (p.subtitle_bordercolor_alpha !== undefined) document.getElementById('subtitle-bordercolor-alpha').value = p.subtitle_bordercolor_alpha;
            if (p.subtitle_bordercolor_none !== undefined) document.getElementById('subtitle-bordercolor-none').checked = p.subtitle_bordercolor_none;
            if (p.subtitle_boxborder !== undefined) document.getElementById('subtitle-boxborder').value = p.subtitle_boxborder;
            if (p.subtitle_boxcolor) document.getElementById('subtitle-boxcolor-picker').value = p.subtitle_boxcolor;
            if (p.subtitle_boxcolor_alpha !== undefined) document.getElementById('subtitle-boxcolor-alpha').value = p.subtitle_boxcolor_alpha;
            if (p.subtitle_boxcolor_none !== undefined) document.getElementById('subtitle-boxcolor-none').checked = p.subtitle_boxcolor_none;
            if (p.subtitle_shadowx !== undefined) document.getElementById('subtitle-shadowx').value = p.subtitle_shadowx;
            if (p.subtitle_shadowy !== undefined) document.getElementById('subtitle-shadowy').value = p.subtitle_shadowy;
            if (p.subtitle_shadowcolor) document.getElementById('subtitle-shadowcolor-picker').value = p.subtitle_shadowcolor;
            if (p.subtitle_shadowcolor_alpha !== undefined) document.getElementById('subtitle-shadowcolor-alpha').value = p.subtitle_shadowcolor_alpha;
            if (p.subtitle_shadowcolor_none !== undefined) document.getElementById('subtitle-shadowcolor-none').checked = p.subtitle_shadowcolor_none;
            if (p.filename_keywords !== undefined) document.getElementById('filename-keywords').value = p.filename_keywords;

            updateSubtitlePreview();
            alert('Шаблон загружен!');
        }
    } catch (e) {
        alert('Ошибка загрузки шаблона: ' + e.message);
    }
}

// ==================== Предпросмотр субтитров ====================

function getPreviewFrameMetrics() {
    return { format: '9:16', frameW: 1080, frameH: 1920, width: 180, height: 320 };
}

function updateSubtitlePreview() {
    const text = document.getElementById('preview-text')?.value || 'Текст субтитров';
    const font = document.getElementById('subtitle-font')?.value || 'Montserrat';
    const style = document.getElementById('subtitle-style')?.value || 'normal';
    const fontsize = parseInt(document.getElementById('subtitle-fontsize')?.value || '100');
    const fontColorHex = document.getElementById('subtitle-color-picker')?.value || '#ffffff';
    const fontAlpha = (parseInt(document.getElementById('subtitle-color-alpha')?.value || '100')) / 100;
    const position = parseInt(document.getElementById('subtitle-position')?.value || '1670');
    const borderw = parseInt(document.getElementById('subtitle-borderw')?.value || '3');
    const borderColorHex = document.getElementById('subtitle-bordercolor-picker')?.value || '#000000';
    const borderColorNone = document.getElementById('subtitle-bordercolor-none')?.checked || false;
    const borderAlpha = (parseInt(document.getElementById('subtitle-bordercolor-alpha')?.value || '100')) / 100;
    const boxborder = parseInt(document.getElementById('subtitle-boxborder')?.value || '0');
    const boxColorHex = document.getElementById('subtitle-boxcolor-picker')?.value || '#000000';
    const boxColorNone = document.getElementById('subtitle-boxcolor-none')?.checked || false;
    const boxAlpha = (parseInt(document.getElementById('subtitle-boxcolor-alpha')?.value || '80')) / 100;
    const shadowx = parseInt(document.getElementById('subtitle-shadowx')?.value || '2');
    const shadowy = parseInt(document.getElementById('subtitle-shadowy')?.value || '2');
    const shadowColorHex = document.getElementById('subtitle-shadowcolor-picker')?.value || '#000000';
    const shadowColorNone = document.getElementById('subtitle-shadowcolor-none')?.checked || false;
    const shadowAlpha = (parseInt(document.getElementById('subtitle-shadowcolor-alpha')?.value || '100')) / 100;
    const capitalize = document.getElementById('subtitle-capitalize')?.checked || false;
    const previewBg = document.getElementById('preview-bg-color')?.value || 'black';
    const metrics = getPreviewFrameMetrics();
    const preview = document.getElementById('subtitle-preview');
    if (preview) {
        preview.style.width = metrics.width + 'px';
        preview.style.height = metrics.height + 'px';
    }
    const previewScale = metrics.width / metrics.frameW;

    function rgba(hex, a) {
        const h = hex.replace('#', '');
        const r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
    }

    let finalText = text;
    if (capitalize) finalText = text.toUpperCase();

    const span = document.getElementById('preview-text-span');
    if (!span) return;

    span.textContent = finalText;
    span.style.fontFamily = '"' + font + '", Arial, sans-serif';
    if (document.fonts?.load) document.fonts.load('12px "' + font + '"').catch(() => {});
    span.style.fontSize = Math.round(fontsize * previewScale) + 'px';
    span.style.color = rgba(fontColorHex, fontAlpha);
    span.style.fontWeight = (style === 'bold' || style === 'bold_italic') ? 'bold' : 'normal';
    span.style.fontStyle = (style === 'italic' || style === 'bold_italic') ? 'italic' : 'normal';

    span.style.textShadow = 'none';
    span.style.webkitTextStroke = 'none';
    span.style.backgroundColor = 'transparent';
    span.style.padding = '0';
    span.style.borderRadius = '0';
    span.style.display = 'inline-block';
    span.style.maxWidth = '90%';

    if (borderw > 0 && !borderColorNone) {
        span.style.webkitTextStroke = Math.round(borderw * previewScale) + 'px ' + rgba(borderColorHex, borderAlpha);
    }

    if ((shadowx > 0 || shadowy > 0) && !shadowColorNone) {
        span.style.textShadow = Math.round(shadowx * previewScale) + 'px ' + Math.round(shadowy * previewScale) + 'px 2px ' + rgba(shadowColorHex, shadowAlpha);
    }

    if (boxborder > 0 && !boxColorNone) {
        span.style.backgroundColor = rgba(boxColorHex, boxAlpha);
        span.style.padding = Math.round(boxborder * previewScale) + 'px';
        span.style.borderRadius = '4px';
    }

    const layer = document.getElementById('preview-subtitle-layer');
    if (layer) {
        // в реальном рендере субтитры привязаны снизу (MarginV = 1920 - position)
        const bottomMargin = Math.round((1920 - position) * metrics.height / 1920);
        layer.style.top = 'auto';
        layer.style.bottom = bottomMargin + 'px';
    }

    if (preview) {
        preview.style.backgroundColor = previewBg;
    }

    // Preview all frame modes, including blur + zoom together.
    const previewBlur = document.getElementById('preview-blur-bg')?.checked || false;
    const previewCropMode = document.getElementById('preview-crop-mode')?.value || 'original';
    const backgroundVideo = document.getElementById('preview-video-bg');
    const foregroundVideo = document.getElementById('preview-video-fg');
    const hasPreviewVideo = !!(previewVideoUrl && foregroundVideo?.src);

    if (preview) {
        preview.style.filter = 'none';
        preview.style.transform = 'none';
    }
    if (backgroundVideo) {
        backgroundVideo.style.display = hasPreviewVideo && previewBlur ? 'block' : 'none';
        backgroundVideo.style.objectPosition = '50% 50%';
    }
    if (foregroundVideo) {
        foregroundVideo.style.display = hasPreviewVideo ? 'block' : 'none';
        foregroundVideo.style.transform = 'none';
        foregroundVideo.style.left = '0%';
        foregroundVideo.style.inset = 'auto';
        foregroundVideo.style.objectPosition = '50% 50%';
        let wrapper = document.getElementById('preview-crop-wrapper');
        if (previewCropMode === 'square') {
            if (!wrapper) {
                wrapper = document.createElement('div');
                wrapper.id = 'preview-crop-wrapper';
                wrapper.style.cssText = 'position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);height:56.25%;z-index:1;overflow:hidden;';
                foregroundVideo.parentElement.insertBefore(wrapper, foregroundVideo);
            }
            if (foregroundVideo.parentElement !== wrapper) wrapper.appendChild(foregroundVideo);
            foregroundVideo.style.position = 'relative';
            foregroundVideo.style.objectFit = 'cover';
            foregroundVideo.style.width = '100%';
            foregroundVideo.style.height = '100%';
            foregroundVideo.style.top = '0%';
        } else {
            if (wrapper && foregroundVideo.parentElement === wrapper) {
                foregroundVideo.parentElement.parentElement.insertBefore(foregroundVideo, wrapper);
                wrapper.remove();
            }
            foregroundVideo.style.position = 'absolute';
            if (previewCropMode === 'vertical') {
                foregroundVideo.style.objectFit = 'cover';
                foregroundVideo.style.width = '100%';
                foregroundVideo.style.height = '100%';
                foregroundVideo.style.top = '0%';
            } else {
                foregroundVideo.style.objectFit = 'contain';
                foregroundVideo.style.width = '100%';
                foregroundVideo.style.height = '100%';
                foregroundVideo.style.top = '0%';
            }
        }
    }
    // Баннер в предпросмотре (показывается если галочка включена и выбран файл)
    const bannerEnabled = document.getElementById('banner-enabled-settings')?.checked || false;
    const bannerLayer = document.getElementById('preview-banner-layer');
    const bannerImg = document.getElementById('preview-banner-img');
    const bannerVideo = document.getElementById('preview-banner-video');
    if (bannerLayer && bannerImg) {
        const fileInput = document.getElementById('banner-file-settings');
        if (bannerEnabled && fileInput?.files?.[0]) {
            if (!window._bannerPreviewUrl || window._bannerPreviewFile !== fileInput.files[0]) {
                window._bannerPreviewFile = fileInput.files[0];
                const isVideo = fileInput.files[0].type.startsWith('video/');
                if (isVideo) {
                    if (window._bannerPreviewUrl && window._bannerPreviewUrl.startsWith('blob:')) URL.revokeObjectURL(window._bannerPreviewUrl);
                    window._bannerPreviewUrl = URL.createObjectURL(fileInput.files[0]);
                    applyBannerPreview(bannerImg, bannerVideo, bannerLayer, true);
                } else {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        window._bannerPreviewUrl = e.target.result;
                        applyBannerPreview(bannerImg, bannerVideo, bannerLayer, false);
                    };
                    reader.readAsDataURL(fileInput.files[0]);
                    return;
                }
                return;
            }
            const isVideo = fileInput.files[0].type.startsWith('video/');
            applyBannerPreview(bannerImg, bannerVideo, bannerLayer, isVideo);
        } else {
            bannerLayer.style.display = 'none';
            const ro = document.getElementById('banner-size-readout');
            if (ro) ro.textContent = 'Баннер: файл не выбран';
        }
    }
    const rectLayer = document.getElementById('preview-rect-layer');
    const rectEnabled = document.getElementById('preview-rect-enable')?.checked || false;
    if (rectLayer) {
        let rect = document.getElementById('preview-rect-element');
        if (!rect) {
            rect = document.createElement('div');
            rect.id = 'preview-rect-element';
            rect.style.position = 'absolute';
            rect.style.pointerEvents = 'none';
            rectLayer.appendChild(rect);
        }

        if (rectEnabled) {
            const bx = parseInt(document.getElementById('banner-x-settings')?.value || '0');
            const by = parseInt(document.getElementById('banner-y-settings')?.value || '0');
            const bw = parseInt(document.getElementById('banner-w-settings')?.value || '1080');
            const bh = parseInt(document.getElementById('banner-h-settings')?.value || '200');
            const alpha = (parseInt(document.getElementById('preview-rect-alpha')?.value || '80')) / 100;
            rect.style.left = Math.round(bx * metrics.width / metrics.frameW) + 'px';
            rect.style.top = Math.round(by * metrics.height / metrics.frameH) + 'px';
            rect.style.width = Math.round(bw * metrics.width / metrics.frameW) + 'px';
            rect.style.height = Math.round(bh * metrics.height / metrics.frameH) + 'px';
            rect.style.backgroundColor = rgba(
                document.getElementById('preview-rect-color')?.value || '#ff0000',
                alpha
            );
            rect.style.display = 'block';
        } else {
            rect.style.display = 'none';
        }
    }
}

function applyBannerPreview(bannerImg, bannerVideo, bannerLayer, isVideo) {
    if (!window._bannerPreviewUrl) return;
    let bw = parseInt(document.getElementById('banner-w-settings')?.value || '1080');
    let bh = parseInt(document.getElementById('banner-h-settings')?.value || '200');
    let bx = parseInt(document.getElementById('banner-x-settings')?.value || '0');
    let by = parseInt(document.getElementById('banner-y-settings')?.value || '0');
    const op = parseInt(document.getElementById('banner-opacity-settings')?.value || '100');
    const style = document.getElementById('banner-style-settings')?.value || 'overlay';
    const metrics = getPreviewFrameMetrics();
    // в режиме "пауза по середине" баннер центрируется — как в реальном рендере
    if (style === 'pause') {
        bx = (metrics.frameW - bw) / 2 + bx;
        by = (metrics.frameH - bh) / 2 + by;
    }
    const scaleW = metrics.width / metrics.frameW;
    const scaleH = metrics.height / metrics.frameH;
    const el = isVideo ? bannerVideo : bannerImg;
    const other = isVideo ? bannerImg : bannerVideo;
    el.src = window._bannerPreviewUrl;
    el.style.width = Math.round(bw * scaleW) + 'px';
    el.style.height = Math.round(bh * scaleH) + 'px';
    el.style.position = 'absolute';
    el.style.left = Math.round(bx * scaleW) + 'px';
    el.style.top = Math.round(by * scaleH) + 'px';
    el.style.objectFit = 'fill';
    el.style.opacity = op / 100;
    el.style.display = 'block';
    other.style.display = 'none';
    bannerLayer.style.display = 'block';
    const ro = document.getElementById('banner-size-readout');
    if (ro) {
        const fitW = Math.round(bw * scaleW);
        const fitH = Math.round(bh * scaleH);
        const overflowNote = (bw > metrics.frameW || bx < 0 || bx + bw > metrics.frameW || by < 0 || by + bh > metrics.frameH)
            ? ' — ⚠ выходит за кадр' : '';
        ro.textContent = `Баннер: ${bw}×${bh} → в превью ${fitW}×${fitH} px${overflowNote}`;
    }
}

function initTabs() {}

function initSubtitlePreview() {
    const ids = [
        'subtitle-font', 'subtitle-style', 'subtitle-fontsize',
        'subtitle-color-picker', 'subtitle-color-alpha',
        'subtitle-position', 'subtitle-borderw',
        'subtitle-bordercolor-picker', 'subtitle-bordercolor-alpha', 'subtitle-bordercolor-none',
        'subtitle-boxborder', 'subtitle-boxcolor-picker', 'subtitle-boxcolor-alpha', 'subtitle-boxcolor-none',
        'subtitle-shadowx', 'subtitle-shadowy',
        'subtitle-shadowcolor-picker', 'subtitle-shadowcolor-alpha', 'subtitle-shadowcolor-none',
        'preview-text', 'preview-bg-color', 'subtitle-capitalize',
        'banner-x-settings', 'banner-y-settings', 'banner-w-settings', 'banner-h-settings',
        'banner-style-settings', 'banner-opacity-settings',
        'preview-blur-bg', 'preview-crop-mode', 'preview-rect-enable',
        'preview-rect-color', 'preview-rect-alpha', 'banner-enabled-settings'
    ];

    [...new Set(ids)].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', updateSubtitlePreview);
        el.addEventListener('change', updateSubtitlePreview);
    });

    [
        ['subtitle-color-alpha', 'subtitle-color-alpha-val'],
        ['subtitle-bordercolor-alpha', 'subtitle-bordercolor-alpha-val'],
        ['subtitle-boxcolor-alpha', 'subtitle-boxcolor-alpha-val'],
        ['subtitle-shadowcolor-alpha', 'subtitle-shadowcolor-alpha-val'],
        ['preview-rect-alpha', 'preview-rect-alpha-val']
    ].forEach(([sliderId, labelId]) => {
        const slider = document.getElementById(sliderId);
        const label = document.getElementById(labelId);
        if (slider && label) {
            const updateLabel = () => { label.textContent = slider.value + '%'; };
            slider.addEventListener('input', updateLabel);
            updateLabel();
        }
    });

    [
        ['audio-volume', 'audio-volume-val'],
        ['audio-volume-file', 'audio-volume-file-val']
    ].forEach(([sliderId, labelId]) => {
        const slider = document.getElementById(sliderId);
        const label = document.getElementById(labelId);
        if (slider && label) {
            const updateLabel = () => { label.textContent = slider.value + '%'; };
            slider.addEventListener('input', updateLabel);
            updateLabel();
        }
    });

    const rectEnable = document.getElementById('preview-rect-enable');
    const rectOptions = document.getElementById('preview-rect-options');
    if (rectEnable && rectOptions) {
        const syncRectOptions = () => {
            rectOptions.style.display = rectEnable.checked ? 'flex' : 'none';
        };
        rectEnable.addEventListener('change', syncRectOptions);
        syncRectOptions();
    }

    updateSubtitlePreview();
}

document.addEventListener('DOMContentLoaded', initSubtitlePreview);
async function loadProjects() {
    try {
        const res = await fetch('/api/projects');
        const data = await res.json();
        const container = document.getElementById('projects-list');
        if (!container) return;

        if (!data.projects || data.projects.length === 0) {
            container.innerHTML = '<p class="text-gray-500">Нет проектов</p>';
            return;
        }

        container.innerHTML = data.projects.map(p => {
            const projectId = p.id || p.job_id;
            if (!projectId) return '';
            const createdAt = typeof p.created_at === 'number'
                ? new Date(p.created_at * 1000)
                : new Date(String(p.created_at || '').replace(' ', 'T'));
            const date = Number.isNaN(createdAt.getTime()) ? '—' : createdAt.toLocaleString('ru-RU');
            const statusColors = { 'completed': 'text-green-400', 'failed': 'text-red-400', 'processing': 'text-blue-400', 'downloading': 'text-yellow-400' };
            const statusIcons = { 'completed': '✅', 'failed': '❌', 'processing': '🔄', 'downloading': '⏳' };
            const sc = statusColors[p.status] || 'text-gray-400';
            const si = statusIcons[p.status] || '❓';
            return `
            <div class="p-4 bg-gray-800 rounded-xl border border-gray-700">
                <div class="flex items-center justify-between">
                    <div>
                        <div class="font-medium">${si} ${projectId.substring(0, 8)}...</div>
                        <div class="text-sm text-gray-500">${date}</div>
                        <div class="text-sm ${sc}">${p.status} — ${p.shorts_count} шортсов</div>
                        ${p.save_folder ? `<div class="text-xs text-gray-600">Папка: ${p.save_folder}</div>` : ''}
                    </div>
                    <button onclick="deleteProject('${projectId}')" class="px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-xs">🗑</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        console.error('Failed to load projects:', e);
    }
}

async function deleteProject(jobId) {
    if (!confirm('Удалить проект и все его файлы?')) return;
    try {
        const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            window._sessionJobs = (window._sessionJobs || []).filter(id => id !== jobId);
            if (currentJobId === jobId) {
                currentJobId = null;
                sessionStorage.removeItem('currentJobId');
            }

            loadProjects();
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}
