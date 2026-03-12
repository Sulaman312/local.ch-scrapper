// Custom modal system for alerts and confirmations

// Show custom alert
function showAlert(message, type = 'info') {
    const iconMap = {
        'success': '<i class="fas fa-check-circle" style="color: #10b981;"></i>',
        'error': '<i class="fas fa-exclamation-circle" style="color: #ef4444;"></i>',
        'info': '<i class="fas fa-info-circle" style="color: #3b82f6;"></i>',
        'warning': '<i class="fas fa-exclamation-triangle" style="color: #f59e0b;"></i>'
    };

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

    modal.innerHTML = `
        <div style="
            background: white;
            border-radius: 0.75rem;
            padding: 2rem;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        ">
            <div style="text-align: center; margin-bottom: 1.5rem; font-size: 3rem;">
                ${iconMap[type] || iconMap['info']}
            </div>
            <div style="
                text-align: center;
                color: var(--text-dark);
                line-height: 1.6;
                margin-bottom: 1.5rem;
                white-space: pre-line;
            ">${message}</div>
            <button id="alertOkBtn" style="
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
            ">OK</button>
        </div>
    `;

    document.body.appendChild(modal);

    const okBtn = modal.querySelector('#alertOkBtn');
    okBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
    });

    okBtn.addEventListener('mouseenter', () => {
        okBtn.style.opacity = '0.9';
    });

    okBtn.addEventListener('mouseleave', () => {
        okBtn.style.opacity = '1';
    });

    // Close on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    });

    // Focus the OK button
    setTimeout(() => okBtn.focus(), 100);

    // Close on Enter key
    okBtn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            document.body.removeChild(modal);
        }
    });
}

// Show custom confirmation dialog
function showConfirm(message, onConfirm, onCancel) {
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

    modal.innerHTML = `
        <div style="
            background: white;
            border-radius: 0.75rem;
            padding: 2rem;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        ">
            <div style="text-align: center; margin-bottom: 1.5rem; font-size: 3rem;">
                <i class="fas fa-question-circle" style="color: var(--navbar-primary);"></i>
            </div>
            <div style="
                text-align: center;
                color: var(--text-dark);
                line-height: 1.6;
                margin-bottom: 1.5rem;
                white-space: pre-line;
            ">${message}</div>
            <div style="display: flex; gap: 0.75rem;">
                <button id="confirmCancelBtn" style="
                    flex: 1;
                    padding: 0.75rem;
                    background: var(--bg-gray);
                    color: var(--text-dark);
                    border: none;
                    border-radius: 0.5rem;
                    font-size: 0.875rem;
                    font-weight: 500;
                    cursor: pointer;
                    font-family: 'Inter', sans-serif;
                ">Cancel</button>
                <button id="confirmOkBtn" style="
                    flex: 1;
                    padding: 0.75rem;
                    background: var(--accent-red);
                    color: white;
                    border: none;
                    border-radius: 0.5rem;
                    font-size: 0.875rem;
                    font-weight: 500;
                    cursor: pointer;
                    font-family: 'Inter', sans-serif;
                ">Confirm</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    const cancelBtn = modal.querySelector('#confirmCancelBtn');
    const okBtn = modal.querySelector('#confirmOkBtn');

    const cleanup = () => {
        document.body.removeChild(modal);
    };

    cancelBtn.addEventListener('click', () => {
        cleanup();
        if (onCancel) onCancel();
    });

    okBtn.addEventListener('click', () => {
        cleanup();
        if (onConfirm) onConfirm();
    });

    // Hover effects
    cancelBtn.addEventListener('mouseenter', () => {
        cancelBtn.style.background = 'var(--border-gray)';
    });

    cancelBtn.addEventListener('mouseleave', () => {
        cancelBtn.style.background = 'var(--bg-gray)';
    });

    okBtn.addEventListener('mouseenter', () => {
        okBtn.style.background = '#dc2626';
    });

    okBtn.addEventListener('mouseleave', () => {
        okBtn.style.background = 'var(--accent-red)';
    });

    // Close on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            cleanup();
            if (onCancel) onCancel();
        }
    });

    // Focus the confirm button
    setTimeout(() => okBtn.focus(), 100);

    // Keyboard navigation
    document.addEventListener('keydown', function handleKeydown(e) {
        if (e.key === 'Escape') {
            cleanup();
            if (onCancel) onCancel();
            document.removeEventListener('keydown', handleKeydown);
        }
    });
}
