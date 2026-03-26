// ── Navigation ──
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const screen = link.dataset.screen;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    link.classList.add('active');
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(screen).classList.add('active');
    if (screen === 'resume-manager') loadResumes();
    if (screen === 'settings') loadKeyStatus();
  });
});

// ── Filters ──
const filterToggle = document.getElementById('filter-toggle');
const filtersPanel = document.getElementById('filters-panel');
const filterCount = document.getElementById('filter-count');
const filterMinPay = document.getElementById('filter-min-pay');
const filterMaxPay = document.getElementById('filter-max-pay');
const filterFormat = document.getElementById('filter-format');

filterToggle.addEventListener('click', () => {
  const open = filtersPanel.hidden;
  filtersPanel.hidden = !open;
  filterToggle.classList.toggle('active', open);
  filterToggle.textContent = open ? 'Hide Filters' : 'Filters';
});

function getFilters() {
  return {
    maxResults: parseInt(filterCount.value) || 10,
    minPay: filterMinPay.value ? parseFloat(filterMinPay.value) : null,
    maxPay: filterMaxPay.value ? parseFloat(filterMaxPay.value) : null,
    format: filterFormat.value,
  };
}

function parseLowPay(payRange) {
  if (!payRange) return null;
  const match = payRange.match(/\$(\d+)/);
  return match ? parseFloat(match[1]) : null;
}

function parseHighPay(payRange) {
  if (!payRange) return null;
  const match = payRange.match(/\$\d+[^$]*\$?(\d+)/);
  if (match) return parseFloat(match[1]);
  // Single value like "$45/hr"
  const single = payRange.match(/\$(\d+)/);
  return single ? parseFloat(single[1]) : null;
}

function applyFilters(jobs) {
  const f = getFilters();
  let filtered = jobs.filter((job, idx) => {
    // Exclude dismissed
    if (dismissedJobs.has(idx)) return false;
    // Format filter
    if (f.format !== 'all' && job.format !== f.format) return false;
    // Min pay filter
    if (f.minPay !== null) {
      const high = parseHighPay(job.pay_range);
      if (high !== null && high < f.minPay) return false;
    }
    // Max pay filter
    if (f.maxPay !== null) {
      const low = parseLowPay(job.pay_range);
      if (low !== null && low > f.maxPay) return false;
    }
    return true;
  });
  return filtered.slice(0, f.maxResults);
}

// ── Job Search ──
const searchBtn = document.getElementById('search-btn');
const searchLoading = document.getElementById('search-loading');
const resultsContainer = document.getElementById('results-container');
const resultsBody = document.getElementById('results-body');
const resultsCount = document.getElementById('results-count');

let allJobs = [];
let currentJobs = [];
let dismissedJobs = new Set(); // Track not-interested jobs by index in allJobs
let lastSource = null;

searchBtn.addEventListener('click', async () => {
  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching...';
  searchLoading.hidden = false;
  resultsContainer.hidden = true;

  try {
    const res = await fetch('/api/jobs/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    allJobs = (data.jobs || []).map((j, i) => ({ ...j, _origIdx: i }));
    dismissedJobs.clear();
    lastSource = data.source;
    currentJobs = applyFilters(allJobs);
    renderJobTable(currentJobs, data.source);
  } catch (err) {
    console.error(err);
    resultsContainer.hidden = false;
    resultsBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--danger)">Search failed. Make sure the server is running.</td></tr>';
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search Jobs';
    searchLoading.hidden = true;
  }
});

// Re-apply filters live when changed (if results already loaded)
[filterCount, filterMinPay, filterMaxPay, filterFormat].forEach(el => {
  el.addEventListener('change', () => {
    if (allJobs.length > 0) {
      currentJobs = applyFilters(allJobs);
      renderJobTable(currentJobs);
    }
  });
});

function renderJobTable(jobs, source) {
  resultsContainer.hidden = false;
  const srcLabel = source === 'live'
    ? ' <span style="font-size:0.75rem;color:var(--success);font-weight:600">LIVE</span>'
    : ' <span style="font-size:0.75rem;color:var(--gray-400);font-weight:600">SAMPLE DATA</span>';
  resultsCount.innerHTML = `${jobs.length} opportunities found ${srcLabel}`;
  resultsBody.innerHTML = '';

  jobs.forEach((job, idx) => {
    const tr = document.createElement('tr');

    const formatClass = job.format === 'Hybrid' ? 'format-hybrid' : 'format-onsite';
    const reachBadge = job.is_reach ? '<span class="badge-reach">Reach</span>' : '';
    const payCell = job.pay_range
      ? job.pay_range
      : '<span class="pay-undisclosed">Not disclosed &#9888;</span>';

    tr.innerHTML = `
      <td class="company-name">${esc(job.company)}</td>
      <td>${esc(job.position)}${reachBadge}</td>
      <td>${esc(job.location)}</td>
      <td><span class="format-badge ${formatClass}">${esc(job.format)}</span></td>
      <td>${payCell}</td>
      <td class="actions-cell">
        <button class="btn btn-interested" data-idx="${idx}">Interested</button>
        <button class="btn btn-not-interested btn-small" data-orig-idx="${job._origIdx}">Not Interested</button>
        ${job.apply_link ? `<a href="${esc(job.apply_link)}" target="_blank" class="btn btn-secondary btn-small">Apply</a>` : ''}
      </td>
    `;
    resultsBody.appendChild(tr);
  });

  document.querySelectorAll('.btn-interested').forEach(btn => {
    btn.addEventListener('click', () => {
      const job = currentJobs[parseInt(btn.dataset.idx)];
      openModal(job);
    });
  });

  document.querySelectorAll('.btn-not-interested').forEach(btn => {
    btn.addEventListener('click', () => {
      const origIdx = parseInt(btn.dataset.origIdx);
      dismissedJobs.add(origIdx);
      // Animate row out
      const row = btn.closest('tr');
      row.style.transition = 'opacity 0.3s, transform 0.3s';
      row.style.opacity = '0';
      row.style.transform = 'translateX(20px)';
      setTimeout(() => {
        currentJobs = applyFilters(allJobs);
        renderJobTable(currentJobs, lastSource);
      }, 300);
    });
  });
}

// ── Modal ──
const modalOverlay = document.getElementById('modal-overlay');
const modalTitle = document.getElementById('modal-title');
const modalSubtitle = document.getElementById('modal-subtitle');
const modalClose = document.getElementById('modal-close');
const tabBtns = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

let currentModalJob = null;
let coverLetterLoaded = false;
let resumeTipsLoaded = false;

function openModal(job) {
  currentModalJob = job;
  coverLetterLoaded = false;
  resumeTipsLoaded = false;
  modalTitle.textContent = `${job.position} at ${job.company}`;
  modalSubtitle.textContent = `${job.location} \u00B7 ${job.format}`;

  // Reset tabs
  tabBtns.forEach(b => b.classList.remove('active'));
  tabBtns[0].classList.add('active');
  tabContents.forEach(c => {
    c.classList.remove('active');
    c.querySelector('.tab-result').innerHTML = '';
    c.querySelector('.tab-loading').hidden = true;
  });
  document.getElementById('tab-cover-letter').classList.add('active');

  modalOverlay.classList.add('visible');
  document.body.style.overflow = 'hidden';
  loadCoverLetter(job);
}

function closeModal() {
  modalOverlay.classList.remove('visible');
  document.body.style.overflow = '';
  currentModalJob = null;
}

modalClose.addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e => {
  if (e.target === modalOverlay) closeModal();
});

tabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    tabBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    tabContents.forEach(c => c.classList.remove('active'));
    const tab = document.getElementById('tab-' + btn.dataset.tab);
    tab.classList.add('active');
    if (btn.dataset.tab === 'resume-tips' && !resumeTipsLoaded && currentModalJob) {
      loadResumeTips(currentModalJob);
    }
    if (btn.dataset.tab === 'cover-letter' && !coverLetterLoaded && currentModalJob) {
      loadCoverLetter(currentModalJob);
    }
  });
});

async function loadCoverLetter(job) {
  const tab = document.getElementById('tab-cover-letter');
  const loading = tab.querySelector('.tab-loading');
  const result = tab.querySelector('.tab-result');
  loading.hidden = false;
  result.innerHTML = '';

  try {
    const res = await fetch('/api/generate/cover-letter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job })
    });
    const data = await res.json();
    result.innerHTML = data.content;
    coverLetterLoaded = true;
  } catch (err) {
    result.innerHTML = '<p style="color:var(--danger)">Failed to generate cover letter.</p>';
  } finally {
    loading.hidden = true;
  }
}

async function loadResumeTips(job) {
  const tab = document.getElementById('tab-resume-tips');
  const loading = tab.querySelector('.tab-loading');
  const result = tab.querySelector('.tab-result');
  loading.hidden = false;
  result.innerHTML = '';

  try {
    const res = await fetch('/api/generate/resume-tips', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job })
    });
    const data = await res.json();
    result.innerHTML = data.content;
    resumeTipsLoaded = true;
  } catch (err) {
    result.innerHTML = '<p style="color:var(--danger)">Failed to generate resume tips.</p>';
  } finally {
    loading.hidden = true;
  }
}

// ── Resume Manager ──
const uploadBtn = document.getElementById('upload-btn');
const fileInput = document.getElementById('file-input');
const resumeTable = document.getElementById('resume-table');
const resumeBody = document.getElementById('resume-body');
const noResumes = document.getElementById('no-resumes');
const pdfWarning = document.getElementById('pdf-extraction-warning');

uploadBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  uploadBtn.disabled = true;
  uploadBtn.textContent = 'Uploading...';

  try {
    const res = await fetch('/api/resumes/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.warning) pdfWarning.hidden = false;
    loadResumes();
  } catch (err) {
    console.error('Upload failed:', err);
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = 'Upload New Resume';
    fileInput.value = '';
  }
});

async function loadResumes() {
  try {
    const res = await fetch('/api/resumes');
    const data = await res.json();
    const resumes = data.resumes || [];

    if (resumes.length === 0) {
      noResumes.hidden = false;
      resumeTable.hidden = true;
      return;
    }

    noResumes.hidden = true;
    resumeTable.hidden = false;
    resumeBody.innerHTML = '';

    resumes.forEach(r => {
      const tr = document.createElement('tr');
      if (r.is_default) tr.classList.add('row-default');

      const statusHtml = r.is_default
        ? '<span class="badge-default">Default &#10003;</span>'
        : `<button class="btn btn-secondary btn-small set-default-btn" data-id="${r.id}">Set as Default</button>`;

      const date = new Date(r.upload_date).toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      });

      tr.innerHTML = `
        <td style="font-weight:500">${esc(r.filename)}</td>
        <td>${date}</td>
        <td>${statusHtml}</td>
        <td class="resume-actions">
          <button class="btn btn-secondary btn-small view-resume-btn" data-id="${r.id}" data-name="${esc(r.filename)}">View</button>
          <button class="btn btn-danger btn-small delete-resume-btn" data-id="${r.id}" data-name="${esc(r.filename)}">Delete</button>
        </td>
      `;
      resumeBody.appendChild(tr);
    });

    document.querySelectorAll('.view-resume-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openPdfViewer(btn.dataset.id, btn.dataset.name);
      });
    });

    document.querySelectorAll('.delete-resume-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm(`Delete "${btn.dataset.name}"? This cannot be undone.`)) return;
        await fetch(`/api/resumes/${btn.dataset.id}`, { method: 'DELETE' });
        loadResumes();
      });
    });

    document.querySelectorAll('.set-default-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        await fetch('/api/resumes/default', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: btn.dataset.id })
        });
        loadResumes();
      });
    });
  } catch (err) {
    console.error('Failed to load resumes:', err);
  }
}

// ── PDF Viewer (PDF.js) ──
const pdfOverlay = document.getElementById('pdf-overlay');
const pdfViewerTitle = document.getElementById('pdf-viewer-title');
const pdfClose = document.getElementById('pdf-close');
const pdfPages = document.getElementById('pdf-pages');
const pdfLoading = document.getElementById('pdf-loading');

pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

async function openPdfViewer(id, filename) {
  pdfViewerTitle.textContent = filename || 'Resume Preview';
  pdfPages.innerHTML = '';
  pdfLoading.hidden = false;
  pdfOverlay.classList.add('visible');
  document.body.style.overflow = 'hidden';

  try {
    const pdf = await pdfjsLib.getDocument(`/api/resumes/${id}/view`).promise;
    pdfLoading.hidden = true;
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const scale = 1.5;
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport }).promise;
      pdfPages.appendChild(canvas);
    }
  } catch (err) {
    pdfLoading.hidden = true;
    pdfPages.innerHTML = '<p style="color:var(--danger);text-align:center;padding:40px">Failed to load PDF.</p>';
    console.error('PDF render error:', err);
  }
}

function closePdfViewer() {
  pdfOverlay.classList.remove('visible');
  pdfPages.innerHTML = '';
  document.body.style.overflow = '';
}

pdfClose.addEventListener('click', closePdfViewer);
pdfOverlay.addEventListener('click', e => {
  if (e.target === pdfOverlay) closePdfViewer();
});

// ── Utility ──
function esc(str) {
  const el = document.createElement('span');
  el.textContent = str || '';
  return el.innerHTML;
}

// ── Settings ──
const apiKeyInput = document.getElementById('api-key-input');
const saveKeyBtn = document.getElementById('save-key-btn');
const keyStatus = document.getElementById('key-status');

saveKeyBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  if (!key) {
    keyStatus.className = 'key-status error';
    keyStatus.textContent = 'Please enter an API key.';
    return;
  }

  saveKeyBtn.disabled = true;
  saveKeyBtn.textContent = 'Saving...';

  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rapidapi_key: key })
    });
    apiKeyInput.value = '';
    keyStatus.className = 'key-status success';
    keyStatus.textContent = 'API key saved. Job search will now use live data.';
    loadKeyStatus();
  } catch (err) {
    keyStatus.className = 'key-status error';
    keyStatus.textContent = 'Failed to save key.';
  } finally {
    saveKeyBtn.disabled = false;
    saveKeyBtn.textContent = 'Save Key';
  }
});

async function loadKeyStatus() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    if (data.has_key) {
      keyStatus.className = 'key-status success';
      keyStatus.textContent = `API key configured: ${data.masked_key}`;
    } else {
      keyStatus.className = 'key-status info';
      keyStatus.textContent = 'No API key set. Using sample data for job search.';
    }
  } catch (err) {
    // ignore
  }
}

// Initial load
loadResumes();
