// API Base URL
const API_BASE = '';

// State
let currentJobId = null;
let currentPage = 1;
let totalPages = 1;
let totalResults = 0;
let currentFilters = {};

// Load page
document.addEventListener('DOMContentLoaded', () => {
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
});

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
                            <div class="empty-state-text">No scraping jobs yet</div>
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
                    ${job.status === 'completed' ? `
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
        document.getElementById('currentJobKeyword').textContent = job.keyword;

        // Populate language filter options
        await populateLanguageFilter();

        // Load companies
        loadCompanies();
    } catch (error) {
        console.error('Error loading job:', error);
    }
}

// Back to jobs list
function backToJobs() {
    currentJobId = null;
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
    if (value === true || value === 'true') {
        return `<span class="badge" style="background: #d1fae5; color: #065f46;">TRUE</span>`;
    }
    return `<span class="badge" style="background: #fee2e2; color: #991b1b;">FALSE</span>`;
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
