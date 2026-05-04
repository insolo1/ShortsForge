// Video Bot Main Script

let currentTab = 'url';
let currentJobId = null;
let pollInterval = null;
let logsPollingInterval = null;

// Switch tabs
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

// Safe add event listener
function safeAddListener(id, event, handler) {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener(event, handler);
        console.log('Added listener:', id);
    } else {
        console.error('Element not found:', id);
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Page loaded');
    
    safeAddListener('tab-url', 'click', () => switchTab('url'));
    safeAddListener('tab-file', 'click', () => switchTab('file'));
    safeAddListener('tab-settings', 'click', () => switchTab('settings'));
    safeAddListener('tab-integration', 'click', () => switchTab('integration'));
    safeAddListener('create-btn', 'click', createShorts);
    safeAddListener('save-settings-btn', 'click', saveSettings);
    safeAddListener('start-integration-btn', 'click', startIntegration);
    safeAddListener('upload-credentials-btn', 'click', uploadCredentials);
    safeAddListener('authorize-accounts-btn', 'click', authorizeAccounts);
    safeAddListener('save-preset-btn', 'click', savePreset);
    safeAddListener('load-preset', 'change', loadPresetFromSelect);
    safeAddListener('clear-logs-btn', 'click', clearLogs);
    
    // Toggle handlers
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
    
    // Set min date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('schedule-start-date').setAttribute('min', today);
    document.getElementById('schedule-start-date').value = today;
    
    console.log('Initialization complete');
});

// Settings functions
async function saveSettings() {
    const btn = document.getElementById('save-settings-btn');
    btn.disabled = true;
    btn.textContent = 'Сохраняем...';
    
    try {
        const formData = new URLSearchParams();
        formData.append('font', document.getElementById('subtitle-font').value);
        formData.append('fontsize', document.getElementById('subtitle-fontsize').value);
        formData.append('fontcolor', document.getElementById('subtitle-color').value);
        formData.append('position', document.getElementById('subtitle-position').value);
        formData.append('borderw', document.getElementById('subtitle-borderw').value);
        formData.append('boxborder', document.getElementById('subtitle-boxborder').value);
        formData.append('capitalize', document.getElementById('subtitle-capitalize').checked);
        
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: formData
        });
        
        if (!response.ok) throw new Error('Ошибка сохранения');
        
        btn.textContent = 'Сохранено ✓';
        setTimeout(() => {
            btn.textContent = 'Сохранить настройки ✓';
            btn.disabled = false;
        }, 2000);
    } catch (error) {
        alert('Ошибка: ' + error.message);
        btn.textContent = 'Сохранить настройки ✓';
        btn.disabled = false;
    }
}

// Logs functions
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
            
            if (data.status === 'completed') {
                addLog('Задача завершена!', 'success');
                stopLogsPolling();
            } else if (data.status === 'failed') {
                addLog('Задача завершена с ошибками', 'error');
                stopLogsPolling();
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 2000);
}

function stopLogsPolling() {
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }
}

// Load accounts list
async function loadAccountsList() {
    try {
        const response = await fetch('/api/youtube/accounts');
        const data = await response.json();
        
        const container = document.getElementById('accounts-list');
        
        if (data.status === 'success' && data.accounts.length > 0) {
            container.innerHTML = data.accounts.map(acc => `
                <div class="flex justify-between items-center py-2 border-b border-gray-700">
                    <span>${acc.email}</span>
                    <span class="${acc.has_token ? 'text-green-400' : 'text-yellow-400'}">
                        ${acc.has_token ? '✓ Авторизован' : '⚠ Нужен токен'}
                    </span>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p class="text-gray-500">Нет сохранённых аккаунтов</p>';
        }
    } catch (e) {
        console.error('Load accounts error:', e);
    }
}

// Load presets list
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
        console.error('Load presets error:', e);
    }
}

// Create Shorts
async function createShorts() {
    const shortLength = document.getElementById('short-length').value;
    const shortsCount = document.getElementById('shorts-count').value;
    const btn = document.getElementById('create-btn');
    
    btn.disabled = true;
    btn.textContent = 'Загружаем...';
    
    try {
        let response;
        if (currentTab === 'url') {
            const url = document.getElementById('video-url').value;
            if (!url) {
                btn.disabled = false;
                btn.textContent = 'Создать шорты 🚀';
                return alert('Введите URL');
            }
            response = await fetch('/api/upload-url', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `url=${encodeURIComponent(url)}&short_length=${shortLength}&shorts_count=${shortsCount}`
            });
        } else {
            const fileInput = document.getElementById('video-file');
            if (!fileInput.files[0]) {
                btn.disabled = false;
                btn.textContent = 'Создать шорты 🚀';
                return alert('Выберите файл');
            }
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('short_length', shortLength);
            formData.append('shorts_count', shortsCount);
            
            btn.textContent = 'Загружаем файл...';
            response = await fetch('/api/upload-file', {
                method: 'POST',
                body: formData
            });
        }
        
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
        btn.textContent = 'Создать шорты 🚀';
    }
}

function startPolling() {
    pollInterval = setInterval(async () => {
        const res = await fetch(`/api/status/${currentJobId}`);
        const data = await res.json();
        
        document.getElementById('progress-bar').style.width = data.progress + '%';
        document.getElementById('progress-text').textContent = getStatusText(data.status);
        
        if (data.status === 'completed') {
            clearInterval(pollInterval);
            document.getElementById('create-btn').disabled = false;
            document.getElementById('create-btn').textContent = 'Создать шорты 🚀';
            showResults(data.shorts);
        } else if (data.status === 'failed') {
            clearInterval(pollInterval);
            document.getElementById('create-btn').disabled = false;
            document.getElementById('create-btn').textContent = 'Создать шорты 🚀';
            alert('Ошибка: ' + data.error);
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
                    Play
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
                    Download
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

// Start Integration
async function startIntegration() {
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
                btn.textContent = 'Запустить автопубликацию 🚀';
                return;
            }
            formData.append('video_url', url);
        } else {
            const file = document.getElementById('integration-video-file').files[0];
            if (!file) {
                alert('Выберите файл');
                btn.disabled = false;
                btn.textContent = 'Запустить автопубликацию 🚀';
                return;
            }
            formData.append('video_file', file);
        }
        
        const accounts = document.getElementById('youtube-accounts').value;
        if (!accounts.trim()) {
            alert('Добавьте хотя бы один YouTube аккаунт');
            btn.disabled = false;
            btn.textContent = 'Запустить автопубликацию 🚀';
            return;
        }
        formData.append('accounts', accounts);
        formData.append('distribution_mode', document.getElementById('distribution-mode').value);
        formData.append('custom_distribution', document.getElementById('custom-distribution').value);
        formData.append('videos_per_day', document.getElementById('videos-per-day').value);
        formData.append('short_length', document.getElementById('integration-short-length').value);
        formData.append('shorts_count', document.getElementById('integration-shorts-count').value);
        
        // Scheduled publishing
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
        
        // Show logs window
        document.getElementById('logs-window').classList.remove('hidden');
        clearLogs();
        addLog(`Интеграция запущена! Job ID: ${data.job_id}`, 'success');
        
        // Start polling logs
        startLogsPolling(data.job_id);
        
        btn.textContent = 'Запущено ✓';
        setTimeout(() => {
            btn.textContent = 'Запустить автопубликацию 🚀';
            btn.disabled = false;
        }, 3000);
    } catch (error) {
        alert('Ошибка: ' + error.message);
        btn.textContent = 'Запустить автопубликацию 🚀';
        btn.disabled = false;
    }
}

// Upload credentials
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
            alert('Account ' + email + ' added!');
            document.getElementById('manual-account-email').value = '';
            document.getElementById('manual-credentials-file').value = '';
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

// Authorize accounts
async function authorizeAccounts() {
    const btn = document.getElementById('authorize-accounts-btn');
    const accounts = document.getElementById('youtube-accounts').value.trim();
    
    if (!accounts) {
        alert('Введите email аккаунтов');
        return;
    }
    
    const emails = accounts.split('\n').map(e => e.trim()).filter(e => e);
    
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
                console.log('Checkmark ' + email + ' authorized');
            } else if (data.status === 'needs_auth') {
                alert(`Откроется браузер для авторизации: ${email}\n\nВойдите в аккаунт и разрешите доступ.`);
                await new Promise(resolve => setTimeout(resolve, 2000));
            } else {
                alert(`Ошибка авторизации ${email}: ${data.message}`);
            }
        }
        
        alert(`Авторизация завершена! Авторизовано ${emails.length} аккаунтов.`);
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

// Save preset
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
        subtitle_font: document.getElementById('integration-subtitle-font').value,
        subtitle_fontsize: document.getElementById('integration-subtitle-fontsize').value,
        subtitle_color: document.getElementById('integration-subtitle-color').value,
        subtitle_position: document.getElementById('integration-subtitle-position').value,
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

// Load preset from select
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
            document.getElementById('integration-subtitle-font').value = p.subtitle_font || 'Verdana';
            document.getElementById('integration-subtitle-fontsize').value = p.subtitle_fontsize || 65;
            document.getElementById('integration-subtitle-color').value = p.subtitle_color || 'white';
            document.getElementById('integration-subtitle-position').value = p.subtitle_position || 450;
            document.getElementById('distribution-mode').value = p.distribution_mode || 'equal';
            document.getElementById('custom-distribution').value = p.custom_distribution || '';
            document.getElementById('videos-per-day').value = p.videos_per_day || 3;
            document.getElementById('enable-scheduled').checked = p.enable_scheduled || false;
            document.getElementById('schedule-start-date').value = p.schedule_start_date || today;
            document.getElementById('schedule-start-time').value = p.schedule_start_time || '12:00';
            document.getElementById('schedule-interval').value = p.schedule_interval || '60';
            
            // Trigger events
            document.getElementById('integration-source').dispatchEvent(new Event('change'));
            document.getElementById('distribution-mode').dispatchEvent(new Event('change'));
            document.getElementById('enable-scheduled').dispatchEvent(new Event('change'));
            
            alert('Схема загружена!');
        }
    } catch (e) {
        alert('Ошибка загрузки схемы: ' + e.message);
    }
}
