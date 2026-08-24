// Основной скрипт Video Bot

let currentTab = 'url';
let currentJobId = null;
let pollInterval = null;
let lastShownLog = '';
let logsPollingInterval = null;
let currentShorts = [];

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
    document.getElementById('tab-url').className = tab === 'url' 
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-file').className = tab === 'file'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-settings').className = tab === 'settings'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-integration').className = tab === 'integration'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('tab-cleanup').className = tab === 'cleanup'
        ? 'flex-1 py-3 rounded-xl font-medium bg-purple-600 hover:bg-purple-700 transition'
        : 'flex-1 py-3 rounded-xl font-medium bg-gray-700 hover:bg-gray-600 transition';
    document.getElementById('section-url').classList.toggle('hidden', tab !== 'url');
    document.getElementById('section-file').classList.toggle('hidden', tab !== 'file');
    document.getElementById('section-settings').classList.toggle('hidden', tab !== 'settings');
    document.getElementById('section-integration').classList.toggle('hidden', tab !== 'integration');
    document.getElementById('section-cleanup').classList.toggle('hidden', tab !== 'cleanup');
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

async function loadFonts() {
    try {
        const res = await fetch('/api/fonts');
        const data = await res.json();
        const sel = document.getElementById('subtitle-font');
        if (sel && data.fonts) {
            sel.innerHTML = data.fonts.map(f => `<option value="${f}">${f}</option>`).join('');
        }
    } catch (e) {
        console.error('Ошибка загрузки шрифтов:', e);
    }
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

async function cleanupOld() {
    try {
        const res = await fetch('/api/cleanup', {method: 'POST'});
        const data = await res.json();
        if (data.deleted > 0) console.log(`[CLEANUP] Удалено ${data.deleted} файлов`);
    } catch (e) {
        console.error('Ошибка очистки:', e);
    }
}

async function logout() {
    try {
        await fetch('/api/logout', {method: 'POST'});
    } catch (e) {}
    window.location.href = '/login';
}

// Инициализация после загрузки страницы
document.addEventListener('DOMContentLoaded', async function() {
    console.log('Страница загружена');
    
    safeAddListener('tab-url', 'click', () => switchTab('url'));
    safeAddListener('tab-file', 'click', () => switchTab('file'));
    safeAddListener('tab-settings', 'click', () => switchTab('settings'));
    safeAddListener('tab-integration', 'click', () => switchTab('integration'));
    safeAddListener('tab-cleanup', 'click', () => switchTab('cleanup'));
    safeAddListener('create-btn', 'click', createShorts);
    safeAddListener('create-btn-file', 'click', createShortsFromFile);
    safeAddListener('download-all-zip-btn', 'click', downloadAllAsZip);
    safeAddListener('save-settings-btn', 'click', saveSettings);
    safeAddListener('start-integration-btn', 'click', startIntegration);
    safeAddListener('upload-credentials-btn', 'click', uploadCredentials);
    safeAddListener('authorize-accounts-btn', 'click', authorizeAccounts);
    safeAddListener('save-preset-btn', 'click', savePreset);
    safeAddListener('logout-btn', 'click', logout);
    safeAddListener('load-preset', 'change', loadPresetFromSelect);
    safeAddListener('refresh-accounts-btn', 'click', loadAccountsList);
    safeAddListener('cleanup-uploads-btn', 'click', cleanupUploads);
    safeAddListener('cleanup-output-btn', 'click', cleanupOutput);
    safeAddListener('cleanup-projects-btn', 'click', cleanupOldProjects);
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
        readFileVideoDuration(first, 'file');
    });
    
    initTabs();
    await loadFonts();
    await loadStats();
    await loadSettings();
    loadApiKeys();
    
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
        if (len) len.disabled = isAuto;
        updateEstimate(tab);
    }

    document.querySelectorAll('.smart-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            const mode = btn.dataset.mode;
            document.querySelectorAll(`.smart-mode-btn[data-tab="${tab}"]`).forEach(b => {
                b.style.background = '#374151';
                b.style.opacity = '0.6';
            });
            btn.style.background = '#1F2937';
            btn.style.opacity = '1';
            const desc = document.getElementById('smart-desc-' + tab);
            if (desc) desc.textContent = smartDescs[mode] || '';
            updateEstimate(tab);
        });
        // init first as active
        if (btn.querySelector(':checked')) {
            btn.style.background = '#1F2937';
            btn.style.opacity = '1';
        }
    });

    ['url', 'file', 'integration'].forEach(tab => {
        const cb = document.getElementById('auto-duration-' + tab);
        if (cb) cb.addEventListener('change', () => applyAutoDurationUI(tab, cb.checked));
        applyAutoDurationUI(tab, cb ? cb.checked : false);
    });

    // ── Оценка времени обработки ──
    const WHISPER_FACTORS = { base: 1, small: 3.5, medium: 7, 'large-v3-turbo': 4, 'large-v3': 14 };
    window._videoDurations = { url: null, file: null, integration: null };

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
        const knownDur = getVideoDurationSec(tab);
        const videoSec = knownDur || 1200;   // запасной вариант — 20 мин
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

        const wf = WHISPER_FACTORS[whisper] || 1;
        const smart = mode !== 'off' || auto;
        const transcribe = smart ? videoSec * 0.1 * wf : count * segLen * 0.1 * wf;  // смарт — транскрипция всего видео
        const render = count * segLen * 0.25;                  // ffmpeg (NVENC + blur + субтитры)
        const selection = mode === 'off' ? 0 : videoSec * 0.25 + 30;  // нейросетевой отбор по всему видео
        const autoTime = auto ? count * 3 : 0;                 // уточнение длительности
        const ai = count * 2;                                  // AI-метаданные

        const perShort = (transcribe + render) / count + ai / count + (auto ? 3 : 0);
        let total = transcribe + render + selection + autoTime + ai;

        // режим папки: несколько видео → умножаем общее время
        let videosCount = 1;
        if (tab === 'file') {
            const folderMode = document.getElementById('folder-mode-file')?.checked;
            const files = document.getElementById('video-file')?.files;
            if (folderMode && files && files.length > 1) videosCount = files.length;
        }
        if (videosCount > 1) total = total * videosCount;
        const countLabel = videosCount > 1 ? `${count} шт × ${videosCount} видео` : `${count} шт`;

        const parts = [];
        if (mode !== 'off') parts.push('отбор моментов ' + fmtTime(selection));
        parts.push('Whisper ' + whisper + ' ' + fmtTime(transcribe));
        parts.push('рендер ' + fmtTime(render));
        if (auto) parts.push('авто-длина ' + fmtTime(autoTime));
        parts.push('AI ' + fmtTime(ai));

        const durText = knownDur
            ? 'Длительность видео: ' + fmtTime(knownDur)
            : (tab === 'file' ? 'Длительность определится после выбора файла' : 'Длительность определится после ввода ссылки');

        box.innerHTML = `
            <div class="text-gray-400 text-xs mb-1">${durText}</div>
            <div class="text-gray-400 text-xs mb-1">Ориентировочно (${whisper}, ${mode === 'off' ? 'просто нарезка' : mode}, ${countLabel}):</div>
            <div class="text-purple-300">1 шортс — ${fmtTime(perShort)}</div>
            <div class="text-gray-300">всего — ${fmtTime(total)}</div>
            <div class="text-gray-500 text-xs mt-1">${parts.join(' • ')}</div>
        `;
    }

    function initEstimates() {
        ['url', 'file', 'integration'].forEach(tab => {
            const ids = [
                tab === 'url' ? 'shorts-count' : tab === 'file' ? 'shorts-count-file' : 'integration-shorts-count',
                tab === 'url' ? 'short-length' : tab === 'file' ? 'short-length-file' : 'integration-short-length',
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
    ['url', 'file', 'integration'].forEach(tab => updateEstimate(tab));

    // ── Авто-определение длительности видео ──
    function readFileVideoDuration(file, tab) {
        window._videoDurations[tab] = null;
        if (!file) { updateEstimate(tab); return; }
        const objUrl = URL.createObjectURL(file);
        const v = document.createElement('video');
        v.preload = 'metadata';
        v.muted = true;
        v.onloadedmetadata = () => {
            if (isFinite(v.duration) && v.duration > 0) window._videoDurations[tab] = v.duration;
            URL.revokeObjectURL(objUrl);
            updateEstimate(tab);
        };
        v.onerror = () => { URL.revokeObjectURL(objUrl); updateEstimate(tab); };
        v.src = objUrl;
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
                } catch (e) {}
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
        readFileVideoDuration(e.target.files[0], 'integration');
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
    
    // Обработчики для сохранения в папку
    ['url', 'file', 'integration'].forEach(tab => {
        const cb = document.getElementById('save-video-' + tab);
        if (cb) {
            cb.addEventListener('change', () => {
                document.getElementById('save-folder-row-' + tab)?.classList.toggle('hidden', !cb.checked);
            });
        }
    });

    // Обработчик для режима папки
    const folderCb = document.getElementById('folder-mode-file');
    const fileInput = document.getElementById('video-file');
    if (folderCb && fileInput) {
        folderCb.addEventListener('change', () => {
            try {
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
            document.getElementById('file-name').classList.add('hidden');
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

    // Показ/скрытие настроек паузы баннера
    const bannerStyleSel = document.getElementById('banner-style-settings');
    const bannerPauseRow = document.getElementById('banner-pause-settings');
    if (bannerStyleSel && bannerPauseRow) {
        const syncBannerStyle = () => {
            bannerPauseRow.classList.toggle('hidden', bannerStyleSel.value !== 'pause');
        };
        bannerStyleSel.addEventListener('change', syncBannerStyle);
        syncBannerStyle();
    }
    
    loadSaveFolders();
    
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
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        if (data.status === 'success' && data.settings) {
            const s = data.settings;
            // Субтитры
            if (document.getElementById('subtitle-font')) {
                document.getElementById('subtitle-font').value = s.font || 'Montserrat';
                document.getElementById('subtitle-style').value = s.style || 'normal';
                document.getElementById('subtitle-fontsize').value = s.fontsize || 100;
                document.getElementById('subtitle-fontsize-val').textContent = s.fontsize || 100;
                document.getElementById('subtitle-color').value = s.fontcolor || 'white';
                document.getElementById('subtitle-position').value = s.position || 1670;
                document.getElementById('subtitle-position-val').textContent = s.position || 1670;
                document.getElementById('subtitle-borderw').value = s.borderw || 3;
                document.getElementById('subtitle-bordercolor').value = s.bordercolor || 'black';
                document.getElementById('subtitle-boxborder').value = s.boxborder ?? 0;
                document.getElementById('subtitle-boxcolor').value = s.boxcolor || 'black@0.8';
                document.getElementById('subtitle-shadowx').value = s.shadowx || 2;
                document.getElementById('subtitle-shadowy').value = s.shadowy || 2;
                document.getElementById('subtitle-shadowcolor').value = s.shadowcolor || 'black';
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

                if (document.getElementById('crop-mode')) {
                    document.getElementById('crop-mode').value = s.crop_mode || '9:16';
                }
                if (document.getElementById('zoom-enabled')) {
                    document.getElementById('zoom-enabled').checked = s.zoom_enabled || false;
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
        formData.append('fontcolor', document.getElementById('subtitle-color')?.value || 'white');
        formData.append('position', document.getElementById('subtitle-position')?.value || '1670');
        formData.append('borderw', document.getElementById('subtitle-borderw')?.value || '3');
        formData.append('bordercolor', document.getElementById('subtitle-bordercolor')?.value || 'black');
        formData.append('boxborder', document.getElementById('subtitle-boxborder')?.value || '0');
        formData.append('boxcolor', document.getElementById('subtitle-boxcolor')?.value || 'black@0.8');
        formData.append('shadowx', document.getElementById('subtitle-shadowx')?.value || '2');
        formData.append('shadowy', document.getElementById('subtitle-shadowy')?.value || '2');
        formData.append('shadowcolor', document.getElementById('subtitle-shadowcolor')?.value || 'black');
        formData.append('capitalize', document.getElementById('subtitle-capitalize')?.checked ?? false);
        formData.append('crop_mode', document.getElementById('crop-mode')?.value || '9:16');
        formData.append('zoom_enabled', document.getElementById('zoom-enabled')?.checked ?? false);

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
    
    const logLine = document.createElement('div');
    logLine.className = `${color} mb-1`;
    logLine.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${icon} ${message}`;
    
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
    last.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> ${icon} ${message}`;
    logsContent.scrollTop = logsContent.scrollHeight;
}

function startLogsPolling(jobId) {
    if (logsPollingInterval) clearInterval(logsPollingInterval);
    currentJobId = jobId;
    let shownLogs = 0;
    
    logsPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/logs/${jobId}`);
            const data = await response.json();
            const logs = data.logs || [];
            const total = logs.length;
            
            if (total > shownLogs) {
                for (let i = shownLogs; i < total; i++) {
                    addLog(logs[i].message, logs[i].type || 'info');
                }
                shownLogs = total;
            }
            
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
        select.innerHTML = '<option value="">-- Выберите схему --</option>';
        
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

// Создание Shorts из URL
async function createShorts() {
    const shortLength = document.getElementById('short-length')?.value || '45';
    const shortsCount = document.getElementById('shorts-count')?.value || '5';
    const btn = document.getElementById('create-btn');
    
    btn.disabled = true;
    btn.textContent = 'Загружаем...';
    
    try {
        const url = document.getElementById('video-url')?.value || '';
        if (!url) {
            btn.disabled = false;
            btn.textContent = 'Создать Shorts';
            return alert('Введите URL');
        }
        
        const formData = new FormData();
        formData.append('url', url);
        formData.append('short_length', shortLength);
        formData.append('shorts_count', shortsCount);
        formData.append('smart_selection', document.querySelector('input[name="smart-mode-url"]:checked')?.value || 'off');
        formData.append('auto_duration', String(document.getElementById('auto-duration-url')?.checked || false));
        formData.append('min_short_length', document.getElementById('auto-min-url')?.value || '30');
        formData.append('max_short_length', document.getElementById('auto-max-url')?.value || '60');
        formData.append('blurred_bg', String(document.getElementById('blurred-bg-url')?.checked || false));
        formData.append('crop_fill', String(document.getElementById('crop-fill-url')?.checked || false));
        formData.append('save_video', String(document.getElementById('save-video-url')?.checked || false));
        formData.append('save_folder', getSelectedSaveFolder('url'));
        formData.append('filename_keywords', document.getElementById('filename-keywords')?.value?.trim() || '');

        // Баннер
        const bUrl = document.getElementById('banner-enabled-url');
        formData.append('banner_enabled', String(bUrl?.checked || false));
        if (bUrl?.checked) {
            formData.append('banner_x', document.getElementById('banner-x-settings')?.value || '0');
            formData.append('banner_y', document.getElementById('banner-y-settings')?.value || '0');
            formData.append('banner_w', document.getElementById('banner-w-settings')?.value || '1080');
            formData.append('banner_h', document.getElementById('banner-h-settings')?.value || '200');
            formData.append('banner_opacity', document.getElementById('banner-opacity-settings')?.value || '100');
            formData.append('banner_style', document.getElementById('banner-style-settings')?.value || 'overlay');
            formData.append('banner_position', document.getElementById('banner-position-settings')?.value || '50');
            formData.append('banner_duration', document.getElementById('banner-duration-settings')?.value || '3');
            const bannerFile = document.getElementById('banner-file-settings')?.files?.[0];
            if (bannerFile) formData.append('banner_file', bannerFile);
        }

        const response = await fetch('/api/upload-url', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Ошибка сервера: ' + response.status);
        }
        
        const data = await response.json();
        currentJobId = data.job_id;
        
        document.getElementById('progress-section')?.classList.remove('hidden');
        document.getElementById('results-section')?.classList.add('hidden');
        document.getElementById('shorts-list').innerHTML = '';
        btn.textContent = 'Обрабатываем...';
        startPolling();
    } catch (e) {
        alert('Ошибка: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Создать Shorts';
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
        formData.append('smart_selection', document.querySelector('input[name="smart-mode-file"]:checked')?.value || 'off');
        formData.append('auto_duration', String(document.getElementById('auto-duration-file')?.checked || false));
        formData.append('min_short_length', document.getElementById('auto-min-file')?.value || '30');
        formData.append('max_short_length', document.getElementById('auto-max-file')?.value || '60');
        formData.append('blurred_bg', String(document.getElementById('blurred-bg-file')?.checked || false));
        formData.append('crop_fill', String(document.getElementById('crop-fill-file')?.checked || false));
        formData.append('save_video', String(document.getElementById('save-video-file')?.checked || false));
        formData.append('save_folder', getSelectedSaveFolder('file'));
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
            const bannerFile = document.getElementById('banner-file-settings')?.files?.[0];
            if (bannerFile) formData.append('banner_file', bannerFile);
        }
        
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
        if (pt) pt.textContent = getStatusText(data.status);
        
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
            const logsRes = await fetch(`/api/logs/${currentJobId}`);
            const logsData = await logsRes.json();
            const logs = logsData.logs || [];
            const total = logs.length;
            
            if (total > shownLogs) {
                for (let i = shownLogs; i < total; i++) {
                    addLog(logs[i].message, logs[i].type || 'info');
                }
                shownLogs = total;
            }
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
        downloadBtn.textContent = '📦 Скачать все (' + shorts.length + ') в ZIP';
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
    if (!currentJobId) return alert('Нет видео для скачивания');
    
    const btn = document.getElementById('download-all-zip-btn');
    btn.textContent = 'Создаём ZIP...';
    btn.disabled = true;
    
    const a = document.createElement('a');
    a.href = `/api/download-zip/${currentJobId}`;
    a.download = `shorts_${currentJobId}.zip`;
    a.click();
    
    btn.textContent = '📦 Скачать все в ZIP';
    btn.disabled = false;
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
        formData.append('save_video', String(document.getElementById('save-video-integration').checked));
        formData.append('save_folder', getSelectedSaveFolder('integration'));
        formData.append('crop_fill', String(document.getElementById('integration-crop-fill')?.checked || false));
        formData.append('smart_selection', document.querySelector('input[name="smart-mode-integration"]:checked')?.value || 'off');
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
                formData.append('replace_audio', document.getElementById('replace-audio')?.checked || false);
            }
        }
        
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
        alert('Введите название схемы');
        return;
    }
    
    const preset = {
        name: name,
        source: document.getElementById('integration-source').value,
        short_length: document.getElementById('integration-short-length').value,
        shorts_count: document.getElementById('integration-shorts-count').value,
        // Субтитры больше не используются
        distribution_mode: document.getElementById('distribution-mode').value,
        custom_distribution: document.getElementById('custom-distribution').value,
        videos_per_day: document.getElementById('videos-per-day').value,
        enable_scheduled: document.getElementById('enable-scheduled').checked,
        schedule_start_date: document.getElementById('schedule-start-date').value,
        schedule_start_time: document.getElementById('schedule-start-time').value,
        schedule_interval: document.getElementById('schedule-interval').value
    };
    
    try {
        const response = await fetch('/api/presets/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(preset)
        });
        
        const data = await response.json();
        if (data.status === 'success') {
            alert('Схема сохранена!');
            document.getElementById('preset-name').value = '';
            loadPresets();
        } else {
            alert('Ошибка: ' + data.message);
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
            document.getElementById('integration-source').value = p.source || 'url';
            document.getElementById('integration-short-length').value = p.short_length || 45;
            document.getElementById('integration-shorts-count').value = p.shorts_count || 5;
            // Субтитры больше не используются
            document.getElementById('distribution-mode').value = p.distribution_mode || 'equal';
            document.getElementById('custom-distribution').value = p.custom_distribution || '';
            document.getElementById('videos-per-day').value = p.videos_per_day || 3;
            document.getElementById('enable-scheduled').checked = p.enable_scheduled || false;
            document.getElementById('schedule-start-date').value = p.schedule_start_date || today;
            document.getElementById('schedule-start-time').value = p.schedule_start_time || '12:00';
            document.getElementById('schedule-interval').value = p.schedule_interval || '60';
            
            // Обновляем зависимые поля
            document.getElementById('integration-source').dispatchEvent(new Event('change'));
            document.getElementById('distribution-mode').dispatchEvent(new Event('change'));
            document.getElementById('enable-scheduled').dispatchEvent(new Event('change'));
            
            alert('Схема загружена!');
        }
    } catch (e) {
        alert('Ошибка загрузки схемы: ' + e.message);
    }
}

// ==================== Предпросмотр субтитров ====================

function updateSubtitlePreview() {
    const text = document.getElementById('preview-text')?.value || 'Текст субтитров';
    const font = document.getElementById('subtitle-font')?.value || 'Montserrat';
    const style = document.getElementById('subtitle-style')?.value || 'normal';
    const fontsize = parseInt(document.getElementById('subtitle-fontsize')?.value || '100');
    const color = document.getElementById('subtitle-color')?.value || 'white';
    const position = parseInt(document.getElementById('subtitle-position')?.value || '1670');
    const borderw = parseInt(document.getElementById('subtitle-borderw')?.value || '3');
    const bordercolor = document.getElementById('subtitle-bordercolor')?.value || 'black';
    const boxborder = parseInt(document.getElementById('subtitle-boxborder')?.value || '0');
    const boxcolor = document.getElementById('subtitle-boxcolor')?.value || 'none';
    const shadowx = parseInt(document.getElementById('subtitle-shadowx')?.value || '2');
    const shadowy = parseInt(document.getElementById('subtitle-shadowy')?.value || '2');
    const shadowcolor = document.getElementById('subtitle-shadowcolor')?.value || 'black';
    const capitalize = document.getElementById('subtitle-capitalize')?.checked || false;
    const previewBg = document.getElementById('preview-bg-color')?.value || 'black';

    const colors = {
        white: '#FFFFFF', yellow: '#FFFF00', red: '#FF0000', green: '#00FF00',
        blue: '#0000FF', cyan: '#00FFFF', magenta: '#FF00FF', orange: '#FFA500',
        black: '#000000', gray: '#808080'
    };

    let finalText = text;
    if (capitalize) finalText = text.toUpperCase();

    const span = document.getElementById('preview-text-span');
    if (!span) return;

    span.textContent = finalText;
    span.style.fontFamily = font + ', sans-serif';
    span.style.fontSize = Math.round(fontsize * 180 / 1080) + 'px';
    span.style.color = colors[color] || color;
    span.style.fontWeight = (style === 'bold' || style === 'bold_italic') ? 'bold' : 'normal';
    span.style.fontStyle = (style === 'italic' || style === 'bold_italic') ? 'italic' : 'normal';

    span.style.textShadow = 'none';
    span.style.webkitTextStroke = 'none';
    span.style.backgroundColor = 'transparent';
    span.style.padding = '0';
    span.style.borderRadius = '0';
    span.style.display = 'inline-block';
    span.style.maxWidth = '90%';

    if (borderw > 0 && bordercolor !== 'none') {
        span.style.webkitTextStroke = Math.round(borderw * 180 / 1080) + 'px ' + (colors[bordercolor] || bordercolor);
    }

    if ((shadowx > 0 || shadowy > 0) && shadowcolor !== 'none') {
        span.style.textShadow = Math.round(shadowx * 180 / 1080) + 'px ' + Math.round(shadowy * 180 / 1080) + 'px 2px ' + (colors[shadowcolor] || shadowcolor);
    }

    if (boxborder > 0 && boxcolor !== 'none') {
        if (boxcolor.includes('@')) {
            const parts = boxcolor.split('@');
            const alpha = parseFloat(parts[1]);
            span.style.backgroundColor = 'rgba(0, 0, 0, ' + alpha + ')';
        } else {
            span.style.backgroundColor = colors[boxcolor] || boxcolor;
        }
        span.style.padding = Math.round(boxborder * 180 / 1080) + 'px';
        span.style.borderRadius = '4px';
    }

    const layer = document.getElementById('preview-subtitle-layer');
    if (layer) {
        const scaledY = Math.round(position * 320 / 1920);
        layer.style.top = scaledY + 'px';
        layer.style.bottom = 'auto';
    }

    const preview = document.getElementById('subtitle-preview');
    if (preview) {
        preview.style.backgroundColor = previewBg;
    }

    // Баннер в предпросмотре
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
        }
    }
}

function applyBannerPreview(bannerImg, bannerVideo, bannerLayer, isVideo) {
    if (!window._bannerPreviewUrl) return;
    const bw = parseInt(document.getElementById('banner-w-settings')?.value || '1080');
    const bh = parseInt(document.getElementById('banner-h-settings')?.value || '200');
    const bx = parseInt(document.getElementById('banner-x-settings')?.value || '0');
    const by = parseInt(document.getElementById('banner-y-settings')?.value || '0');
    const op = parseInt(document.getElementById('banner-opacity-settings')?.value || '100');
    const scaleW = 180 / 1080;
    const scaleH = 320 / 1920;
    const el = isVideo ? bannerVideo : bannerImg;
    const other = isVideo ? bannerImg : bannerVideo;
    el.src = window._bannerPreviewUrl;
    el.style.width = Math.round(bw * scaleW) + 'px';
    el.style.height = Math.round(bh * scaleH) + 'px';
    el.style.position = 'absolute';
    el.style.left = Math.round(bx * scaleW) + 'px';
    el.style.top = Math.round(by * scaleH) + 'px';
    el.style.opacity = op / 100;
    el.style.display = 'block';
    other.style.display = 'none';
    bannerLayer.style.display = 'block';
}

function initTabs() {}

function initSubtitlePreview() {
    const ids = ['subtitle-font', 'subtitle-style', 'subtitle-fontsize', 'subtitle-color',
                 'subtitle-position', 'subtitle-borderw', 'subtitle-bordercolor', 'subtitle-boxborder', 'subtitle-boxcolor',
                 'subtitle-shadowx', 'subtitle-shadowy', 'subtitle-shadowcolor',
                 'preview-text', 'preview-bg-color',
                 'banner-x-settings', 'banner-y-settings', 'banner-w-settings', 'banner-h-settings'];
    
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateSubtitlePreview);
            el.addEventListener('change', updateSubtitlePreview);
        }
    });

    const capEl = document.getElementById('subtitle-capitalize');
    if (capEl) capEl.addEventListener('change', updateSubtitlePreview);

    const bannerEnabled = document.getElementById('banner-enabled-settings');
    if (bannerEnabled) bannerEnabled.addEventListener('change', updateSubtitlePreview);

    updateSubtitlePreview();
}

document.addEventListener('DOMContentLoaded', () => {
    initSubtitlePreview();
    
    const saveVideoUrl = document.getElementById('save-video-url');
    if (saveVideoUrl) {
        saveVideoUrl.addEventListener('change', () => {
            document.getElementById('save-folder-row-url')?.classList.toggle('hidden', !saveVideoUrl.checked);
        });
    }
    
    const saveVideoFile = document.getElementById('save-video-file');
    if (saveVideoFile) {
        saveVideoFile.addEventListener('change', () => {
            document.getElementById('save-folder-row-file')?.classList.toggle('hidden', !saveVideoFile.checked);
        });
    }
    
    const saveVideoInt = document.getElementById('save-video-integration');
    if (saveVideoInt) {
        saveVideoInt.addEventListener('change', () => {
            document.getElementById('save-folder-row-integration')?.classList.toggle('hidden', !saveVideoInt.checked);
        });
    }
    
    loadSaveFolders();
});

async function loadSaveFolders() {
    try {
        const res = await fetch('/api/saved-folders');
        const data = await res.json();
        if (data.status === 'success') {
            ['save-folder-select-url', 'save-folder-select-file', 'save-folder-select-integration'].forEach(id => {
                const sel = document.getElementById(id);
                if (!sel) return;
                const current = sel.value;
                sel.innerHTML = '<option value="">-- Выбрать папку --</option>';
                data.folders.forEach(f => {
                    const opt = document.createElement('option');
                    opt.value = f;
                    opt.textContent = f;
                    if (f === current) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        }
    } catch (e) {
        console.log('Failed to load save folders:', e);
    }
}

async function createSaveFolder(tab) {
    const input = document.getElementById('save-folder-' + tab);
    const name = input?.value?.trim();
    if (!name) return;
    
    try {
        const res = await fetch('/api/saved-folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder: name })
        });
        const data = await res.json();
        if (data.status === 'success') {
            input.value = '';
            await loadSaveFolders();
            const selectId = 'save-folder-select-' + tab;
            const sel = document.getElementById(selectId);
            if (sel) sel.value = name;
        } else {
            alert('Ошибка: ' + data.message);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function getSelectedSaveFolder(tab) {
    const sel = document.getElementById('save-folder-select-' + tab)?.value;
    const input = document.getElementById('save-folder-' + tab)?.value?.trim();
    return sel || input || 'saved';
}

async function deleteSaveFolder(tab) {
    const sel = document.getElementById('save-folder-select-' + tab);
    const name = sel?.value;
    if (!name) return alert('Выберите папку для удаления');
    if (!confirm('Удалить папку "' + name + '" и все файлы в ней?')) return;
    
    try {
        const res = await fetch('/api/saved-folders', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder: name })
        });
        const data = await res.json();
        if (data.status === 'success') {
            await loadSaveFolders();
        } else {
            alert('Ошибка: ' + data.message);
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

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
            const date = new Date(p.created_at * 1000).toLocaleString('ru-RU');
            const statusColors = { 'completed': 'text-green-400', 'failed': 'text-red-400', 'processing': 'text-blue-400', 'downloading': 'text-yellow-400' };
            const statusIcons = { 'completed': '✅', 'failed': '❌', 'processing': '🔄', 'downloading': '⏳' };
            const sc = statusColors[p.status] || 'text-gray-400';
            const si = statusIcons[p.status] || '❓';
            return `
            <div class="p-4 bg-gray-800 rounded-xl border border-gray-700">
                <div class="flex items-center justify-between">
                    <div>
                        <div class="font-medium">${si} ${p.job_id.substring(0, 8)}...</div>
                        <div class="text-sm text-gray-500">${date}</div>
                        <div class="text-sm ${sc}">${p.status} — ${p.shorts_count} шортсов</div>
                        ${p.save_folder ? `<div class="text-xs text-gray-600">Папка: ${p.save_folder}</div>` : ''}
                    </div>
                    <button onclick="deleteProject('${p.job_id}')" class="px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-xs">🗑</button>
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
            loadProjects();
        }
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

function showCleanupResult(message, type = 'success') {
    const el = document.getElementById('cleanup-result');
    if (!el) return;
    el.textContent = message;
    el.className = 'mt-4 p-3 rounded-xl border border-gray-700 text-sm ' + (type === 'success' ? 'text-green-400 bg-gray-800' : 'text-red-400 bg-gray-800');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 5000);
}

async function cleanupOldProjects() {
    if (!confirm('Удалить все завершённые/проваленные проекты старше 7 дней?')) return;
    try {
        const res = await fetch('/api/jobs/old?days_old=7', { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showCleanupResult(`Очищено ${data.deleted} проектов`);
            loadProjects();
        }
    } catch (e) {
        showCleanupResult('Ошибка: ' + e.message, 'error');
    }
}

async function cleanupUploads() {
    if (!confirm('Удалить все входные файлы из uploads? Это большие видео!')) return;
    try {
        const res = await fetch('/api/cleanup/uploads', { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showCleanupResult(`Удалено ${data.deleted} файлов из uploads`);
        }
    } catch (e) {
        showCleanupResult('Ошибка: ' + e.message, 'error');
    }
}

async function cleanupOutput() {
    if (!confirm('Удалить все шортсы из output?')) return;
    try {
        const res = await fetch('/api/cleanup/output', { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            showCleanupResult(`Удалено ${data.deleted} файлов из output`);
        }
    } catch (e) {
        showCleanupResult('Ошибка: ' + e.message, 'error');
    }
}
