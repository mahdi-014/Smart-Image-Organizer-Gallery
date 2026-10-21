/**
 * Smart Image Organizer & Gallery — Frontend Application
 * Pure vanilla JavaScript. Zero external dependencies.
 */

(function () {
  'use strict';

  // Application State
  const state = {
    page: 1,
    limit: 24,
    categoryId: null,
    status: null,
    searchQuery: '',
    total: 0,
    items: [],
    categories: [],
    selectedModalIndex: -1,
    isLoading: false,
  };

  // DOM Elements
  const elements = {
    connectionStatus: document.getElementById('connectionStatus'),
    connectionText: document.getElementById('connectionText'),
    totalImagesCount: document.getElementById('totalImagesCount'),
    searchInput: document.getElementById('searchInput'),
    clearSearchBtn: document.getElementById('clearSearchBtn'),
    categoryFilter: document.getElementById('categoryFilter'),
    statusFilter: document.getElementById('statusFilter'),
    pageSizeSelect: document.getElementById('pageSizeSelect'),
    refreshBtn: document.getElementById('refreshBtn'),
    galleryGrid: document.getElementById('galleryGrid'),
    loadingState: document.getElementById('loadingState'),
    errorState: document.getElementById('errorState'),
    errorMessage: document.getElementById('errorMessage'),
    emptyState: document.getElementById('emptyState'),
    retryBtn: document.getElementById('retryBtn'),
    resetFiltersBtn: document.getElementById('resetFiltersBtn'),
    paginationSummary: document.getElementById('paginationSummary'),
    firstPageBtn: document.getElementById('firstPageBtn'),
    prevPageBtn: document.getElementById('prevPageBtn'),
    nextPageBtn: document.getElementById('nextPageBtn'),
    lastPageBtn: document.getElementById('lastPageBtn'),
    pageIndicator: document.getElementById('pageIndicator'),
    // Modal elements
    detailModal: document.getElementById('detailModal'),
    closeModalBtn: document.getElementById('closeModalBtn'),
    modalPreviewImg: document.getElementById('modalPreviewImg'),
    modalFileName: document.getElementById('modalFileName'),
    modalCategoryBadge: document.getElementById('modalCategoryBadge'),
    modalStatusBadge: document.getElementById('modalStatusBadge'),
    modalFormatBadge: document.getElementById('modalFormatBadge'),
    modalDetailId: document.getElementById('modalDetailId'),
    modalDetailDims: document.getElementById('modalDetailDims'),
    modalDetailSize: document.getElementById('modalDetailSize'),
    modalDetailDateTaken: document.getElementById('modalDetailDateTaken'),
    modalDetailDateModified: document.getElementById('modalDetailDateModified'),
    modalPrevBtn: document.getElementById('modalPrevBtn'),
    modalNextBtn: document.getElementById('modalNextBtn'),
    modalPosition: document.getElementById('modalPosition'),
  };

  // Helper: Escape HTML to prevent XSS
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Helper: Format byte sizes
  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    if (!bytes) return '-';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  // Helper: Format date string
  function formatDate(isoString) {
    if (!isoString) return 'None';
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  }

  // Check Backend Health
  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('Health check failed');
      const data = await res.json();
      elements.connectionStatus.className = 'status-pill status-ok';
      elements.connectionText.textContent = 'Connected';
    } catch (err) {
      elements.connectionStatus.className = 'status-pill status-error';
      elements.connectionText.textContent = 'Offline';
    }
  }

  // Load Active Categories
  async function loadCategories() {
    try {
      const res = await fetch('/api/categories');
      if (!res.ok) throw new Error('Failed to load categories');
      state.categories = await res.json();

      // Populate category dropdown
      elements.categoryFilter.innerHTML = '<option value="">All Categories</option>';
      state.categories.forEach((cat) => {
        const opt = document.createElement('option');
        opt.value = cat.id;
        opt.textContent = cat.display_name;
        elements.categoryFilter.appendChild(opt);
      });
    } catch (err) {
      console.error('Error fetching categories:', err);
    }
  }

  // Load Catalog Images
  async function loadImages() {
    state.isLoading = true;
    showLoading();

    const offset = (state.page - 1) * state.limit;
    const params = new URLSearchParams({
      limit: state.limit.toString(),
      offset: offset.toString(),
    });

    if (state.categoryId !== null && state.categoryId !== '') {
      params.append('category_id', state.categoryId);
    }
    if (state.status) {
      params.append('status', state.status);
    }
    if (state.searchQuery.trim()) {
      params.append('q', state.searchQuery.trim());
    }

    try {
      const res = await fetch(`/api/images?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }
      const data = await res.json();
      state.items = data.items || [];
      state.total = data.total || 0;

      // Update total catalog badge
      elements.totalImagesCount.textContent = state.total.toLocaleString();

      renderGallery();
      renderPagination();
    } catch (err) {
      console.error('Failed to load images:', err);
      showError(err.message || 'Error communicating with catalog server.');
    } finally {
      state.isLoading = false;
    }
  }

  // View States
  function showLoading() {
    elements.loadingState.style.display = 'flex';
    elements.errorState.style.display = 'none';
    elements.emptyState.style.display = 'none';
    elements.galleryGrid.style.display = 'none';
  }

  function showError(msg) {
    elements.loadingState.style.display = 'none';
    elements.errorState.style.display = 'flex';
    elements.errorMessage.textContent = msg;
    elements.emptyState.style.display = 'none';
    elements.galleryGrid.style.display = 'none';
  }

  function renderGallery() {
    elements.loadingState.style.display = 'none';
    elements.errorState.style.display = 'none';

    if (state.items.length === 0) {
      elements.emptyState.style.display = 'flex';
      elements.galleryGrid.style.display = 'none';
      return;
    }

    elements.emptyState.style.display = 'none';
    elements.galleryGrid.style.display = 'grid';
    elements.galleryGrid.innerHTML = '';

    state.items.forEach((item, index) => {
      const card = document.createElement('article');
      card.className = 'image-card';
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `View details for ${item.file_name}`);

      const dims = item.width && item.height ? `${item.width}×${item.height}` : 'Dimensions N/A';
      const categoryName = item.category_name || 'Uncategorized';
      const statusClass = item.status === 'needs_review' ? 'badge-status-needs_review' : 'badge-status';

      const thumbUrl = item.has_thumbnail ? `/api/images/${item.id}/thumbnail` : '';

      card.innerHTML = `
        <div class="card-thumb-wrapper">
          ${
            item.has_thumbnail
              ? `<img class="card-thumb-img" src="${thumbUrl}" alt="${escapeHtml(item.file_name)}" loading="lazy">`
              : `<span class="card-placeholder-icon">🖼️</span>`
          }
        </div>
        <div class="card-info">
          <div class="card-filename" title="${escapeHtml(item.file_name)}">${escapeHtml(item.file_name)}</div>
          <div class="card-meta-row">
            <span>${dims}</span>
            <span>${formatBytes(item.file_size)}</span>
          </div>
          <div class="card-badges">
            <span class="badge badge-category">${escapeHtml(categoryName)}</span>
            <span class="badge ${statusClass}">${escapeHtml(item.status)}</span>
            ${item.file_format ? `<span class="badge badge-format">${escapeHtml(item.file_format)}</span>` : ''}
          </div>
        </div>
      `;

      card.addEventListener('click', () => openModal(index));
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openModal(index);
        }
      });

      elements.galleryGrid.appendChild(card);
    });
  }

  function renderPagination() {
    const totalPages = Math.max(1, Math.ceil(state.total / state.limit));
    const startItem = state.total === 0 ? 0 : (state.page - 1) * state.limit + 1;
    const endItem = Math.min(state.page * state.limit, state.total);

    elements.paginationSummary.textContent = `Showing ${startItem}–${endItem} of ${state.total} images`;
    elements.pageIndicator.textContent = `Page ${state.page} of ${totalPages}`;

    elements.firstPageBtn.disabled = state.page <= 1;
    elements.prevPageBtn.disabled = state.page <= 1;
    elements.nextPageBtn.disabled = state.page >= totalPages;
    elements.lastPageBtn.disabled = state.page >= totalPages;
  }

  // Modal Functions
  function openModal(index) {
    if (index < 0 || index >= state.items.length) return;
    state.selectedModalIndex = index;
    updateModalContent();
    elements.detailModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    elements.detailModal.style.display = 'none';
    document.body.style.overflow = '';
    state.selectedModalIndex = -1;
  }

  function updateModalContent() {
    const item = state.items[state.selectedModalIndex];
    if (!item) return;

    elements.modalFileName.textContent = item.file_name;
    elements.modalPreviewImg.src = item.has_thumbnail ? `/api/images/${item.id}/thumbnail` : '';
    elements.modalPreviewImg.alt = item.file_name;

    elements.modalCategoryBadge.textContent = item.category_name || 'Uncategorized';
    elements.modalStatusBadge.textContent = item.status;
    elements.modalFormatBadge.textContent = item.file_format || 'N/A';

    elements.modalDetailId.textContent = `#${item.id}`;
    elements.modalDetailDims.textContent = item.width && item.height ? `${item.width} × ${item.height} px` : 'Unknown';
    elements.modalDetailSize.textContent = `${formatBytes(item.file_size)} (${item.file_size.toLocaleString()} bytes)`;
    elements.modalDetailDateTaken.textContent = formatDate(item.date_taken);
    elements.modalDetailDateModified.textContent = formatDate(item.date_modified);

    elements.modalPosition.textContent = `${state.selectedModalIndex + 1} / ${state.items.length}`;
    elements.modalPrevBtn.disabled = state.selectedModalIndex <= 0;
    elements.modalNextBtn.disabled = state.selectedModalIndex >= state.items.length - 1;
  }

  function showNextModalItem() {
    if (state.selectedModalIndex < state.items.length - 1) {
      state.selectedModalIndex++;
      updateModalContent();
    }
  }

  function showPrevModalItem() {
    if (state.selectedModalIndex > 0) {
      state.selectedModalIndex--;
      updateModalContent();
    }
  }

  // Event Listeners Setup
  function setupEventListeners() {
    // Search with debounce
    let searchTimeout = null;
    elements.searchInput.addEventListener('input', (e) => {
      const val = e.target.value;
      elements.clearSearchBtn.style.display = val ? 'inline-block' : 'none';
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        state.searchQuery = val;
        state.page = 1;
        loadImages();
      }, 300);
    });

    elements.clearSearchBtn.addEventListener('click', () => {
      elements.searchInput.value = '';
      elements.clearSearchBtn.style.display = 'none';
      state.searchQuery = '';
      state.page = 1;
      loadImages();
    });

    // Category filter
    elements.categoryFilter.addEventListener('change', (e) => {
      state.categoryId = e.target.value || null;
      state.page = 1;
      loadImages();
    });

    // Status filter
    elements.statusFilter.addEventListener('change', (e) => {
      state.status = e.target.value || null;
      state.page = 1;
      loadImages();
    });

    // Page size change
    elements.pageSizeSelect.addEventListener('change', (e) => {
      state.limit = parseInt(e.target.value, 10) || 24;
      state.page = 1;
      loadImages();
    });

    // Refresh & Retry buttons
    elements.refreshBtn.addEventListener('click', () => loadImages());
    elements.retryBtn.addEventListener('click', () => {
      checkHealth();
      loadCategories();
      loadImages();
    });

    // Reset filters from empty state
    elements.resetFiltersBtn.addEventListener('click', () => {
      state.categoryId = null;
      state.status = null;
      state.searchQuery = '';
      state.page = 1;
      elements.categoryFilter.value = '';
      elements.statusFilter.value = '';
      elements.searchInput.value = '';
      elements.clearSearchBtn.style.display = 'none';
      loadImages();
    });

    // Pagination buttons
    elements.firstPageBtn.addEventListener('click', () => {
      state.page = 1;
      loadImages();
    });
    elements.prevPageBtn.addEventListener('click', () => {
      if (state.page > 1) {
        state.page--;
        loadImages();
      }
    });
    elements.nextPageBtn.addEventListener('click', () => {
      const totalPages = Math.ceil(state.total / state.limit);
      if (state.page < totalPages) {
        state.page++;
        loadImages();
      }
    });
    elements.lastPageBtn.addEventListener('click', () => {
      const totalPages = Math.ceil(state.total / state.limit);
      state.page = totalPages;
      loadImages();
    });

    // Modal events
    elements.closeModalBtn.addEventListener('click', closeModal);
    elements.detailModal.addEventListener('click', (e) => {
      if (e.target === elements.detailModal) closeModal();
    });
    elements.modalPrevBtn.addEventListener('click', showPrevModalItem);
    elements.modalNextBtn.addEventListener('click', showNextModalItem);

    // Keyboard navigation
    window.addEventListener('keydown', (e) => {
      if (elements.detailModal.style.display === 'flex') {
        if (e.key === 'Escape') closeModal();
        if (e.key === 'ArrowLeft') showPrevModalItem();
        if (e.key === 'ArrowRight') showNextModalItem();
      }
    });
  }

  // Initialization
  async function init() {
    setupEventListeners();
    await checkHealth();
    await loadCategories();
    await loadImages();
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
