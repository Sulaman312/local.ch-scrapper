// API Base URL
const API_BASE = '';
const APP_CONFIG = window.APP_CONFIG || {};
const PIPEDRIVE_POLL_MS = 2500;

// State
let currentJobId = null;
let currentPage = 1;
let totalPages = 1;
let totalResults = 0;
let currentFilters = {};
let currentJobStatus = null;
let currentPipedriveImportJobId = null;
let pipedrivePollTimeout = null;

// Load page
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize i18n first
    await window.i18n.initI18n();

    // Check user role and hide/show dashboard link
    try {
        const response = await fetch(`${API_BASE}/api/auth/me`);
        const data = await response.json();

        if (data.authenticated && data.role === 'user') {
            // Hide dashboard link for regular users
            const dashboardLink = document.getElementById('dashboardLink');
            if (dashboardLink) {
                dashboardLink.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Error checking auth:', error);
    }

    // Check if job_id in URL
    const urlParams = new URLSearchParams(window.location.search);
    const jobId = urlParams.get('job_id');

    if (jobId) {
        // Show specific job results
        viewJobResults(jobId);
    } else {
        // Show jobs list
        loadJobs();
    }

    // Set up event listeners
    document.getElementById('prevBtn').addEventListener('click', () => changePage(-1));
    document.getElementById('nextBtn').addEventListener('click', () => changePage(1));
    document.getElementById('exportJobBtn').addEventListener('click', exportCurrentJob);
    document.getElementById('applyFiltersBtn').addEventListener('click', applyFilters);
    document.getElementById('resetFiltersBtn').addEventListener('click', resetFilters);
    document.getElementById('importPipedriveBtn')?.addEventListener('click', handleImportToPipedriveClick);
});

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

// Load all jobs
async function loadJobs() {
    try {
        const response = await fetch(`${API_BASE}/api/scrape/jobs`);
        const jobs = await response.json();

        document.getElementById('jobsCount').textContent = jobs.length;

        const tbody = document.getElementById('jobsBody');

        if (jobs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 3rem;">
                        <div class="empty-state">
                            <div class="empty-state-icon"><i class="fas fa-folder-open" style="font-size: 3rem; color: var(--text-gray);"></i></div>
                            <div class="empty-state-text">${window.i18n.t('results.noScrapingJobs')}</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = jobs.map(job => `
            <tr>
                <td><strong>${job.keyword}</strong></td>
                <td>${formatDate(job.completed_at || job.created_at)}</td>
                <td>${job.total_companies || 0}</td>
                <td>${job.status.charAt(0).toUpperCase() + job.status.slice(1)}</td>
                <td>
                    ${job.status === 'completed' || job.status === 'stopped' || job.status === 'failed' ? `
                        <button class="btn btn-sm btn-primary" onclick="viewJobResults('${job._id}')">
                            <i class="fas fa-eye"></i> View
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="deleteJob('${job._id}', '${job.keyword}')" style="margin-left: 0.5rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    ` : `
                        <span style="color: var(--text-gray); font-size: 0.875rem;">
                            <i class="fas fa-${job.status === 'running' ? 'spinner fa-spin' : 'clock'}"></i> ${job.status}
                        </span>
                    `}
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading jobs:', error);
    }
}

// View specific job results
async function viewJobResults(jobId) {
    currentJobId = jobId;
    currentPage = 1;

    // Hide jobs view, show companies view
    document.getElementById('jobsView').style.display = 'none';
    document.getElementById('companiesView').style.display = 'block';

    // Update URL without reload
    window.history.pushState({}, '', `?job_id=${jobId}`);

    // Load job details
    try {
        const jobResponse = await fetch(`${API_BASE}/api/scrape/jobs/${jobId}`);
        const job = await jobResponse.json();
        currentJobStatus = job.status;
        document.getElementById('currentJobKeyword').textContent = job.keyword;

        // Show/hide stop button based on job status
        const stopJobBtn = document.getElementById('stopJobBtn');
        const importBtn = document.getElementById('importPipedriveBtn');
        if (job.status === 'running') {
            stopJobBtn.style.display = 'inline-block';
            stopJobBtn.setAttribute('data-job-id', job._id);
            stopJobBtn.setAttribute('data-keyword', job.keyword);
        } else {
            stopJobBtn.style.display = 'none';
        }
        if (importBtn) {
            importBtn.style.display = 'inline-flex';
            importBtn.disabled = false;
            importBtn.classList.toggle('btn-disabled', !APP_CONFIG.pipedriveImportEnabled);
        }
        resetPipedriveImportPanel();

        // Populate language filter options
        await populateLanguageFilter();

        // Load companies
        loadCompanies();

        // Auto-refresh if job is running
        if (job.status === 'running') {
            setTimeout(() => viewJobResults(jobId), 5000);
        }
    } catch (error) {
        console.error('Error loading job:', error);
    }
}

// Back to jobs list
function backToJobs() {
    currentJobId = null;
    currentJobStatus = null;
    currentPipedriveImportJobId = null;
    clearPipedriveImportPolling();
    resetPipedriveImportPanel();
    document.getElementById('jobsView').style.display = 'block';
    document.getElementById('companiesView').style.display = 'none';
    window.history.pushState({}, '', '/results');
    loadJobs();
}

// Load companies for current job
async function loadCompanies() {
    // Get rows per page from filter
    const perPage = document.getElementById('filterRowsPerPage')?.value || 25;

    const params = {
        job_id: currentJobId,
        page: currentPage,
        per_page: perPage
    };

    // Add filters to query params
    if (currentFilters.city) {
        params.city = currentFilters.city;
    }
    if (currentFilters.language && currentFilters.language.length > 0) {
        params.language = currentFilters.language.join(',');
    }
    if (currentFilters.has_local_search && currentFilters.has_local_search !== 'any') {
        params.has_local_search = currentFilters.has_local_search;
    }
    if (currentFilters.has_social_media && currentFilters.has_social_media !== 'any') {
        params.has_social_media = currentFilters.has_social_media;
    }

    const queryString = new URLSearchParams(params).toString();

    try {
        const response = await fetch(`${API_BASE}/api/companies?${queryString}`);
        const data = await response.json();

        totalPages = data.total_pages || 1;
        totalResults = data.total || 0;

        renderResults(data.companies);
        updatePagination();
        updateResultsCount();
    } catch (error) {
        console.error('Error loading companies:', error);
        showError('Failed to load companies');
    }
}

// Render results table
function renderResults(companies) {
    const tbody = document.getElementById('resultsBody');

    if (!companies || companies.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="13" style="text-align: center; padding: 3rem;">
                    <div class="empty-state">
                        <div class="empty-state-icon"><i class="fas fa-search" style="font-size: 3rem; color: var(--text-gray);"></i></div>
                        <div class="empty-state-text">No companies found</div>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = companies.map(company => {
        const phones = company.phone_numbers ? company.phone_numbers.split(',').map(p => p.trim()) : [];
        const emails = company.email ? [company.email] : [];
        const websites = company.website ? [company.website] : [];

        return `
            <tr>
                <td>
                    <span class="score-badge ${getScoreClass(company.credibility_score)}">
                        ${company.credibility_score || 0}
                    </span>
                </td>
                <td><strong>${company.title || 'N/A'}</strong></td>
                <td>${company.city || 'N/A'}</td>
                <td>${renderMultiValue(phones, 'phone', company._id)}</td>
                <td>${renderMultiValue(emails, 'email', company._id)}</td>
                <td>${renderMultiValue(websites, 'website', company._id)}</td>
                <td>${company.review_count || 0}</td>
                <td>${company.average_rating || 'N/A'}</td>
                <td>${renderSocialMedia(company)}</td>
                <td>${renderBooleanBadge(company.has_local_search)}</td>
                <td>${renderBooleanBadge(company.on_architectes_ch)}</td>
                <td>${renderBooleanBadge(company.on_bienvivre_ch)}</td>
                <td>${renderBooleanBadge(company.zip)}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="viewCompany('${company._id}')">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// Render multi-value field (phone, email, website)
function renderMultiValue(values, type, companyId) {
    if (!values || values.length === 0) return 'N/A';

    if (values.length === 1) {
        if (type === 'website') {
            const url = values[0].startsWith('http') ? values[0] : 'https://' + values[0];
            return `<a href="${url}" target="_blank" style="color: var(--navbar-secondary); text-decoration: none;">${truncate(values[0], 20)}</a>`;
        }
        return truncate(values[0], 25);
    }

    // Multiple values - show first + badge
    let firstValue = truncate(values[0], 20);
    if (type === 'website') {
        const url = values[0].startsWith('http') ? values[0] : 'https://' + values[0];
        firstValue = `<a href="${url}" target="_blank" style="color: var(--navbar-secondary); text-decoration: none;">${firstValue}</a>`;
    }

    return `
        ${firstValue}
        <span class="badge" style="background: var(--bg-gray); color: var(--text-dark); margin-left: 0.25rem; cursor: pointer;" onclick="viewCompany('${companyId}')">
            +${values.length - 1}
        </span>
    `;
}

// Render social media badges
function renderSocialMedia(company) {
    const socials = [];

    if (company.facebook_url) {
        socials.push(`<a href="${company.facebook_url}" target="_blank" class="social-badge" style="background: #1877f2; color: white; padding: 0.35rem 0.5rem; border-radius: 0.25rem; text-decoration: none; font-size: 0.875rem; display: inline-block; margin: 0.125rem; line-height: 1;" title="Facebook">
            <i class="fab fa-facebook-f"></i>
        </a>`);
    }
    if (company.instagram_url) {
        socials.push(`<a href="${company.instagram_url}" target="_blank" class="social-badge" style="background: #e4405f; color: white; padding: 0.35rem 0.5rem; border-radius: 0.25rem; text-decoration: none; font-size: 0.875rem; display: inline-block; margin: 0.125rem; line-height: 1;" title="Instagram">
            <i class="fab fa-instagram"></i>
        </a>`);
    }
    if (company.linkedin_url) {
        socials.push(`<a href="${company.linkedin_url}" target="_blank" class="social-badge" style="background: #0077b5; color: white; padding: 0.35rem 0.5rem; border-radius: 0.25rem; text-decoration: none; font-size: 0.875rem; display: inline-block; margin: 0.125rem; line-height: 1;" title="LinkedIn">
            <i class="fab fa-linkedin-in"></i>
        </a>`);
    }
    if (company.twitter_url) {
        socials.push(`<a href="${company.twitter_url}" target="_blank" class="social-badge" style="background: #1da1f2; color: white; padding: 0.35rem 0.5rem; border-radius: 0.25rem; text-decoration: none; font-size: 0.875rem; display: inline-block; margin: 0.125rem; line-height: 1;" title="Twitter">
            <i class="fab fa-twitter"></i>
        </a>`);
    }
    if (company.youtube_url) {
        socials.push(`<a href="${company.youtube_url}" target="_blank" class="social-badge" style="background: #ff0000; color: white; padding: 0.35rem 0.5rem; border-radius: 0.25rem; text-decoration: none; font-size: 0.875rem; display: inline-block; margin: 0.125rem; line-height: 1;" title="YouTube">
            <i class="fab fa-youtube"></i>
        </a>`);
    }

    return socials.length > 0 ? socials.join(' ') : renderBooleanBadge(false);
}

// Render boolean badge (true/false)
function renderBooleanBadge(value) {
    if (value === 'N/A') {
        return `<span class="badge" style="background: #f3f4f6; color: #6b7280;">N/A</span>`;
    }
    if (value === true || value === 'true' || value === 'Yes') {
        return `<span class="badge" style="background: #d1fae5; color: #065f46;">YES</span>`;
    }
    return `<span class="badge" style="background: #fee2e2; color: #991b1b;">NO</span>`;
}

// Get score class for styling
function getScoreClass(score) {
    if (score >= 70) return 'score-high';
    if (score >= 40) return 'score-medium';
    return 'score-low';
}

// View company details modal
async function viewCompany(companyId) {
    try {
        const response = await fetch(`${API_BASE}/api/companies/${companyId}`);
        const company = await response.json();

        const modal = document.getElementById('companyModal');
        const modalTitle = document.getElementById('modalTitle');
        const modalContent = document.getElementById('modalContent');

        modalTitle.textContent = company.title || 'Company Details';

        const phones = company.phone_numbers ? company.phone_numbers.split(',').map(p => p.trim()) : [];
        const emails = company.email ? [company.email] : [];

        modalContent.innerHTML = `
            <div style="display: grid; gap: 1.5rem;">
                <!-- Credibility Score Card -->
                <div style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); padding: 1.5rem; border-radius: 0.75rem; color: white; text-align: center;">
                    <div style="font-size: 0.875rem; opacity: 0.9; margin-bottom: 0.5rem;">Credibility Score</div>
                    <div style="font-size: 2.5rem; font-weight: 700;">
                        ${company.credibility_score || 0}/100
                    </div>
                </div>

                <!-- Contact Information Section -->
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-address-card"></i> Contact Information
                    </h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600; width: 30%;">Address</td>
                            <td style="padding: 0.75rem 0;">${company.street || 'N/A'}, ${company.zipcode || ''} ${company.city || ''}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600; vertical-align: top;">Phone Numbers</td>
                            <td style="padding: 0.75rem 0;">
                                ${phones.length > 0 ? phones.map(p => `<div style="margin: 0.25rem 0;"><i class="fas fa-phone" style="color: var(--navbar-secondary); width: 1.25rem;"></i> ${p}</div>`).join('') : 'N/A'}
                            </td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Email</td>
                            <td style="padding: 0.75rem 0;">${company.email ? `<i class="fas fa-envelope" style="color: var(--navbar-secondary); width: 1.25rem;"></i> ${company.email}` : 'N/A'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 0.75rem 0; font-weight: 600;">Website</td>
                            <td style="padding: 0.75rem 0;">
                                ${company.website ? `<a href="${company.website.startsWith('http') ? company.website : 'https://' + company.website}" target="_blank" style="color: var(--navbar-secondary); text-decoration: none;"><i class="fas fa-globe" style="width: 1.25rem;"></i> ${company.website}</a>` : 'N/A'}
                            </td>
                        </tr>
                    </table>
                </div>

                ${company.description ? `
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-file-alt"></i> Description
                    </h3>
                    <p style="line-height: 1.6; color: var(--text-dark);">${company.description}</p>
                </div>
                ` : ''}

                <!-- Metrics Section -->
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-chart-bar"></i> Metrics
                    </h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600; width: 50%;">Pictures</td>
                            <td style="padding: 0.75rem 0;">${company.picture_count || 0}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Reviews</td>
                            <td style="padding: 0.75rem 0;">${company.review_count || 0}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Average Rating</td>
                            <td style="padding: 0.75rem 0;">${company.average_rating || 'N/A'}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Has Social Media</td>
                            <td style="padding: 0.75rem 0;">${renderBooleanBadge(company.has_social_media)}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Has Local Search</td>
                            <td style="padding: 0.75rem 0;">${renderBooleanBadge(company.has_local_search)}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">On Architectes.ch</td>
                            <td style="padding: 0.75rem 0;">${renderBooleanBadge(company.on_architectes_ch)}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">On Bienvivre.ch</td>
                            <td style="padding: 0.75rem 0;">${renderBooleanBadge(company.on_bienvivre_ch)}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Zip.ch</td>
                            <td style="padding: 0.75rem 0;">${renderBooleanBadge(company.zip)}</td>
                        </tr>
                        ${company.languages && company.languages.length > 0 ? `
                        <tr style="border-bottom: 1px solid var(--border-gray);">
                            <td style="padding: 0.75rem 0; font-weight: 600;">Languages</td>
                            <td style="padding: 0.75rem 0;">${company.languages.join(', ')}</td>
                        </tr>
                        ` : ''}
                        ${company.copyright_year ? `
                        <tr>
                            <td style="padding: 0.75rem 0; font-weight: 600;">Copyright Year</td>
                            <td style="padding: 0.75rem 0;">${company.copyright_year}</td>
                        </tr>
                        ` : ''}
                    </table>
                </div>

                ${(company.persons && company.persons.length > 0) ? `
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-users"></i> Management & People
                    </h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        ${company.persons.map(person => `
                            <tr style="border-bottom: 1px solid var(--border-gray);">
                                <td style="padding: 0.75rem 0;">
                                    <div style="font-weight: 600;">${person.name || 'N/A'}</div>
                                    <div style="font-size: 0.875rem; color: var(--text-gray);">${person.role || ''}</div>
                                    ${person.since ? `<div style="font-size: 0.8125rem; color: var(--text-light);">Since ${person.since}</div>` : ''}
                                </td>
                                <td style="padding: 0.75rem 0; text-align: right;">
                                    ${person.linkedin ? `<a href="${person.linkedin}" target="_blank" style="color: var(--navbar-secondary); text-decoration: none;"><i class="fab fa-linkedin" style="font-size: 1.5rem;"></i></a>` : ''}
                                </td>
                            </tr>
                        `).join('')}
                    </table>
                </div>
                ` : ''}

                ${(company.facebook_url || company.instagram_url || company.linkedin_url || company.twitter_url || company.youtube_url) ? `
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-share-alt"></i> Social Media
                    </h3>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.75rem;">
                        ${renderSocialMedia(company)}
                    </div>
                </div>
                ` : ''}

                ${(company.hours_monday || company.hours_tuesday || company.hours_wednesday || company.hours_thursday || company.hours_friday || company.hours_saturday || company.hours_sunday) ? `
                <div style="background: var(--bg-light); padding: 1.5rem; border-radius: 0.75rem; border: 1px solid var(--border-gray);">
                    <h3 style="background: linear-gradient(135deg, var(--navbar-primary) 0%, var(--navbar-secondary) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1rem; font-size: 1.125rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border-gray);">
                        <i class="fas fa-clock"></i> Opening Hours
                    </h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        ${company.hours_monday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600; width: 30%;">Monday</td><td style="padding: 0.75rem 0;">${company.hours_monday}</td></tr>` : ''}
                        ${company.hours_tuesday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600;">Tuesday</td><td style="padding: 0.75rem 0;">${company.hours_tuesday}</td></tr>` : ''}
                        ${company.hours_wednesday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600;">Wednesday</td><td style="padding: 0.75rem 0;">${company.hours_wednesday}</td></tr>` : ''}
                        ${company.hours_thursday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600;">Thursday</td><td style="padding: 0.75rem 0;">${company.hours_thursday}</td></tr>` : ''}
                        ${company.hours_friday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600;">Friday</td><td style="padding: 0.75rem 0;">${company.hours_friday}</td></tr>` : ''}
                        ${company.hours_saturday ? `<tr style="border-bottom: 1px solid var(--border-gray);"><td style="padding: 0.75rem 0; font-weight: 600;">Saturday</td><td style="padding: 0.75rem 0;">${company.hours_saturday}</td></tr>` : ''}
                        ${company.hours_sunday ? `<tr><td style="padding: 0.75rem 0; font-weight: 600;">Sunday</td><td style="padding: 0.75rem 0;">${company.hours_sunday}</td></tr>` : ''}
                    </table>
                </div>
                ` : ''}
            </div>
        `;

        modal.style.display = 'block';
    } catch (error) {
        console.error('Error loading company details:', error);
        showAlert('Failed to load company details', 'error');
    }
}

// Close modal
function closeModal() {
    document.getElementById('companyModal').style.display = 'none';
}

// Export current job with filters
function exportCurrentJob() {
    const params = {
        job_id: currentJobId
    };

    // Add filters to export (excluding rows per page - export ALL filtered results)
    if (currentFilters.city) {
        params.city = currentFilters.city;
    }
    if (currentFilters.has_local_search && currentFilters.has_local_search !== 'any') {
        params.has_local_search = currentFilters.has_local_search;
    }
    if (currentFilters.has_social_media && currentFilters.has_social_media !== 'any') {
        params.has_social_media = currentFilters.has_social_media;
    }

    const queryString = new URLSearchParams(params).toString();
    window.location.href = `${API_BASE}/api/export?${queryString}`;
}

async function handleImportToPipedriveClick() {
    if (!currentJobId) {
        return;
    }

    if (!APP_CONFIG.pipedriveImportEnabled) {
        showAlert(window.i18n.t('results.pipedriveUnavailable'), 'info');
        return;
    }

    if (currentJobStatus === 'running' || currentJobStatus === 'pending') {
        showAlert(window.i18n.t('results.pipedriveWaitForCompletion'), 'warning');
        return;
    }

    await startPipedriveImport();
}

async function startPipedriveImport() {
    const importBtn = document.getElementById('importPipedriveBtn');
    clearPipedriveImportPolling();
    currentPipedriveImportJobId = null;
    setImportButtonLoading(true);
    showPipedriveImportPanel();
    updatePipedriveImportPanel({
        state: 'queued',
        percent: 0,
        processed: 0,
        total: 0,
        failed_rows: 0,
        message: window.i18n.t('results.pipedriveStarting')
    });

    try {
        const response = await fetch(`${API_BASE}/api/pipedrive-import/jobs/${currentJobId}/start`, {
            method: 'POST'
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || window.i18n.t('results.pipedriveStartFailed'));
        }

        currentPipedriveImportJobId = data.job_id;
        updatePipedriveImportPanel({
            state: 'queued',
            percent: 0,
            processed: 0,
            total: 0,
            failed_rows: 0,
            message: window.i18n.t('results.pipedriveQueued')
        });

        importBtn?.classList.remove('btn-disabled');
        pollPipedriveImportStatus();
    } catch (error) {
        updatePipedriveImportPanel({
            state: 'failed',
            percent: 0,
            processed: 0,
            total: 0,
            failed_rows: 0,
            message: window.i18n.t('results.pipedriveStartFailed'),
            error: error.message
        });
        showAlert(error.message, 'error');
    } finally {
        setImportButtonLoading(false);
    }
}

function clearPipedriveImportPolling() {
    if (pipedrivePollTimeout) {
        clearTimeout(pipedrivePollTimeout);
        pipedrivePollTimeout = null;
    }
}

function schedulePipedriveImportPoll() {
    clearPipedriveImportPolling();
    pipedrivePollTimeout = setTimeout(pollPipedriveImportStatus, PIPEDRIVE_POLL_MS);
}

async function pollPipedriveImportStatus() {
    if (!currentPipedriveImportJobId) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/pipedrive-import/jobs/${currentPipedriveImportJobId}/status`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || window.i18n.t('results.pipedriveStatusFailed'));
        }

        updatePipedriveImportPanel({
            ...data,
            message: getPipedriveStatusMessage(data)
        });

        if (data.state === 'completed') {
            await fetchPipedriveImportResult();
            return;
        }

        if (data.state === 'failed') {
            const errorMessage = data.error || window.i18n.t('results.pipedriveFailed');
            updatePipedriveImportPanel({
                ...data,
                message: errorMessage,
                error: errorMessage
            });
            return;
        }

        schedulePipedriveImportPoll();
    } catch (error) {
        updatePipedriveImportPanel({
            state: 'failed',
            message: window.i18n.t('results.pipedriveStatusFailed'),
            error: error.message
        });
    }
}

async function fetchPipedriveImportResult() {
    try {
        const response = await fetch(`${API_BASE}/api/pipedrive-import/jobs/${currentPipedriveImportJobId}/result`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || window.i18n.t('results.pipedriveResultFailed'));
        }

        if (data.state === 'failed') {
            updatePipedriveImportPanel({
                state: 'failed',
                message: data.error || window.i18n.t('results.pipedriveFailed'),
                error: data.error || window.i18n.t('results.pipedriveFailed')
            });
            return;
        }

        updatePipedriveImportPanel({
            state: 'completed',
            percent: 100,
            processed: data.result?.rows || 0,
            total: data.result?.rows || 0,
            failed_rows: data.result?.failed_rows || 0,
            organizations_created: data.result?.organizations_created || 0,
            organizations_updated: data.result?.organizations_updated || 0,
            persons_created: data.result?.persons_created || 0,
            persons_updated: data.result?.persons_updated || 0,
            deals_created: data.result?.deals_created || 0,
            deals_skipped: data.result?.deals_skipped || 0,
            message: data.result?.message || window.i18n.t('results.pipedriveCompleted')
        });
        showAlert(data.result?.message || window.i18n.t('results.pipedriveCompleted'), 'success');
    } catch (error) {
        updatePipedriveImportPanel({
            state: 'failed',
            message: window.i18n.t('results.pipedriveResultFailed'),
            error: error.message
        });
    }
}

function showPipedriveImportPanel() {
    const panel = document.getElementById('pipedriveImportPanel');
    if (panel) {
        panel.style.display = 'block';
    }
}

function resetPipedriveImportPanel() {
    const panel = document.getElementById('pipedriveImportPanel');
    if (!panel) {
        return;
    }

    panel.style.display = 'none';
    updatePipedriveImportPanel({
        state: 'idle',
        percent: 0,
        processed: 0,
        total: 0,
        failed_rows: 0,
        organizations_created: 0,
        organizations_updated: 0,
        persons_created: 0,
        persons_updated: 0,
        deals_created: 0,
        deals_skipped: 0,
        message: window.i18n?.t('results.pipedriveIdle') || 'Waiting to start.'
    });
}

function updatePipedriveImportPanel(data) {
    const state = data.state || 'idle';
    const percent = Number.isFinite(data.percent) ? data.percent : 0;
    const processed = data.processed ?? 0;
    const total = data.total ?? 0;
    const failedRows = data.failed_rows ?? 0;
    const organizationsCreated = data.organizations_created ?? 0;
    const organizationsUpdated = data.organizations_updated ?? 0;
    const personsCreated = data.persons_created ?? 0;
    const personsUpdated = data.persons_updated ?? 0;
    const dealsCreated = data.deals_created ?? 0;
    const dealsSkipped = data.deals_skipped ?? 0;
    const message = data.message || window.i18n.t('results.pipedriveIdle');

    document.getElementById('pipedriveImportMessage').textContent = message;
    document.getElementById('pipedrivePercent').textContent = `${percent}%`;
    document.getElementById('pipedriveProcessed').textContent = `${processed} / ${total}`;
    document.getElementById('pipedriveProgressFill').style.width = `${Math.max(0, Math.min(percent, 100))}%`;
    document.getElementById('pipedriveFailedRows').textContent = failedRows;
    document.getElementById('pipedriveOrganizations').textContent = `${organizationsCreated} / ${organizationsUpdated}`;
    document.getElementById('pipedrivePersons').textContent = `${personsCreated} / ${personsUpdated}`;
    document.getElementById('pipedriveDeals').textContent = `${dealsCreated} / ${dealsSkipped}`;

    const stateBadge = document.getElementById('pipedriveImportState');
    stateBadge.textContent = formatStateLabel(state);
    stateBadge.className = `pipedrive-state-badge pipedrive-state-${state}`;

    const errorBox = document.getElementById('pipedriveErrorBox');
    if (data.error) {
        errorBox.textContent = data.error;
        errorBox.style.display = 'block';
    } else {
        errorBox.textContent = '';
        errorBox.style.display = 'none';
    }
}

function setImportButtonLoading(isLoading) {
    const importBtn = document.getElementById('importPipedriveBtn');
    if (!importBtn) {
        return;
    }

    importBtn.disabled = isLoading;
    importBtn.innerHTML = isLoading
        ? `<i class="fas fa-spinner fa-spin"></i> ${window.i18n.t('results.pipedriveImporting')}`
        : `<i class="fas fa-cloud-upload-alt"></i> <span data-i18n="results.importToPipedrive">${window.i18n.t('results.importToPipedrive')}</span>`;
}

function getPipedriveStatusMessage(data) {
    if (data.state === 'completed') {
        return window.i18n.t('results.pipedriveCompleted');
    }
    if (data.state === 'failed') {
        return data.error || window.i18n.t('results.pipedriveFailed');
    }
    if (data.state === 'running') {
        return `${data.processed || 0} / ${data.total || 0} ${window.i18n.t('results.rowsProcessed')}`;
    }
    return window.i18n.t('results.pipedriveQueued');
}

function formatStateLabel(state) {
    const labels = {
        idle: window.i18n.t('results.stateIdle'),
        queued: window.i18n.t('results.stateQueued'),
        running: window.i18n.t('results.stateRunning'),
        completed: window.i18n.t('results.stateCompleted'),
        failed: window.i18n.t('results.stateFailed')
    };

    return labels[state] || state;
}

// Populate language filter with unique languages from companies
async function populateLanguageFilter() {
    try {
        const response = await fetch(`${API_BASE}/api/companies?job_id=${currentJobId}&per_page=1000`);
        const data = await response.json();

        // Extract unique languages from all companies
        const languagesSet = new Set();
        data.companies.forEach(company => {
            if (company.languages && Array.isArray(company.languages)) {
                company.languages.forEach(lang => languagesSet.add(lang));
            }
        });

        // Sort and populate custom dropdown
        const languages = Array.from(languagesSet).sort();
        const dropdown = document.getElementById('languageDropdown');
        dropdown.innerHTML = languages.map(lang => `
            <div class="multi-select-option">
                <input type="checkbox" id="lang-${lang}" value="${lang}" onchange="updateLanguageDisplay()">
                <label for="lang-${lang}">${lang}</label>
            </div>
        `).join('');

        // Setup trigger click handler
        const trigger = document.getElementById('languageTrigger');
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
            trigger.classList.toggle('active');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.custom-multi-select')) {
                dropdown.style.display = 'none';
                trigger.classList.remove('active');
            }
        });
    } catch (error) {
        console.error('Error populating language filter:', error);
    }
}

// Update language display text
function updateLanguageDisplay() {
    const checkboxes = document.querySelectorAll('#languageDropdown input[type="checkbox"]:checked');
    const display = document.getElementById('languageDisplay');

    if (checkboxes.length === 0) {
        display.textContent = 'Choose languages';
    } else if (checkboxes.length === 1) {
        display.textContent = checkboxes[0].value;
    } else {
        display.textContent = `${checkboxes.length} languages selected`;
    }
}

// Apply filters
function applyFilters() {
    // Collect filter values
    currentFilters = {};

    const city = document.getElementById('filterCity').value.trim();
    if (city) {
        currentFilters.city = city;
    }

    // Get selected languages from custom multi-select
    const languageCheckboxes = document.querySelectorAll('#languageDropdown input[type="checkbox"]:checked');
    const selectedLanguages = Array.from(languageCheckboxes).map(cb => cb.value);
    if (selectedLanguages.length > 0) {
        currentFilters.language = selectedLanguages;
    }

    const localSearch = document.getElementById('filterLocalSearch').value;
    if (localSearch !== 'any') {
        currentFilters.has_local_search = localSearch;
    }

    const socialMedia = document.getElementById('filterSocialMedia').value;
    if (socialMedia !== 'any') {
        currentFilters.has_social_media = socialMedia;
    }

    // Reset to page 1 when applying filters
    currentPage = 1;

    // Reload companies with filters
    loadCompanies();
}

// Reset filters
function resetFilters() {
    // Clear filter inputs
    document.getElementById('filterCity').value = '';

    // Clear language checkboxes
    const languageCheckboxes = document.querySelectorAll('#languageDropdown input[type="checkbox"]');
    languageCheckboxes.forEach(cb => cb.checked = false);
    document.getElementById('languageDisplay').textContent = 'Choose languages';

    document.getElementById('filterLocalSearch').value = 'any';
    document.getElementById('filterSocialMedia').value = 'any';
    document.getElementById('filterRowsPerPage').value = '25';

    // Clear current filters
    currentFilters = {};

    // Reset to page 1
    currentPage = 1;

    // Reload companies without filters
    loadCompanies();
}

// Change page
function changePage(direction) {
    currentPage += direction;
    loadCompanies();
}

// Update pagination controls
function updatePagination() {
    document.getElementById('currentPage').textContent = currentPage;
    document.getElementById('totalPages').textContent = totalPages;
    document.getElementById('prevBtn').disabled = currentPage <= 1;
    document.getElementById('nextBtn').disabled = currentPage >= totalPages;
}

// Update results count
function updateResultsCount() {
    document.getElementById('resultsCount').textContent = totalResults;

    const perPage = parseInt(document.getElementById('filterRowsPerPage')?.value || 25);
    const start = (currentPage - 1) * perPage + 1;
    const end = Math.min(currentPage * perPage, totalResults);
    document.getElementById('showingRange').textContent = totalResults > 0 ? `${start}-${end}` : '0-0';
}

// Helper: Truncate text
function truncate(text, length) {
    return text && text.length > length ? text.substring(0, length) + '...' : text;
}

// Show error message
function showError(message) {
    const tbody = document.getElementById('resultsBody');
    tbody.innerHTML = `
        <tr>
            <td colspan="11" style="text-align: center; padding: 3rem; color: var(--accent-red);">
                <i class="fas fa-exclamation-triangle"></i> ${message}
            </td>
        </tr>
    `;
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

// Delete job
async function stopCurrentJob() {
    const stopBtn = document.getElementById('stopJobBtn');
    const jobId = stopBtn.getAttribute('data-job-id');
    const keyword = stopBtn.getAttribute('data-keyword');

    showConfirm(
        `Are you sure you want to stop the scraping job for "${keyword}"?\n\nAll data scraped so far will be saved.`,
        async () => {
            try {
                const response = await fetch(`${API_BASE}/api/scrape/jobs/${jobId}/stop`, {
                    method: 'POST'
                });

                const data = await response.json();

                if (data.success) {
                    showAlert(`Job stopped successfully. ${data.companies_scraped || 0} companies were scraped.`, 'success');
                    // Reload job details
                    viewJobResults(jobId);
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

async function deleteJob(jobId, keyword) {
    showConfirm(
        `Are you sure you want to delete the "${keyword}" job and all its companies?\n\nThis action cannot be undone.`,
        async () => {
            try {
                const response = await fetch(`${API_BASE}/api/scrape/jobs/${jobId}`, {
                    method: 'DELETE'
                });

                const data = await response.json();

                if (data.success) {
                    showAlert(data.message, 'success');
                    loadJobs(); // Reload the jobs list
                } else {
                    showAlert('Error: ' + (data.error || 'Failed to delete job'), 'error');
                }
            } catch (error) {
                console.error('Error deleting job:', error);
                showAlert('Failed to delete job', 'error');
            }
        }
    );
}

// Close modal on outside click
window.onclick = function(event) {
    const modal = document.getElementById('companyModal');
    if (event.target === modal) {
        closeModal();
    }
}
