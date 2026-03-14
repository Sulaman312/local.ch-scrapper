// i18n - Internationalization module
let currentLang = 'fr'; // Default language is French
let translations = {};

// Load translation file
async function loadTranslations(lang) {
    try {
        const response = await fetch(`/static/lang/${lang}.json`);
        translations = await response.json();
        return translations;
    } catch (error) {
        console.error(`Error loading translations for ${lang}:`, error);
        return null;
    }
}

// Get nested translation value
function getNestedValue(obj, path) {
    return path.split('.').reduce((current, key) => current?.[key], obj);
}

// Translate a key
function t(key, replacements = {}) {
    let value = getNestedValue(translations, key);

    if (!value) {
        console.warn(`Translation key not found: ${key}`);
        return key;
    }

    // Replace placeholders like {keyword}, {count}, etc.
    Object.keys(replacements).forEach(placeholder => {
        value = value.replace(`{${placeholder}}`, replacements[placeholder]);
    });

    return value;
}

// Update all elements with data-i18n attribute
function updatePageTranslations() {
    // Update text content
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        element.textContent = t(key);
    });

    // Update placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
        const key = element.getAttribute('data-i18n-placeholder');
        element.placeholder = t(key);
    });
}

// Change language
async function changeLanguage(lang) {
    currentLang = lang;

    // Save to sessionStorage (persists during session only)
    sessionStorage.setItem('language', lang);

    // Load translations
    await loadTranslations(lang);

    // Update page
    updatePageTranslations();

    // Update language dropdown
    const langSelect = document.getElementById('langSelect');
    if (langSelect) {
        langSelect.value = lang;
    }
}

// Initialize i18n on page load
async function initI18n() {
    // Check if language is set in sessionStorage (persists during current session)
    // If not, default to French
    const sessionLang = sessionStorage.getItem('language');
    const defaultLang = sessionLang || 'fr';

    // Load initial translations
    await loadTranslations(defaultLang);
    currentLang = defaultLang;

    // Update page
    updatePageTranslations();

    // Set up language selector dropdown
    const langSelect = document.getElementById('langSelect');
    if (langSelect) {
        // Set initial value
        langSelect.value = currentLang;

        // Add change handler
        langSelect.addEventListener('change', (e) => changeLanguage(e.target.value));
    }
}

// Export functions for use in other scripts
window.i18n = {
    t,
    currentLang: () => currentLang,
    changeLanguage,
    initI18n
};
