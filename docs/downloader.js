const tg = window.Telegram?.WebApp;
const configuredApi = new URLSearchParams(window.location.search).get('api') || window.CLIPDROP_API_BASE;
const API_BASE = (configuredApi || 'https://debian-2.tail4f778c.ts.net').replace(/\/$/, '');
const $ = (id) => document.getElementById(id);
const urlInput = $('urlInput');
const formHint = $('formHint');
const statusPanel = $('statusPanel');
const statusLabel = $('statusLabel');
const statusDetail = $('statusDetail');
const progressBar = $('progressBar');
const resultButton = $('resultButton');
const cancelButton = $('cancelButton');
let currentJob = null;
let pollTimer = null;

if (tg) { tg.ready(); tg.expand(); }

const openedInsideTelegram = Boolean(tg?.initData);
if (!openedInsideTelegram) {
  $('downloadButton').disabled = true;
  showError('Открой эту страницу через кнопку Mini App в Telegram.');
}

function authHeaders() {
  return { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg?.initData || '' };
}
function setStatus(label, detail, progress = 30) {
  statusPanel.classList.remove('hidden'); statusLabel.textContent = label; statusDetail.textContent = detail; progressBar.style.width = `${progress}%`;
}
function showError(message) { formHint.textContent = message; formHint.style.color = '#c45e51'; }
async function createJob() {
  if (!openedInsideTelegram) return showError('Открой эту страницу через кнопку Mini App в Telegram.');
  const url = urlInput.value.trim();
  if (!/^https?:\/\//i.test(url)) return showError('Вставь корректную ссылку на видео.');
  $('downloadButton').disabled = true; showError(''); setStatus('Добавляем в очередь', 'Это займёт несколько секунд...', 12);
  try {
    const response = await fetch(`${API_BASE}/api/jobs`, { method: 'POST', headers: authHeaders(), body: JSON.stringify({ url }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось создать загрузку');
    currentJob = data; pollJob();
  } catch (error) { setStatus('Не получилось', error.message, 100); progressBar.style.background = '#c45e51'; }
  finally { $('downloadButton').disabled = false; }
}
async function pollJob() {
  if (!currentJob) return;
  clearTimeout(pollTimer);
  try {
    const response = await fetch(`${API_BASE}/api/jobs/${currentJob.id}`, { headers: authHeaders() });
    const data = await response.json(); currentJob = data;
    if (!response.ok) throw new Error(data.error || 'Задача недоступна');
    if (data.status === 'queued') { setStatus('В очереди', 'Ждём свободный слот...', 18); }
    else if (data.status === 'running') { setStatus('Скачиваем', 'Подготавливаем видео для Telegram...', 62); }
    else if (data.status === 'completed') { setStatus('Готово', 'Файл можно скачать или отправить в чат.', 100); resultButton.dataset.downloadUrl = `${API_BASE}${data.download_url}`; resultButton.classList.remove('hidden'); cancelButton.classList.add('hidden'); return; }
    else { setStatus('Загрузка не удалась', data.error || 'Попробуй другую ссылку.', 100); return; }
    pollTimer = setTimeout(pollJob, 1500);
  } catch (error) { setStatus('Ошибка соединения', error.message, 100); }
}
async function cancelJob() {
  if (!currentJob) return;
  await fetch(`${API_BASE}/api/jobs/${currentJob.id}/cancel`, { method: 'POST', headers: authHeaders() });
  setStatus('Отменено', 'Можно вставить другую ссылку.', 100); cancelButton.classList.add('hidden'); clearTimeout(pollTimer);
}
$('downloadButton').addEventListener('click', createJob);
urlInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') createJob(); });
cancelButton.addEventListener('click', cancelJob);
$('resultButton').addEventListener('click', async (event) => {
  event.preventDefault();
  const downloadUrl = resultButton.dataset.downloadUrl;
  if (!downloadUrl) return;
  resultButton.textContent = 'Готовим файл…';
  resultButton.setAttribute('aria-disabled', 'true');
  try {
    const response = await fetch(downloadUrl, { headers: authHeaders() });
    if (!response.ok) throw new Error('Не удалось получить файл');
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = 'clipdrop-video.mp4';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
  } catch (error) {
    setStatus('Ошибка скачивания', error.message, 100);
  } finally {
    resultButton.textContent = 'Скачать файл';
    resultButton.removeAttribute('aria-disabled');
  }
});
$('pasteButton').addEventListener('click', async () => { try { urlInput.value = await navigator.clipboard.readText(); urlInput.focus(); } catch { showError('Вставь ссылку через меню устройства.'); } });
$('themeButton').addEventListener('click', () => document.body.classList.toggle('dark'));

async function loadAdmin() {
  if (!openedInsideTelegram) return;
  try { const response = await fetch(`${API_BASE}/api/admin/summary`, { headers: authHeaders() }); if (!response.ok) return; const data = await response.json(); $('adminPanel').classList.remove('hidden'); $('metricJobs').textContent = data.jobs; $('metricActive').textContent = data.active; $('metricFailed').textContent = data.failed; } catch { /* user is not an admin or API is offline */ }
}
$('refreshAdmin').addEventListener('click', loadAdmin);
loadAdmin();
