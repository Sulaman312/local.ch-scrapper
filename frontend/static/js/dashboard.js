// API Base URL
const API_BASE = '';

// Load stats on page load
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize i18n first
    await window.i18n.initI18n();

    loadStats();
    loadJobs();

    // Set up form submission
    document.getElementById('scrapeForm').addEventListener('submit', handleStartScrape);

    // Auto-refresh jobs (interval will be adjusted based on active jobs)
    window.jobsRefreshInterval = setInterval(loadJobs, 30000);
});

// Load dashboard statistics
async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const data = await response.json();

        document.getElementById('statTotalCompanies').textContent = data.total_companies || 0;
        document.getElementById('statAvgScore').textContent = data.avg_credibility_score || 0;
        document.getElementById('statSocialMedia').textContent = data.has_social_media || 0;
        document.getElementById('statLocalSearch').textContent = data.has_local_search || 0;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load all jobs
async function loadJobs() {
    try {
        const response = await fetch(`${API_BASE}/api/scrape/jobs`);
        const jobs = await response.json();

        const activeJobs = jobs.filter(j => j.status === 'pending' || j.status === 'running');
        const completedJobs = jobs.filter(j => j.status === 'completed' || j.status === 'failed');

        renderActiveJobs(activeJobs);
        renderRecentJobs(completedJobs);

        // If there are active jobs, refresh more frequently (every 5 seconds)
        if (activeJobs.length > 0) {
            clearInterval(window.jobsRefreshInterval);
            window.jobsRefreshInterval = setInterval(loadJobs, 5000);
        } else {
            // Otherwise, slower refresh (every 30 seconds)
            clearInterval(window.jobsRefreshInterval);
            window.jobsRefreshInterval = setInterval(loadJobs, 30000);
        }
    } catch (error) {
        console.error('Error loading jobs:', error);
    }
}

// Render active jobs
function renderActiveJobs(jobs) {
    const container = document.getElementById('activeJobs');

    if (jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon"><i class="fas fa-clock" style="font-size: 3rem; color: var(--text-gray);"></i></div>
                <div class="empty-state-text">${window.i18n.t('activeJobs.noActiveJobs')}</div>
            </div>
        `;
        return;
    }

    container.innerHTML = jobs.map(job => {
        const companiesScraped = job.companies_scraped || 0;
        const totalCompanies = job.total_companies || 0;
        const percentage = totalCompanies > 0 ? Math.round((companiesScraped / totalCompanies) * 100) : 0;

        // Determine status message
        let statusMessage;
        if (totalCompanies === 0 && companiesScraped === 0) {
            statusMessage = `<i class="fas fa-search"></i> ${window.i18n.t('activeJobs.gatheringCompanies')}`;
        } else {
            statusMessage = `${companiesScraped}${totalCompanies > 0 ? `/${totalCompanies}` : ''} ${window.i18n.t('activeJobs.companiesScraped')}`;
        }

        return `
        <div class="job-card">
            <div class="job-header">
                <div class="job-title">
                    <i class="fas fa-${job.status === 'running' ? 'spinner fa-spin' : 'pause'}"></i> ${job.keyword}
                </div>
            </div>
            <div class="job-meta">
                ${window.i18n.t('activeJobs.started')}: ${formatDate(job.started_at || job.created_at)} •
                ${statusMessage}
            </div>
            ${job.status === 'running' && totalCompanies > 0 ? `
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${percentage}%"></div>
                </div>
                <div style="text-align: center; font-size: 0.875rem; color: var(--text-gray); margin-top: 0.25rem;">
                    ${percentage}% ${window.i18n.t('activeJobs.complete')}
                </div>
            ` : ''}
            <div class="job-actions" style="margin-top: 0.75rem; display: flex; gap: 0.5rem;">
                ${companiesScraped > 0 ? `
                    <a href="/results?job_id=${job._id}" class="btn btn-sm btn-primary">
                        <i class="fas fa-eye"></i> ${window.i18n.t('activeJobs.viewProgress')} (${companiesScraped} companies)
                    </a>
                ` : ''}
                ${job.status === 'running' ? `
                    <button class="btn btn-sm btn-secondary" onclick="stopJob('${job._id}', '${job.keyword}')">
                        <i class="fas fa-stop"></i> ${window.i18n.t('activeJobs.stopJob')}
                    </button>
                ` : ''}
            </div>
        </div>
    `}).join('');
}

// Render recent completed jobs
function renderRecentJobs(jobs) {
    const container = document.getElementById('recentJobs');

    if (jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon"><i class="fas fa-clipboard-list" style="font-size: 3rem; color: var(--text-gray);"></i></div>
                <div class="empty-state-text">${window.i18n.t('recentJobs.noCompletedJobs')}</div>
            </div>
        `;
        return;
    }

    container.innerHTML = jobs.slice(0, 10).map(job => `
        <div class="job-card">
            <div class="job-header">
                <div class="job-title">
                    ${job.keyword}
                </div>
            </div>
            <div class="job-meta">
                ${window.i18n.t('recentJobs.completed')}: ${formatDate(job.completed_at)} •
                ${job.total_companies || 0} ${window.i18n.t('activeJobs.companiesScraped')}
                ${job.error_message ? `<br><span style="color: var(--accent-red);">${window.i18n.t('recentJobs.error')}: ${job.error_message}</span>` : ''}
            </div>
            ${job.status === 'completed' ? `
                <div class="job-actions">
                    <a href="/results?job_id=${job._id}" class="btn btn-sm btn-primary">
                        <i class="fas fa-eye"></i> ${window.i18n.t('recentJobs.viewResults')}
                    </a>
                    <button class="btn btn-sm btn-secondary" onclick="downloadResults('${job.keyword}')">
                        <i class="fas fa-download"></i> ${window.i18n.t('recentJobs.downloadExcel')}
                    </button>
                </div>
            ` : ''}
        </div>
    `).join('');
}

// Show continue prompt modal
async function showContinuePrompt(keyword, lastMaxPages, newMaxPages) {
    const endPage = newMaxPages ? (lastMaxPages + newMaxPages) : '?';
    const lang = window.i18n?.currentLang || 'fr';

    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 10000;
            display: flex;
            align-items: center;
            justify-content: center;
        `;

        const titleText = lang === 'fr' ? 'Mot-clé déjà extrait' : 'Keyword Already Scraped';
        const descText = lang === 'fr'
            ? `Vous avez déjà extrait "<strong>${keyword}</strong>" récemment (${lastMaxPages} pages).${newMaxPages ? `<br><br>Si vous continuez, il extraira les pages <strong>${lastMaxPages + 1}-${endPage}</strong>.` : ''}`
            : `You've already scraped "<strong>${keyword}</strong>" recently (${lastMaxPages} pages).${newMaxPages ? `<br><br>If you continue, it will scrape pages <strong>${lastMaxPages + 1}-${endPage}</strong>.` : ''}`;
        const continueText = lang === 'fr' ? `Continuer depuis la page ${lastMaxPages + 1}` : `Continue from Page ${lastMaxPages + 1}`;
        const freshText = lang === 'fr' ? 'Recommencer depuis la page 1' : 'Start Fresh from Page 1';
        const cancelText = lang === 'fr' ? 'Annuler' : 'Cancel';

        modal.innerHTML = `
            <div style="
                background: white;
                border-radius: 0.75rem;
                padding: 2rem;
                max-width: 500px;
                width: 90%;
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
            ">
                <div style="text-align: center; margin-bottom: 1.5rem; font-size: 3rem;">
                    <i class="fas fa-info-circle" style="color: var(--navbar-primary);"></i>
                </div>
                <h3 style="
                    margin: 0 0 1rem 0;
                    text-align: center;
                    color: var(--text-dark);
                    font-size: 1.25rem;
                    font-weight: 600;
                ">${titleText}</h3>
                <div style="
                    text-align: center;
                    color: var(--text-gray);
                    line-height: 1.6;
                    margin-bottom: 1.5rem;
                ">
                    ${descText}
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                    <button id="continueBtn" style="
                        width: 100%;
                        padding: 0.75rem;
                        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                        color: white;
                        border: none;
                        border-radius: 0.5rem;
                        font-size: 0.875rem;
                        font-weight: 500;
                        cursor: pointer;
                        font-family: 'Inter', sans-serif;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 0.5rem;
                    ">
                        <i class="fas fa-play"></i> ${continueText}
                    </button>
                    <button id="freshBtn" style="
                        width: 100%;
                        padding: 0.75rem;
                        background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%);
                        color: white;
                        border: none;
                        border-radius: 0.5rem;
                        font-size: 0.875rem;
                        font-weight: 500;
                        cursor: pointer;
                        font-family: 'Inter', sans-serif;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 0.5rem;
                    ">
                        <i class="fas fa-redo"></i> ${freshText}
                    </button>
                    <button id="cancelBtn" style="
                        width: 100%;
                        padding: 0.75rem;
                        background: var(--bg-gray);
                        color: var(--text-dark);
                        border: none;
                        border-radius: 0.5rem;
                        font-size: 0.875rem;
                        font-weight: 500;
                        cursor: pointer;
                        font-family: 'Inter', sans-serif;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 0.5rem;
                    ">
                        <i class="fas fa-times"></i> ${cancelText}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const cancelBtn = modal.querySelector('#cancelBtn');
        const freshBtn = modal.querySelector('#freshBtn');
        const continueBtn = modal.querySelector('#continueBtn');

        const cleanup = () => {
            document.body.removeChild(modal);
        };

        cancelBtn.addEventListener('click', () => {
            cleanup();
            resolve('cancel');
        });

        freshBtn.addEventListener('click', () => {
            cleanup();
            resolve('fresh');
        });

        continueBtn.addEventListener('click', () => {
            cleanup();
            resolve('continue');
        });

        // Hover effects
        continueBtn.addEventListener('mouseenter', () => {
            continueBtn.style.opacity = '0.9';
        });
        continueBtn.addEventListener('mouseleave', () => {
            continueBtn.style.opacity = '1';
        });

        freshBtn.addEventListener('mouseenter', () => {
            freshBtn.style.opacity = '0.9';
        });
        freshBtn.addEventListener('mouseleave', () => {
            freshBtn.style.opacity = '1';
        });

        cancelBtn.addEventListener('mouseenter', () => {
            cancelBtn.style.background = 'var(--border-gray)';
        });
        cancelBtn.addEventListener('mouseleave', () => {
            cancelBtn.style.background = 'var(--bg-gray)';
        });

        // Close on background click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                cleanup();
                resolve('cancel');
            }
        });

        // Focus the continue button
        setTimeout(() => continueBtn.focus(), 100);

        // Keyboard navigation
        document.addEventListener('keydown', function handleKeydown(e) {
            if (e.key === 'Escape') {
                cleanup();
                resolve('cancel');
                document.removeEventListener('keydown', handleKeydown);
            }
        });
    });
}

// Handle start scrape form submission
async function handleStartScrape(e) {
    e.preventDefault();

    const keyword = document.getElementById('keyword').value.trim();
    const maxPagesInput = document.getElementById('maxPages').value.trim();
    const maxPages = maxPagesInput ? parseInt(maxPagesInput) : null;
    const maxCompaniesInput = document.getElementById('maxCompanies').value.trim();
    const maxCompanies = maxCompaniesInput ? parseInt(maxCompaniesInput) : null;

    // Get optional data enrichment options
    const checkWebsites = document.getElementById('checkWebsites').checked;
    const checkMoneyhouse = document.getElementById('checkMoneyhouse').checked;
    const checkArchitectes = document.getElementById('checkArchitectes').checked;
    const checkBienvivre = document.getElementById('checkBienvivre').checked;
    const checkZip = document.getElementById('checkZip').checked;

    if (!keyword) {
        showAlert('Please enter a keyword', 'warning');
        return;
    }

    const startBtn = document.getElementById('startBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${window.i18n.t('scrapeForm.checking', 'Checking...')}`;

    let startPage = 1;
    let adjustedMaxPages = maxPages;

    try {
        // Check if keyword was scraped recently
        const checkResponse = await fetch(`${API_BASE}/api/scrape/check-keyword`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ keyword })
        });

        const checkData = await checkResponse.json();

        // If keyword exists, prompt user
        if (checkData.exists && checkData.last_max_pages) {
            const continueChoice = await showContinuePrompt(keyword, checkData.last_max_pages, maxPages);

            if (continueChoice === 'cancel') {
                startBtn.disabled = false;
                startBtn.innerHTML = `<i class="fas fa-play"></i> ${window.i18n.t('scrapeForm.startScraping')}`;
                return;
            } else if (continueChoice === 'continue') {
                startPage = checkData.last_max_pages + 1;
                // CRITICAL: Adjust max_pages to be the total end page
                if (maxPages) {
                    adjustedMaxPages = checkData.last_max_pages + maxPages;
                }
            }
            // If 'fresh', startPage remains 1 and maxPages unchanged
        }
    } catch (checkError) {
        console.error('Error checking keyword:', checkError);
        // Continue with normal scraping if check fails
    }

    try {
        startBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${window.i18n.t('scrapeForm.starting')}`;

        const response = await fetch(`${API_BASE}/api/scrape/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                keyword,
                max_pages: adjustedMaxPages,
                max_companies: maxCompanies,
                start_page: startPage,
                check_websites: checkWebsites,
                check_moneyhouse: checkMoneyhouse,
                check_architectes: checkArchitectes,
                check_bienvivre: checkBienvivre,
                check_zip: checkZip
            })
        });

        const data = await response.json();

        if (data.success) {
            showAlert(window.i18n.t('alerts.jobStarted', {keyword}), 'success');

            // Reset form
            document.getElementById('scrapeForm').reset();

            // Reload jobs immediately
            loadJobs();
        } else {
            showAlert('Error: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Error starting scrape:', error);
        showAlert('Failed to start scraping job. Check console for details.', 'error');
    } finally {
        startBtn.disabled = false;
        startBtn.innerHTML = `<i class="fas fa-play"></i> ${window.i18n.t('scrapeForm.startScraping')}`;
    }
}

// Download results as Excel
async function downloadResults(keyword) {
    window.location.href = `${API_BASE}/api/export?keyword=${encodeURIComponent(keyword)}`;
}

// Stop a running job
async function stopJob(jobId, keyword) {
    showConfirm(
        `Are you sure you want to stop the scraping job for "${keyword}"?\n\nAll data scraped so far will be saved.`,
        async () => {
            try {
                const response = await fetch(`${API_BASE}/api/scrape/jobs/${jobId}/stop`, {
                    method: 'POST'
                });

                const data = await response.json();

                if (data.success) {
                    showAlert(window.i18n.t('alerts.jobStopped', {count: data.companies_scraped || 0}), 'success');
                    loadJobs();
                } else {
                    showAlert('Error: ' + (data.error || 'Failed to stop job'), 'error');
                }
            } catch (error) {
                console.error('Error stopping job:', error);
                showAlert('Failed to stop job. Check console for details.', 'error');
            }
        }
    );
}

// Logout function
async function logout(event) {
    if (event) event.preventDefault();

    try {
        await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
        window.location.href = '/login';
    } catch (error) {
        console.error('Logout error:', error);
        window.location.href = '/login';
    }
}

// Format date helper
function formatDate(dateStr) {
    if (!dateStr) return 'N/A';

    // Parse the date string - handle ISO format properly
    const date = new Date(dateStr);

    // Check if date is valid
    if (isNaN(date.getTime())) {
        return 'Invalid date';
    }

    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins} min ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;

    return date.toLocaleDateString();
}
