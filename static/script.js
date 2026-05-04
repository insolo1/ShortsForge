// Основной скрипт Video Bot

let currentTab = 'url';
let currentJobId = null;
let pollInterval = null;
let logsPollingInterval = null;

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
    
    // Определяем текущий этап по статусу
    let currentStageId = 'init';
    switch(currentStatus) {
        case 'downloading':
            currentStageId = 'download';
            break;
        case 'processing':
            currentStageId = 'split';
            break;
        case 'generating':
            currentStageId = 'content';
            break;
        case 'uploading':
            currentStageId = 'youtube';
            break;
        case 'completed':
            currentStageId = 'done';
            break;
        default:
            currentStageId = 'init';
    }
    
    // Обновляем статус каждого этапа
    stages.forEach(stage => {
        if (stage.id === currentStageId) {
            stage.status = 'in_progress';
        } else if (stages.findIndex(s => s.id === currentStageId) > stages.findIndex(s => s.id === stage.id)) {
            stage.status = 'completed';
        } else {
            stage.status = 'waiting';
        }
    });
    
    // Рендерим список этапов
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
    
    // Выводим в чат
    const stageNames = {
        'init': 'Инициализация',
        'download': 'Скачивание видео',
        'split': 'Нарезка на шортсы',
        'content': 'Генерация контента (названия, теги)',
        'youtube': 'Загрузка на YouTube',
        'done': 'Завершено'
    };
    
    if (currentStatus && currentStatus !== 'unknown') {
        addLog(`Текущий этап: ${stageNames[currentStageId] || currentStageId}`, 'progress');
    }
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
    document.getElementById('section-url').classList.toggle('hidden', tab !== 'url');
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

// Инициализация после загрузки страницы
document.addEventListener('DOMContentLoaded', function() {
    console.log('Страница загружена');
    
    safeAddListener('tab-url', 'click', () => switchTab('url'));
    safeAddListener('tab-file', 'click', () => switchTab('file'));
    safeAddListener('tab-settings', 'click', () => switchTab('settings'));
    safeAddListener('tab-integration', 'click', () => switchTab('integration'));
    safeAddListener('create-btn', 'click', createShorts);
    safeAddListener('create-btn-file', 'click', createShortsFromFile);
    safeAddListener('save-settings-btn', 'click', saveSettings);
    safeAddListener('start-integration-btn', 'click', startIntegration);
    safeAddListener('upload-credentials-btn', 'click', uploadCredentials);
    safeAddListener('authorize-accounts-btn', 'click', authorizeAccounts);
    safeAddListener('save-preset-btn', 'click', savePreset);
    safeAddListener('load-preset', 'change', loadPresetFromSelect);
    safeAddListener('clear-logs-btn', 'click', clearLogs);
    safeAddListener('refresh-accounts-btn', 'click', loadAccountsList);

    safeAddListener('video-file', 'change', (e) => {
        const fileName = document.getElementById('file-name');
        if (e.target.files[0]) {
            fileName.textContent = 'Выбран: ' + e.target.files[0].name;
            fileName.classList.remove('hidden');
        }
    });
    
    // Переключатели
    document.getElementById('integration-source').addEventListener('change', (e) => {
        const isFile = e.target.value === 'file';
        document.getElementById('integration-url-input').classList.toggle('hidden', isFile);
        document.getElementById('integration-file-input').classList.toggle('hidden', !isFile);
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
    
    // Загружаем список аккаунтов и настройки при загрузке
    loadAccountsList();
    loadSettings();
    
    console.log('Инициализация завершена');
});

// Загрузка настроек
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        if (data.status === 'success' && data.settings) {
            const s = data.settings;
            // Субтитры
            if (document.getElementById('subtitle-font')) {
                document.getElementById('subtitle-font').value = s.font || 'Verdana';
                document.getElementById('subtitle-style').value = s.style || 'normal';
                document.getElementById('subtitle-fontsize').value = s.fontsize || 75;
                document.getElementById('subtitle-color').value = s.fontcolor || 'white';
                document.getElementById('subtitle-position').value = s.position || 600;
                document.getElementById('subtitle-borderw').value = s.borderw || 6;
                document.getElementById('subtitle-bordercolor').value = s.bordercolor || 'black';
                document.getElementById('subtitle-boxborder').value = s.boxborder || 20;
                document.getElementById('subtitle-boxcolor').value = s.boxcolor || 'black@0.8';
                document.getElementById('subtitle-shadowx').value = s.shadowx || 3;
                document.getElementById('subtitle-shadowy').value = s.shadowy || 3;
                document.getElementById('subtitle-shadowcolor').value = s.shadowcolor || 'black';
                document.getElementById('subtitle-capitalize').checked = s.capitalize !== false;
            }
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
        formData.append('font', document.getElementById('subtitle-font').value);
        formData.append('style', document.getElementById('subtitle-style').value);
        formData.append('fontsize', document.getElementById('subtitle-fontsize').value);
        formData.append('fontcolor', document.getElementById('subtitle-color').value);
        formData.append('position', document.getElementById('subtitle-position').value);
        formData.append('borderw', document.getElementById('subtitle-borderw').value);
        formData.append('bordercolor', document.getElementById('subtitle-bordercolor').value);
        formData.append('boxborder', document.getElementById('subtitle-boxborder').value);
        formData.append('boxcolor', document.getElementById('subtitle-boxcolor').value);
        formData.append('shadowx', document.getElementById('subtitle-shadowx').value);
        formData.append('shadowy', document.getElementById('subtitle-shadowy').value);
        formData.append('shadowcolor', document.getElementById('subtitle-shadowcolor').value);
        formData.append('capitalize', document.getElementById('subtitle-capitalize').checked);
        formData.append('crop_mode', '9:16');
        formData.append('zoom_enabled', false);
        
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });
        
        const data = await response.json();
        if (data.status === 'success') {
            showNotification('Настройки сохранены', 'success');
        }
    } catch (e) {
        showNotification('Ошибка сохранения', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Сохранить настройки';
    }
}

// Логи
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
    logsContent.scrollTop = logsContent.scrollHeight;
}

function clearLogs() {
    document.getElementById('logs-content').innerHTML = '<div class="text-gray-500">Логи очищены</div>';
}

function startLogsPolling(jobId) {
    currentJobId = jobId;
    
    logsPollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/logs/${jobId}`);
            const data = await response.json();
            
            if (data.logs && data.logs.length > 0) {
                data.logs.forEach(log => {
                    addLog(log.message, log.type);
                });
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
    const shortLength = document.getElementById('short-length').value;
    const shortsCount = document.getElementById('shorts-count').value;
    const btn = document.getElementById('create-btn');
    
    btn.disabled = true;
    btn.textContent = 'Загружаем...';
    
    try {
        const url = document.getElementById('video-url').value;
        if (!url) {
            btn.disabled = false;
            btn.textContent = 'Создать Shorts';
            return alert('Введите URL');
        }
        
        const smartSelection = String(document.getElementById('smart-selection-url').checked);
        const blurredBg = String(document.getElementById('blurred-bg-url').checked);
        const response = await fetch('/api/upload-url', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `url=${encodeURIComponent(url)}&short_length=${shortLength}&shorts_count=${shortsCount}&smart_selection=${smartSelection}&blurred_bg=${blurredBg}`
        });
        
        if (!response.ok) {
            throw new Error('Ошибка сервера: ' + response.status);
        }
        
        const data = await response.json();
        currentJobId = data.job_id;
        
        document.getElementById('progress-section').classList.remove('hidden');
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
    const shortLength = document.getElementById('short-length-file').value;
    const shortsCount = document.getElementById('shorts-count-file').value;
    const btn = document.getElementById('create-btn-file');
    
    btn.disabled = true;
    btn.textContent = 'Загружаем...';
    
    try {
        const fileInput = document.getElementById('video-file');
        if (!fileInput.files[0]) {
            btn.disabled = false;
            btn.textContent = 'Создать Shorts';
            return alert('Выберите файл');
        }
        
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('short_length', shortLength);
        formData.append('shorts_count', shortsCount);
        formData.append('smart_selection', String(document.getElementById('smart-selection-file').checked));
        formData.append('blurred_bg', String(document.getElementById('blurred-bg-file').checked));
        
        btn.textContent = 'Загружаем файл...';
        const response = await fetch('/api/upload-file', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Ошибка сервера: ' + response.status);
        }
        
        const data = await response.json();
        currentJobId = data.job_id;
        
        document.getElementById('progress-section').classList.remove('hidden');
        btn.textContent = 'Обрабатываем...';
        startPolling();
    } catch (e) {
        alert('Ошибка: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Создать Shorts';
    }
}

function startPolling() {
    pollInterval = setInterval(async () => {
        const res = await fetch(`/api/status/${currentJobId}`);
        const data = await res.json();
        
        document.getElementById('progress-bar').style.width = data.progress + '%';
        document.getElementById('progress-text').textContent = getStatusText(data.status);
        
        // Обновляем интерактивное окно этапов
        updateStages(data.status);
        
        if (data.status === 'completed') {
            clearInterval(pollInterval);
            document.getElementById('create-btn').disabled = false;
            document.getElementById('create-btn').textContent = 'Sozdat Shorts';
            showResults(data.shorts);
        } else if (data.status === 'failed') {
            clearInterval(pollInterval);
            document.getElementById('create-btn').disabled = false;
            document.getElementById('create-btn').textContent = 'Sozdat Shorts';
            alert('Oshibka: ' + data.error);
        }
    }, 2000);
}

function getStatusText(status) {
    const texts = {
        'downloading': 'Скачивание видео...',
        'processing': 'Нарезаем на шорты...',
        'generating': 'Генерируем названия...',
        'completed': 'Готово!'
    };
    return texts[status] || 'Обработка...';
}

function showResults(shorts) {
    document.getElementById('progress-section').classList.add('hidden');
    document.getElementById('results-section').classList.remove('hidden');
    
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
    const card = document.querySelector(`[data-id="${shortId}"]`).closest('.card');
    const title = card.querySelector('[data-field="title"]').value;
    const description = card.querySelector('[data-field="description"]').value;
    const tags = card.querySelector('[data-field="tags"]').value;
    
    await fetch(`/api/update-short/${shortId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `title=${encodeURIComponent(title)}&description=${encodeURIComponent(description)}&tags=${encodeURIComponent(tags)}`
    });
    
    alert('Сохранено!');
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
        
        const source = document.getElementById('integration-source').value;
        formData.append('source', source);
        
        if (source === 'url') {
            const url = document.getElementById('integration-video-url').value;
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
        document.getElementById('integration-stages-window').classList.remove('hidden');
        
        const accounts = document.getElementById('youtube-accounts').value;
        if (!accounts.trim()) {
            alert('Добавьте хотя бы один YouTube аккаунт');
            btn.disabled = false;
            btn.textContent = 'Запустить автопубликацию';
            return;
        }
        formData.append('accounts', accounts);
        formData.append('distribution_mode', document.getElementById('distribution-mode').value);
        formData.append('custom_distribution', document.getElementById('custom-distribution').value);
        formData.append('videos_per_day', document.getElementById('videos-per-day').value);
        formData.append('short_length', document.getElementById('integration-short-length').value);
        formData.append('shorts_count', document.getElementById('integration-shorts-count').value);
        
        // Музыка
        formData.append('enable_audio', document.getElementById('enable-audio').checked);
        if (document.getElementById('enable-audio').checked) {
            const audioFile = document.getElementById('integration-audio-file').files[0];
            if (audioFile) {
                formData.append('audio_file', audioFile);
                formData.append('audio_start', document.getElementById('audio-start').value);
                formData.append('audio_end', document.getElementById('audio-end').value);
                formData.append('replace_audio', document.getElementById('replace-audio').checked);
            }
        }
        
        // Теги
        formData.append('enable_required_tags', document.getElementById('enable-required-tags').checked);
        formData.append('required_tags', document.getElementById('required-tags').value);
        formData.append('enable_optional_tags', document.getElementById('enable-optional-tags').checked);
        
        // Отложенная публикация
        formData.append('enable_scheduled', document.getElementById('enable-scheduled').checked);
        if (document.getElementById('enable-scheduled').checked) {
            formData.append('schedule_start_date', document.getElementById('schedule-start-date').value);
            formData.append('schedule_start_time', document.getElementById('schedule-start-time').value);
            formData.append('schedule_interval', document.getElementById('schedule-interval').value);
        }
        
        const response = await fetch('/api/integration/start', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error('Ошибка запуска');
        
        const data = await response.json();
        
        // Показываем окно логов
        document.getElementById('logs-window').classList.remove('hidden');
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
