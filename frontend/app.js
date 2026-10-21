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
    // Organizer Workflow State
    sourcePath: '',
    destPath: '',
    currentPlan: null,
    isScanning: false,
    isClassifying: false,
    isOrganizing: false,
  };

  // DOM Elements
  const elements = {
    // Header
    connectionStatus: document.getElementById('connectionStatus'),
    connectionText: document.getElementById('connectionText'),
    totalImagesCount: document.getElementById('totalImagesCount'),
    clearCatalogBtn: document.getElementById('clearCatalogBtn'),
    clearBeforeScanCheck: document.getElementById('clearBeforeScanCheck'),

    // Workflow Elements
    sourceFolderInput: document.getElementById('sourceFolderInput'),
    destFolderInput: document.getElementById('destFolderInput'),
    browseSourceBtn: document.getElementById('browseSourceBtn'),
    browseDestBtn: document.getElementById('browseDestBtn'),
    sourceValidationMsg: document.getElementById('sourceValidationMsg'),
    destValidationMsg: document.getElementById('destValidationMsg'),

    startScanBtn: document.getElementById('startScanBtn'),
    startClassifyBtn: document.getElementById('startClassifyBtn'),
    previewPlanBtn: document.getElementById('previewPlanBtn'),
    executeOrganizeBtn: document.getElementById('executeOrganizeBtn'),
    openExplorerBtn: document.getElementById('openExplorerBtn'),

    workflowProgressCard: document.getElementById('workflowProgressCard'),
    progressTitle: document.getElementById('progressTitle'),
    progressPercentage: document.getElementById('progressPercentage'),
    progressBarFill: document.getElementById('progressBarFill'),
    progressDetail: document.getElementById('progressDetail'),

    // Toolbar & Filters
    searchInput: document.getElementById('searchInput'),
    clearSearchBtn: document.getElementById('clearSearchBtn'),
    categoryFilter: document.getElementById('categoryFilter'),
    statusFilter: document.getElementById('statusFilter'),
    pageSizeSelect: document.getElementById('pageSizeSelect'),
    refreshBtn: document.getElementById('refreshBtn'),

    // Gallery View
    galleryGrid: document.getElementById('galleryGrid'),
    loadingState: document.getElementById('loadingState'),
    errorState: document.getElementById('errorState'),
    errorMessage: document.getElementById('errorMessage'),
    emptyState: document.getElementById('emptyState'),
    retryBtn: document.getElementById('retryBtn'),
    resetFiltersBtn: document.getElementById('resetFiltersBtn'),

    // Pagination
    paginationSummary: document.getElementById('paginationSummary'),
    firstPageBtn: document.getElementById('firstPageBtn'),
    prevPageBtn: document.getElementById('prevPageBtn'),
    nextPageBtn: document.getElementById('nextPageBtn'),
    lastPageBtn: document.getElementById('lastPageBtn'),
    pageIndicator: document.getElementById('pageIndicator'),

    // Dry-Run Preview Modal
    previewModal: document.getElementById('previewModal'),
    closePreviewModalBtn: document.getElementById('closePreviewModalBtn'),
    cancelPreviewBtn: document.getElementById('cancelPreviewBtn'),
    confirmOrganizeBtn: document.getElementById('confirmOrganizeBtn'),
    planFilesCount: document.getElementById('planFilesCount'),
    planTotalBytes: document.getElementById('planTotalBytes'),
    planCollisionsCount: document.getElementById('planCollisionsCount'),
    previewTableBody: document.getElementById('previewTableBody'),

    // Detail & Review Modal
    detailModal: document.getElementById('detailModal'),
    closeModalBtn: document.getElementById('closeModalBtn'),
    modalPreviewImg: document.getElementById('modalPreviewImg'),
    modalFileName: document.getElementById('modalFileName'),
    modalCategoryBadge: document.getElementById('modalCategoryBadge'),
    modalStatusBadge: document.getElementById('modalStatusBadge'),
    modalFormatBadge: document.getElementById('modalFormatBadge'),
    modalCategorySelect: document.getElementById('modalCategorySelect'),
    modalProposedNameInput: document.getElementById('modalProposedNameInput'),
    modalSaveNameBtn: document.getElementById('modalSaveNameBtn'),
    modalRenameMsg: document.getElementById('modalRenameMsg'),
    modalVisualDesc: document.getElementById('modalVisualDesc'),
    modalApproveBtn: document.getElementById('modalApproveBtn'),
    modalDetailId: document.getElementById('modalDetailId'),
    modalDetailDims: document.getElementById('modalDetailDims'),
    modalDetailSize: document.getElementById('modalDetailSize'),
    modalDetailDateTaken: document.getElementById('modalDetailDateTaken'),
    modalDetailDateModified: document.getElementById('modalDetailDateModified'),
    modalPrevBtn: document.getElementById('modalPrevBtn'),
    modalNextBtn: document.getElementById('modalNextBtn'),
    modalPosition: document.getElementById('modalPosition'),
  };

  // Helper: Escape HTML
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

  // --- Backend Communication ---

  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('Health check failed');
      elements.connectionStatus.className = 'status-pill status-ok';
      elements.connectionText.textContent = 'Connected';
    } catch (err) {
      elements.connectionStatus.className = 'status-pill status-error';
      elements.connectionText.textContent = 'Offline';
    }
  }

  async function loadCategories() {
    try {
      const res = await fetch('/api/categories');
      if (!res.ok) throw new Error('Failed to load categories');
      state.categories = await res.json();

      // Populate filter dropdown
      elements.categoryFilter.innerHTML = '<option value="">All Categories</option>';
      elements.modalCategorySelect.innerHTML = '';

      state.categories.forEach((cat) => {
        const opt = document.createElement('option');
        opt.value = cat.id;
        opt.textContent = cat.display_name;
        elements.categoryFilter.appendChild(opt);

        const modalOpt = document.createElement('option');
        modalOpt.value = cat.id;
        modalOpt.textContent = cat.display_name;
        elements.modalCategorySelect.appendChild(modalOpt);
      });
    } catch (err) {
      console.error('Error fetching categories:', err);
    }
  }

  // Folder Validation
  async function validateFolder(path, mustExist = true) {
    if (!path.trim()) return { valid: false, error: 'Path is required' };
    try {
      const res = await fetch('/api/folders/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: path.trim(), must_exist: mustExist }),
      });
      return await res.json();
    } catch (err) {
      return { valid: false, error: err.message };
    }
  }

  async function handleSourceFolderChange() {
    const val = elements.sourceFolderInput.value.trim();
    state.sourcePath = val;
    if (!val) {
      elements.sourceValidationMsg.textContent = '';
      return;
    }
    const res = await validateFolder(val, true);
    if (res.valid) {
      elements.sourceValidationMsg.className = 'validation-msg valid';
      elements.sourceValidationMsg.textContent = `✓ Valid folder: ${res.resolved_path}`;
      elements.startScanBtn.disabled = false;
    } else {
      elements.sourceValidationMsg.className = 'validation-msg invalid';
      elements.sourceValidationMsg.textContent = `✗ ${res.error || 'Invalid folder'}`;
    }
  }

  async function handleDestFolderChange() {
    const val = elements.destFolderInput.value.trim();
    state.destPath = val;
    if (!val) {
      elements.destValidationMsg.textContent = '';
      elements.openExplorerBtn.disabled = true;
      return;
    }
    const res = await validateFolder(val, false);
    if (res.valid) {
      elements.destValidationMsg.className = 'validation-msg valid';
      elements.destValidationMsg.textContent = `✓ Destination ready: ${res.resolved_path}`;
      elements.previewPlanBtn.disabled = false;
      elements.openExplorerBtn.disabled = false;
    } else {
      elements.destValidationMsg.className = 'validation-msg invalid';
      elements.destValidationMsg.textContent = `✗ ${res.error || 'Invalid path'}`;
    }
  }

  // Native Browse Calls
  async function browseFolder(isSource) {
    try {
      const res = await fetch('/api/folders/browse', { method: 'POST' });
      const data = await res.json();
      if (data.folder_path) {
        if (isSource) {
          elements.sourceFolderInput.value = data.folder_path;
          handleSourceFolderChange();
        } else {
          elements.destFolderInput.value = data.folder_path;
          handleDestFolderChange();
        }
      }
    } catch (err) {
      console.error('Browse error:', err);
    }
  }

  async function clearCatalog() {
    if (!confirm('Are you sure you want to clear the catalog? This will remove all scanned staging records so you can start clean. (Your original files on disk will NOT be touched).')) {
      return;
    }
    try {
      const res = await fetch('/api/catalog/clear', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to clear catalog');
      const data = await res.json();
      await loadImages();
      elements.workflowProgressCard.style.display = 'flex';
      elements.progressTitle.textContent = 'Catalog Cleared';
      elements.progressBarFill.style.width = '100%';
      elements.progressPercentage.textContent = '100%';
      elements.progressDetail.textContent = data.message || 'Catalog cleared successfully.';
    } catch (err) {
      alert(`Error clearing catalog: ${err.message}`);
    }
  }

  // Scanning Pipeline
  async function startScan() {
    const src = elements.sourceFolderInput.value.trim();
    if (!src) {
      alert('Please select a valid Source Folder first.');
      return;
    }

    if (elements.clearBeforeScanCheck && elements.clearBeforeScanCheck.checked) {
      try {
        await fetch('/api/catalog/clear', { method: 'POST' });
        await loadImages();
      } catch (e) {
        console.warn('Auto-clearing catalog before scan failed:', e);
      }
    }

    state.isScanning = true;
    elements.startScanBtn.disabled = true;
    elements.workflowProgressCard.style.display = 'flex';
    elements.progressTitle.textContent = 'Scanning Source Directory...';
    elements.progressBarFill.style.width = '10%';
    elements.progressPercentage.textContent = 'Scanning...';
    elements.progressDetail.textContent = `Starting traversal in ${src}`;

    try {
      const dest = elements.destFolderInput.value.trim();
      const res = await fetch('/api/scan/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_path: src, exclude_path: dest || null }),
      });
      if (!res.ok) throw new Error('Failed to initiate scan.');

      // Poll status
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetch('/api/scan/status');
          const status = await statusRes.json();

          if (status.total_found > 0) {
            const pct = Math.round((status.processed_count / status.total_found) * 100);
            elements.progressBarFill.style.width = `${Math.max(5, pct)}%`;
            elements.progressPercentage.textContent = `${pct}%`;
          }

          elements.progressDetail.textContent = `Processed ${status.processed_count} of ${status.total_found} images (${status.skipped_count} skipped, ${status.error_count} errors)`;

          if (status.is_complete || !status.is_running) {
            clearInterval(pollInterval);
            state.isScanning = false;
            elements.startScanBtn.disabled = false;
            elements.startClassifyBtn.disabled = false;
            elements.progressBarFill.style.width = '100%';
            elements.progressPercentage.textContent = '100%';
            elements.progressTitle.textContent = 'Scan Completed!';
            await loadImages();
          }
        } catch (pollErr) {
          clearInterval(pollInterval);
          state.isScanning = false;
          elements.startScanBtn.disabled = false;
        }
      }, 400);
    } catch (err) {
      alert(`Error starting scan: ${err.message}`);
      state.isScanning = false;
      elements.startScanBtn.disabled = false;
    }
  }

  // Classification Pipeline
  async function startClassification() {
    state.isClassifying = true;
    elements.startClassifyBtn.disabled = true;
    elements.workflowProgressCard.style.display = 'flex';
    elements.progressTitle.textContent = 'Running Local AI Classification...';
    elements.progressBarFill.style.width = '30%';
    elements.progressPercentage.textContent = 'Analyzing...';
    elements.progressDetail.textContent = 'Evaluating visual features and matching categories...';

    try {
      const res = await fetch('/api/classify/start', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Classification failed.');
      }

      if (data.total_processed === 0) {
        elements.progressBarFill.style.width = '100%';
        elements.progressPercentage.textContent = '100%';
        elements.progressTitle.textContent = 'Classification Check';
        elements.progressDetail.textContent = 'No unclassified images found in catalog. All images are already classified or organized.';
        return;
      }

      elements.progressBarFill.style.width = '100%';
      elements.progressPercentage.textContent = '100%';
      elements.progressTitle.textContent = 'Classification Complete!';
      elements.progressDetail.textContent = `Classified: ${data.classified_count} images | Needs Review: ${data.needs_review_count} images`;
      elements.previewPlanBtn.disabled = false;

      await loadImages();
    } catch (err) {
      alert(`Classification error: ${err.message}`);
    } finally {
      state.isClassifying = false;
      elements.startClassifyBtn.disabled = false;
    }
  }

  // Dry-Run Preview
  async function generatePreviewPlan() {
    const dest = elements.destFolderInput.value.trim();
    if (!dest) {
      alert('Please enter or browse a Destination Folder first.');
      return;
    }

    try {
      const res = await fetch('/api/organize/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination_dir: dest, include_needs_review: true }),
      });
      if (!res.ok) throw new Error('Failed to generate preview.');
      state.currentPlan = await res.json();

      elements.planFilesCount.textContent = state.currentPlan.total_files;
      elements.planTotalBytes.textContent = formatBytes(state.currentPlan.total_bytes);

      const collisions = state.currentPlan.items.filter((i) => i.collision_detected).length;
      elements.planCollisionsCount.textContent = collisions;

      elements.previewTableBody.innerHTML = '';
      state.currentPlan.items.forEach((item) => {
        const tr = document.createElement('tr');
        const catLabel = item.subcategory ? `${item.category_name} / ${item.subcategory}` : item.category_name;
        const visualSummary = item.visual_description || '-';
        tr.innerHTML = `
          <td title="${escapeHtml(item.source_path)}"><strong>${escapeHtml(item.original_filename || item.destination_filename)}</strong></td>
          <td style="font-size: 0.8rem; color: #4b5563;">${escapeHtml(visualSummary)}</td>
          <td><span class="badge badge-category">${escapeHtml(catLabel)}</span></td>
          <td style="font-family: monospace; font-size: 0.75rem;" title="${escapeHtml(item.destination_path)}">
            <strong style="color: #2563eb;">${escapeHtml(item.destination_filename)}</strong><br>
            <span style="color: #6b7280;">${escapeHtml(item.destination_path)}</span>
          </td>
          <td>${item.collision_detected ? '<span class="badge badge-status-needs_review">Collision Renamed (-2)</span>' : '<span class="badge badge-status">Ready</span>'}</td>
        `;
        elements.previewTableBody.appendChild(tr);
      });

      elements.previewModal.style.display = 'flex';
      elements.executeOrganizeBtn.disabled = false;
    } catch (err) {
      alert(`Preview error: ${err.message}`);
    }
  }

  // Execute Organize
  async function executeOrganize() {
    if (!state.currentPlan) return;
    elements.previewModal.style.display = 'none';

    state.isOrganizing = true;
    elements.executeOrganizeBtn.disabled = true;
    elements.workflowProgressCard.style.display = 'flex';
    elements.progressTitle.textContent = 'Copying & Verifying Files (shutil.copy2)...';
    elements.progressBarFill.style.width = '50%';
    elements.progressPercentage.textContent = 'Copying...';
    elements.progressDetail.textContent = 'Preserving originals, writing to destination, and verifying SHA-256...';

    try {
      const res = await fetch('/api/organize/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          destination_dir: state.currentPlan.destination_root,
          include_needs_review: true,
          auto_remove_organized: true,
        }),
      });
      if (!res.ok) throw new Error('Execution failed.');
      const result = await res.json();

      elements.progressBarFill.style.width = '100%';
      elements.progressPercentage.textContent = '100%';
      elements.progressTitle.textContent = 'Organization Successfully Completed!';
      elements.progressDetail.textContent = `✓ Copied: ${result.copied_count} files | Verified SHA-256: ${result.verified_count} | Successfully organized copies delivered & removed from staging catalog.`;

      elements.openExplorerBtn.disabled = false;
      await loadImages();
    } catch (err) {
      alert(`Organization execution error: ${err.message}`);
    } finally {
      state.isOrganizing = false;
      elements.executeOrganizeBtn.disabled = false;
    }
  }

  // Open in Windows File Explorer
  async function openInFileExplorer() {
    const dest = elements.destFolderInput.value.trim();
    if (!dest) {
      alert('Please specify a Destination Folder.');
      return;
    }
    try {
      const res = await fetch('/api/folders/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: dest }),
      });
      const data = await res.json();
      if (!data.success) {
        alert('Could not open folder in File Explorer.');
      }
    } catch (err) {
      alert(`Explorer error: ${err.message}`);
    }
  }

  async function saveModalProposedName() {
    const item = state.items[state.selectedModalIndex];
    if (!item) return;

    const newName = elements.modalProposedNameInput.value.trim();
    if (!newName) {
      elements.modalRenameMsg.className = 'validation-msg invalid';
      elements.modalRenameMsg.textContent = 'Filename cannot be blank.';
      return;
    }

    try {
      const res = await fetch(`/api/images/${item.id}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposed_filename: newName }),
      });
      if (!res.ok) throw new Error('Failed to update filename');
      const data = await res.json();

      item.proposed_filename = data.proposed_filename;
      elements.modalProposedNameInput.value = data.proposed_filename;
      elements.modalRenameMsg.className = 'validation-msg valid';
      elements.modalRenameMsg.textContent = `✓ Renamed to: ${data.proposed_filename}`;
      renderGallery();
    } catch (err) {
      elements.modalRenameMsg.className = 'validation-msg invalid';
      elements.modalRenameMsg.textContent = `✗ ${err.message}`;
    }
  }

  // Approve / Change Category in Modal
  async function approveCurrentModalImage() {
    const item = state.items[state.selectedModalIndex];
    if (!item) return;

    const chosenCatId = parseInt(elements.modalCategorySelect.value, 10);
    try {
      const res = await fetch(`/api/images/${item.id}/category`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: chosenCatId, approve: true }),
      });
      if (!res.ok) throw new Error('Failed to update category');

      item.status = 'approved';
      const catObj = state.categories.find((c) => c.id === chosenCatId);
      if (catObj) item.category_name = catObj.display_name;

      updateModalContent();
      renderGallery();
    } catch (err) {
      alert(`Error approving category: ${err.message}`);
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
      if (!res.ok) throw new Error(`Server returned HTTP ${res.status}`);
      const data = await res.json();
      state.items = data.items || [];
      state.total = data.total || 0;

      elements.totalImagesCount.textContent = state.total.toLocaleString();
      renderGallery();
      renderPagination();
    } catch (err) {
      showError(err.message || 'Error communicating with catalog server.');
    } finally {
      state.isLoading = false;
    }
  }

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
          <div class="card-filename" title="${escapeHtml(item.proposed_filename || item.file_name)}">${escapeHtml(item.proposed_filename || item.file_name)}</div>
          ${item.proposed_filename && item.proposed_filename !== item.file_name ? `<div class="card-orig-filename" title="Original: ${escapeHtml(item.file_name)}">Orig: ${escapeHtml(item.file_name)}</div>` : ''}
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
    if (elements.modalProposedNameInput) {
      elements.modalProposedNameInput.value = item.proposed_filename || item.file_name;
    }
    if (elements.modalVisualDesc) {
      elements.modalVisualDesc.textContent = item.visual_description || 'Analysis pending classification';
    }
    if (elements.modalRenameMsg) {
      elements.modalRenameMsg.textContent = '';
    }

    // Set matching select option if available
    if (item.category_name) {
      const match = state.categories.find((c) => c.display_name === item.category_name);
      if (match) elements.modalCategorySelect.value = match.id;
    }

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
    // Folder inputs & browse
    elements.sourceFolderInput.addEventListener('change', handleSourceFolderChange);
    elements.destFolderInput.addEventListener('change', handleDestFolderChange);
    elements.browseSourceBtn.addEventListener('click', () => browseFolder(true));
    elements.browseDestBtn.addEventListener('click', () => browseFolder(false));
    if (elements.clearCatalogBtn) {
      elements.clearCatalogBtn.addEventListener('click', clearCatalog);
    }

    // Pipeline actions
    elements.startScanBtn.addEventListener('click', startScan);
    elements.startClassifyBtn.addEventListener('click', startClassification);
    elements.previewPlanBtn.addEventListener('click', generatePreviewPlan);
    elements.executeOrganizeBtn.addEventListener('click', executeOrganize);
    elements.confirmOrganizeBtn.addEventListener('click', executeOrganize);
    elements.openExplorerBtn.addEventListener('click', openInFileExplorer);

    // Preview Modal events
    elements.closePreviewModalBtn.addEventListener('click', () => {
      elements.previewModal.style.display = 'none';
    });
    elements.cancelPreviewBtn.addEventListener('click', () => {
      elements.previewModal.style.display = 'none';
    });

    // Review Modal Approve
    elements.modalApproveBtn.addEventListener('click', approveCurrentModalImage);
    if (elements.modalSaveNameBtn) {
      elements.modalSaveNameBtn.addEventListener('click', saveModalProposedName);
    }

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

    // Filters
    elements.categoryFilter.addEventListener('change', (e) => {
      state.categoryId = e.target.value || null;
      state.page = 1;
      loadImages();
    });

    elements.statusFilter.addEventListener('change', (e) => {
      state.status = e.target.value || null;
      state.page = 1;
      loadImages();
    });

    elements.pageSizeSelect.addEventListener('change', (e) => {
      state.limit = parseInt(e.target.value, 10) || 24;
      state.page = 1;
      loadImages();
    });

    elements.refreshBtn.addEventListener('click', () => loadImages());
    elements.retryBtn.addEventListener('click', () => {
      checkHealth();
      loadCategories();
      loadImages();
    });

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

    // Modal controls
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
      if (elements.previewModal.style.display === 'flex') {
        if (e.key === 'Escape') elements.previewModal.style.display = 'none';
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
