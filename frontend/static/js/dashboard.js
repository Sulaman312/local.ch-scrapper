// API Base URL
const API_BASE = '';

// Load stats on page load
document.addEventListener('DOMContentLoaded', () => {
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
                <div class="empty-state-text">No active jobs</div>
            </div>
        `;
        return;
    }

    container.innerHTML = jobs.map(job => {
        const companiesScraped = job.companies_scraped || 0;
        const totalCompanies = job.total_companies || 0;
        const percentage = totalCompanies > 0 ? Math.round((companiesScraped / totalCompanies) * 100) : 0;

        return `
        <div class="job-card">
            <div class="job-header">
                <div class="job-title">
                    <i class="fas fa-${job.status === 'running' ? 'spinner fa-spin' : 'pause'}"></i> ${job.keyword}
                </div>
            </div>
            <div class="job-meta">
                Started: ${formatDate(job.started_at || job.created_at)} •
                ${companiesScraped}${totalCompanies > 0 ? `/${totalCompanies}` : ''} companies scraped
            </div>
            ${job.status === 'running' && totalCompanies > 0 ? `
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${percentage}%"></div>
                </div>
                <div style="text-align: center; font-size: 0.875rem; color: var(--text-gray); margin-top: 0.25rem;">
                    ${percentage}% complete
                </div>
            ` : ''}
            ${companiesScraped > 0 ? `
                <div class="job-actions" style="margin-top: 0.75rem;">
                    <a href="/results?job_id=${job._id}" class="btn btn-sm btn-primary">
                        <i class="fas fa-eye"></i> View Progress (${companiesScraped} companies)
                    </a>
                </div>
            ` : ''}
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
                <div class="empty-state-text">No completed jobs yet</div>
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
                Completed: ${formatDate(job.completed_at)} •
                ${job.total_companies || 0} companies scraped
                ${job.error_message ? `<br><span style="color: var(--accent-red);">Error: ${job.error_message}</span>` : ''}
            </div>
            ${job.status === 'completed' ? `
                <div class="job-actions">
                    <a href="/results?job_id=${job._id}" class="btn btn-sm btn-primary">
                        <i class="fas fa-eye"></i> View Results
                    </a>
                    <button class="btn btn-sm btn-secondary" onclick="downloadResults('${job.keyword}')">
                        <i class="fas fa-download"></i> Download Excel
                    </button>
                </div>
            ` : ''}
        </div>
    `).join('');
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

    if (!keyword) {
        showAlert('Please enter a keyword', 'warning');
        return;
    }

    const startBtn = document.getElementById('startBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

    try {
        const response = await fetch(`${API_BASE}/api/scrape/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                keyword,
                max_pages: maxPages,
                max_companies: maxCompanies,
                check_websites: checkWebsites,
                check_moneyhouse: checkMoneyhouse,
                check_architectes: checkArchitectes,
                check_bienvivre: checkBienvivre
            })
        });

        const data = await response.json();

        if (data.success) {
            showAlert(`Scraping job started for "${keyword}"! You'll see the results here when done.`, 'success');

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
        startBtn.innerHTML = '<i class="fas fa-play"></i> Start Scraping';
    }
}

// Download results as Excel
async function downloadResults(keyword) {
    window.location.href = `${API_BASE}/api/export?keyword=${encodeURIComponent(keyword)}`;
}

// Format date helper
function formatDate(dateStr) {
    if (!dateStr) return 'N/A';

    const date = new Date(dateStr);
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
