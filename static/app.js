/* static/app.js */
document.addEventListener('DOMContentLoaded', () => {
    initCursor();
    init3DCards();
    initFilterAndSearch();
    initFileUpload();
    initForms();

    // Initial fetches
    fetchStats();
    setInterval(fetchStats, 30000);

    // Initial animations
    if (window.gsap) {
        gsap.from(".reveal-text", { y: 30, opacity: 0, duration: 1, ease: "power3.out" });
        gsap.from(".reveal-text-delay", { y: 30, opacity: 0, duration: 1, delay: 0.2, ease: "power3.out" });
    }
});

// Custom Cursor Logic
function initCursor() {
    const cursor = document.getElementById('cursorGlow');
    if (!cursor) return;

    document.addEventListener('mousemove', (e) => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
    });

    const interactives = document.querySelectorAll('button, a, input, select, .item-card');
    interactives.forEach(el => {
        el.addEventListener('mouseenter', () => cursor.classList.add('interactive'));
        el.addEventListener('mouseleave', () => cursor.classList.remove('interactive'));
    });
}

// 3D Card Hover Effect
function init3DCards() {
    const cards = document.querySelectorAll('.3d-card');
    cards.forEach(card => {
        card.addEventListener('mousemove', e => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            const rotateX = ((y - centerY) / centerY) * -10; // Max 10deg
            const rotateY = ((x - centerX) / centerX) * 10;

            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
        });

        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
        });
    });
}

// Advanced Filtering & Searching
function initFilterAndSearch() {
    const searchInput = document.getElementById('liveSearch');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const items = document.querySelectorAll('.item-entry');
    const noResults = document.getElementById('noResultsDeck');
    const mainEmptyDeck = document.querySelector('.empty-deck:not(#noResultsDeck)'); // The native one

    let currentFilter = 'all';
    let currentSearch = '';

    function applyFilters() {
        const currentItems = document.querySelectorAll('.item-entry');
        let visibleCount = 0;
        const totalItems = currentItems.length;

        currentItems.forEach(item => {
            const cat = item.getAttribute('data-category') || '';
            const name = (item.getAttribute('data-name') || '').toLowerCase();
            const loc = (item.getAttribute('data-location') || '').toLowerCase();

            const searchLower = currentSearch.toLowerCase();

            const matchesFilter = currentFilter === 'all' || cat === currentFilter;
            const matchesSearch = name.includes(searchLower) || loc.includes(searchLower);

            if (matchesFilter && matchesSearch) {
                item.style.setProperty('display', 'block', 'important');
                item.classList.remove('hidden');
                visibleCount++;
            } else {
                item.style.setProperty('display', 'none', 'important');
                item.classList.add('hidden');
            }
        });

        // Handle empty states
        if (totalItems > 0) { // Only handle search empty state if there are actually items in DB
            if (visibleCount === 0) {
                if (noResults) noResults.classList.remove('hidden');
            } else {
                if (noResults) noResults.classList.add('hidden');
            }
        }
    }

    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentSearch = e.target.value.toLowerCase().trim();
            applyFilters();
        });
    }

    filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            filterBtns.forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            currentFilter = e.currentTarget.getAttribute('data-filter');
            applyFilters();
        });
    });
}

// File Upload Logic
function initFileUpload() {
    const photoInput = document.getElementById('photoInput');
    const imagePreview = document.getElementById('imagePreview');
    const uploadZone = document.getElementById('uploadZone');

    if (photoInput && imagePreview && uploadZone) {
        photoInput.addEventListener('change', function () {
            if (this.files && this.files[0]) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    imagePreview.src = e.target.result;
                    imagePreview.classList.remove('hidden');
                }
                reader.readAsDataURL(this.files[0]);
            } else {
                imagePreview.classList.add('hidden');
            }
        });

        uploadZone.addEventListener('click', (e) => {
            if (e.target !== photoInput) {
                photoInput.click();
            }
        });

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('drag-active');
        });
        uploadZone.addEventListener('dragleave', () => {
            uploadZone.classList.remove('drag-active');
        });
        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-active');
            if (e.dataTransfer.files.length) {
                photoInput.files = e.dataTransfer.files;
                photoInput.dispatchEvent(new Event('change'));
            }
        });
    }
}

// Forms Handling (Upload & Verify)
function initForms() {
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = uploadForm.querySelector('button[type="submit"]');

            if (btn) btn.classList.add('loading');
            if (btn) btn.disabled = true;

            const formData = new FormData(uploadForm);

            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                const data = await response.json();

                if (data.success) {
                    window.location.reload();
                } else {
                    showToast(data.message || 'Upload failed', 'danger');
                    if (btn) btn.classList.remove('loading');
                    if (btn) btn.disabled = false;
                }
            } catch (err) {
                console.error(err);
                uploadForm.submit(); // fallback
            }
        });
    }
}

// Stats Fetching
async function fetchStats() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();
        const activeEl = document.getElementById('activeCount');
        const claimedEl = document.getElementById('claimedCount');

        animateValue(activeEl, parseInt(activeEl.innerText) || 0, data.active, 1500);
        animateValue(claimedEl, parseInt(claimedEl.innerText) || 0, data.claimed, 1500);
    } catch (err) {
        console.error('Failed to fetch stats', err);
    }
}

// Modal Logic
window.openModal = function (id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

window.closeModal = function (id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.classList.remove('active');
        if (id.startsWith('verifyModal')) {
            setTimeout(() => {
                const form = modal.querySelector('form');
                if (form) {
                    form.reset();
                    form.classList.remove('hidden');
                }
                const resultDiv = modal.querySelector('.alert-box');
                if (resultDiv) {
                    resultDiv.classList.add('hidden');
                    resultDiv.innerHTML = '';
                    resultDiv.className = 'alert-box hidden';
                }
            }, 400);
        }
        if (id === 'uploadModal') {
            setTimeout(() => {
                const form = modal.querySelector('form');
                if (form) form.reset();
                const preview = document.getElementById('imagePreview');
                if (preview) preview.classList.add('hidden');
                toggleFields(); // reset to default generic
            }, 400);
        }
    }
    document.body.style.overflow = 'auto';
}

window.onclick = function (event) {
    if (event.target.classList.contains('modal-backdrop')) {
        closeModal(event.target.id);
    }
}

// Upload Form Conditional Fields
window.toggleFields = function () {
    const cat = document.getElementById('categorySelect').value;
    const generic = document.getElementById('genericFields');
    const electronics = document.getElementById('electronicsFields');

    if (cat === 'Electronics') {
        if (generic) generic.classList.remove('active');
        setTimeout(() => {
            if (generic) generic.classList.add('hidden');
            if (electronics) { electronics.classList.remove('hidden'); }
            setTimeout(() => { if (electronics) electronics.classList.add('active'); }, 50);
        }, 200);

        document.querySelector('input[name="secret_question"]').removeAttribute('required');
        document.querySelector('input[name="secret_answer"]').removeAttribute('required');
        document.querySelector('input[name="serial_number"]').setAttribute('required', 'true');
    } else {
        if (electronics) electronics.classList.remove('active');
        setTimeout(() => {
            if (electronics) electronics.classList.add('hidden');
            if (generic) { generic.classList.remove('hidden'); }
            setTimeout(() => { if (generic) generic.classList.add('active'); }, 50);
        }, 200);

        document.querySelector('input[name="secret_question"]').setAttribute('required', 'true');
        document.querySelector('input[name="secret_answer"]').setAttribute('required', 'true');
        document.querySelector('input[name="serial_number"]').removeAttribute('required');
    }
}

// Verification Logic
window.handleVerify = async function (event, itemId) {
    event.preventDefault();
    const form = event.target;
    const btn = form.querySelector('button[type="submit"]');

    if (btn) btn.classList.add('loading');
    if (btn) btn.disabled = true;

    const formData = new FormData(form);
    const resultDiv = document.getElementById(`result-${itemId}`);

    try {
        const response = await fetch(`/verify/${itemId}`, {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await response.json();

        if (resultDiv) resultDiv.className = 'alert-box';

        if (data.success) {
            if (resultDiv) {
                resultDiv.classList.add('alert-success');
                resultDiv.innerHTML = `
                    <div style="display:flex; align-items:center; gap:8px;">
                        <i class="fa-solid fa-circle-check" style="font-size:1.5rem;"></i>
                        <strong style="font-size:1.2rem;">Match Confirmed!</strong>
                    </div>
                    <div style="margin-top:0.5rem; color: #f8fafc;">
                        <p>${data.message}</p>
                        <div class="contact-display">
                            ${data.contact}
                        </div>
                    </div>
                `;
            }
            form.classList.add('hidden');
            fetchStats();
        } else {
            if (resultDiv) {
                resultDiv.classList.add('alert-danger');
                resultDiv.innerHTML = `
                    <div style="display:flex; align-items:center; gap:8px;">
                        <i class="fa-solid fa-triangle-exclamation" style="font-size:1.2rem;"></i>
                        <strong>Authentication Failed</strong>
                    </div>
                    <p style="margin-top:0.5rem; color: white;">${data.message}</p>
                `;
            }
            form.reset();
        }
    } catch (error) {
        console.error('Error:', error);
        if (resultDiv) {
            resultDiv.className = 'alert-box alert-danger';
            resultDiv.innerHTML = '<strong>Network Error. Try again.</strong>';
        }
    } finally {
        if (!form.classList.contains('hidden')) {
            if (btn) btn.classList.remove('loading');
            if (btn) btn.disabled = false;
        }
    }
}

// Custom Toast
window.showToast = function (message, type) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-hub';
        document.body.appendChild(container);
    }

    let iconClass = 'fa-circle-info';
    if (type === 'success') iconClass = 'fa-circle-check';
    if (type === 'danger') iconClass = 'fa-triangle-exclamation';

    const toast = document.createElement('div');
    toast.className = `toast-modern toast-${type}`;
    toast.innerHTML = `
        <div class="toast-indicator"></div>
        <div class="toast-content">
            <i class="fa-solid ${iconClass}"></i>
            <span>${message}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <i class="fa-solid fa-xmark"></i>
        </button>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        if (document.body.contains(toast)) {
            toast.remove();
        }
    }, 5000);
}

// Number Counter Animation
function animateValue(obj, start, end, duration) {
    if (!obj || start === end) {
        if (obj) obj.innerHTML = end;
        return;
    }
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 4); // easeOutQuart
        obj.innerHTML = Math.floor(ease * (end - start) + start);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        } else {
            obj.innerHTML = end;
        }
    };
    window.requestAnimationFrame(step);
}
