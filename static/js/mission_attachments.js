/**
 * Mission Attachments Manager
 * Handles file uploads, attachment display, and management for mission forms
 */

class MissionAttachmentsManager {
    constructor(missionId) {
        this.missionId = missionId;
        this.selectedFiles = [];
        this.modal = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadAttachments();
    }

    setupEventListeners() {
        // Set up upload button handler
        const uploadButton = document.getElementById('upload-attachment-btn');
        if (uploadButton) {
            uploadButton.addEventListener('click', (e) => this.openUploadModal(e));
        }

        // Set up refresh button handler
        const refreshButton = document.getElementById('refresh-attachments-btn');
        if (refreshButton) {
            refreshButton.addEventListener('click', () => this.loadAttachments());
        }

        // Set up drag and drop file handling
        this.setupDragAndDrop();

        // Set up file input change handler
        const fileInput = document.getElementById('attachmentFile');
        if (fileInput) {
            fileInput.addEventListener('change', () => this.handleFileSelection());
        }

        // Set up clear files button
        const clearFilesBtn = document.getElementById('clearFilesBtn');
        if (clearFilesBtn) {
            clearFilesBtn.addEventListener('click', (e) => this.resetFileInput(e));
        }

        // Set up submit upload button
        const submitUploadBtn = document.getElementById('submitUpload');
        if (submitUploadBtn) {
            submitUploadBtn.addEventListener('click', () => this.submitAttachmentUpload());
        }

        // Set up modal close handlers
        this.setupModalCloseHandlers();
    }

    setupDragAndDrop() {
        const fileDropArea = document.getElementById('fileDrop');
        if (!fileDropArea) return;

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            fileDropArea.addEventListener(eventName, this.preventDefaults, false);
            document.body.addEventListener(eventName, this.preventDefaults, false);
        });

        // Highlight drop area when drag over it
        ['dragenter', 'dragover'].forEach(eventName => {
            fileDropArea.addEventListener(eventName, () => {
                fileDropArea.classList.add('dragover');
            }, false);
        });

        // Remove highlight when drag leaves
        ['dragleave', 'drop'].forEach(eventName => {
            fileDropArea.addEventListener(eventName, () => {
                fileDropArea.classList.remove('dragover');
            }, false);
        });

        // Handle dropped files
        fileDropArea.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = Array.from(dt.files);

            if (files.length > 0) {
                this.selectedFiles = this.selectedFiles.concat(files);
                this.updateFileDisplay();
                const fileInput = document.getElementById('attachmentFile');
                if (fileInput) fileInput.value = '';
            }
        }, false);
    }

    setupModalCloseHandlers() {
        const modalElement = document.getElementById('uploadModal');
        if (!modalElement) return;

        // Handle close button clicks
        const closeButtons = modalElement.querySelectorAll('[data-bs-dismiss="modal"]');
        closeButtons.forEach(btn => {
            btn.addEventListener('click', () => this.closeUploadModal());
        });

        // Handle clicking outside modal
        modalElement.addEventListener('click', (event) => {
            if (event.target === modalElement) {
                this.closeUploadModal();
            }
        });
    }

    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    openUploadModal(event) {
        console.log("Opening upload modal");

        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        try {
            const modalElement = document.getElementById('uploadModal');
            if (!modalElement) {
                console.error("Modal element not found");
                this.showFlashMessage("Error: Upload modal not found", 'error');
                return false;
            }

            // Reset form and state
            this.resetUploadForm();

            // Show modal using Bootstrap if available, otherwise fallback to direct DOM manipulation
            if (typeof bootstrap !== 'undefined') {
                this.modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                this.modal.show();
            } else {
                this.showModalFallback(modalElement);
            }

            return false;
        } catch (err) {
            console.error("Error opening upload modal:", err);
            this.showFlashMessage("Error opening upload dialog", 'error');
            return false;
        }
    }

    closeUploadModal() {
        const modalElement = document.getElementById('uploadModal');
        if (!modalElement) return;

        if (this.modal && typeof bootstrap !== 'undefined') {
            this.modal.hide();
        } else {
            this.hideModalFallback(modalElement);
        }

        this.resetUploadForm();
    }

    showModalFallback(modalElement) {
        modalElement.style.display = 'block';
        modalElement.classList.add('show');
        document.body.classList.add('modal-open');

        // Add backdrop
        let backdrop = document.querySelector('.modal-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            document.body.appendChild(backdrop);
        }
    }

    hideModalFallback(modalElement) {
        modalElement.style.display = 'none';
        modalElement.classList.remove('show');
        document.body.classList.remove('modal-open');

        const backdrop = document.querySelector('.modal-backdrop');
        if (backdrop) {
            document.body.removeChild(backdrop);
        }
    }

    resetUploadForm() {
        // Clear selected files
        this.selectedFiles = [];

        // Reset form
        const form = document.getElementById('uploadForm');
        if (form) {
            form.reset();
        }

        // Reset file display
        const fileDropArea = document.getElementById('fileDrop');
        const selectedFileInfo = document.getElementById('selectedFileInfo');
        const selectedFileName = document.getElementById('selectedFileName');

        if (fileDropArea) fileDropArea.style.display = 'block';
        if (selectedFileInfo) selectedFileInfo.style.display = 'none';
        if (selectedFileName) selectedFileName.textContent = '';

        // Clear error message
        const errorElement = document.getElementById('uploadError');
        if (errorElement) {
            errorElement.style.display = 'none';
        }

        // Remove any progress elements
        const progressElements = form ? form.querySelectorAll('.progress, .status-updates') : [];
        progressElements.forEach(el => el.remove());
    }

    handleFileSelection() {
        const fileInput = document.getElementById('attachmentFile');
        if (fileInput && fileInput.files.length > 0) {
            this.selectedFiles = this.selectedFiles.concat(Array.from(fileInput.files));
            this.updateFileDisplay();
            fileInput.value = '';
        }
    }

    updateFileDisplay() {
        const selectedFileInfo = document.getElementById('selectedFileInfo');
        const selectedFileName = document.getElementById('selectedFileName');

        if (selectedFileInfo && selectedFileName) {
            const names = this.selectedFiles.map(f => f.name).join('<br>');
            selectedFileName.innerHTML = names;
            selectedFileInfo.style.display = this.selectedFiles.length > 0 ? 'flex' : 'none';

            // Auto-fill title from filename when a single file is selected
            const titleInput = document.getElementById('attachmentTitle');
            if (titleInput && !titleInput.value && this.selectedFiles.length === 1) {
                const fileName = this.selectedFiles[0].name.split('.');
                fileName.pop();
                titleInput.value = fileName.join('.');
            }
        }
    }

    resetFileInput(event) {
        if (event) {
            event.preventDefault();
        }

        const fileInput = document.getElementById('attachmentFile');
        if (fileInput) {
            fileInput.value = '';
        }

        this.selectedFiles = [];
        
        const fileDropArea = document.getElementById('fileDrop');
        const selectedFileInfo = document.getElementById('selectedFileInfo');
        const selectedFileName = document.getElementById('selectedFileName');

        if (fileDropArea) fileDropArea.style.display = 'block';
        if (selectedFileInfo) selectedFileInfo.style.display = 'none';
        if (selectedFileName) selectedFileName.textContent = '';
    }

    async submitAttachmentUpload() {
        const form = document.getElementById('uploadForm');
        const errorElement = document.getElementById('uploadError');

        // Clear previous error
        if (errorElement) {
            errorElement.style.display = 'none';
        }

        if (!this.selectedFiles || this.selectedFiles.length === 0) {
            if (errorElement) {
                errorElement.textContent = 'Please select at least one file to upload';
                errorElement.style.display = 'block';
            }
            return;
        }

        const submitButton = document.getElementById('submitUpload');
        const originalText = submitButton.textContent;
        
        // Show loading state
        this.setUploadButtonLoading(submitButton, true);

        // Create progress indicators
        const progressElement = this.createProgressElement();
        const statusElement = this.createStatusElement();
        
        if (form) {
            form.appendChild(progressElement);
            form.appendChild(statusElement);
        }

        try {
            await this.uploadFiles(progressElement, statusElement);
            
            // Success - close modal and refresh attachments
            this.showFlashMessage('Files uploaded successfully to Synack API and ready for submission!', 'success');
            this.closeUploadModal();
            this.loadAttachments();
            
            // Extra delay to ensure backend has finished writing files
            setTimeout(() => this.loadAttachments(), 1000);
            
        } catch (error) {
            console.error('Upload error:', error);
            if (errorElement) {
                errorElement.textContent = error.message || 'Upload failed';
                errorElement.style.display = 'block';
            }
            
            // Remove progress elements on error
            if (form) {
                const progressElements = form.querySelectorAll('.progress, .status-updates');
                progressElements.forEach(el => el.remove());
            }
        } finally {
            this.setUploadButtonLoading(submitButton, false, originalText);
        }
    }

    setUploadButtonLoading(button, isLoading, originalText = '') {
        if (isLoading) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Uploading...';
        } else {
            button.disabled = false;
            button.textContent = originalText || 'Upload';
        }
    }

    createProgressElement() {
        const progressElement = document.createElement('div');
        progressElement.className = 'progress mt-3';
        progressElement.innerHTML = `<div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width: 0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">0%</div>`;
        return progressElement;
    }

    createStatusElement() {
        const statusElement = document.createElement('div');
        statusElement.className = 'status-updates mt-2';
        return statusElement;
    }

    updateStatus(statusElement, message) {
        statusElement.innerHTML += `<div>${message}</div>`;
        statusElement.scrollTop = statusElement.scrollHeight;
    }

    updateProgress(progressElement, percent) {
        const progressBar = progressElement.querySelector('.progress-bar');
        if (progressBar) {
            progressBar.style.width = `${percent}%`;
            progressBar.setAttribute('aria-valuenow', percent);
            progressBar.textContent = `${percent}%`;
        }
    }

    async uploadFiles(progressElement, statusElement) {
        const formData = new FormData();
        formData.append('mission_id', this.missionId);
        formData.append('title', document.getElementById('attachmentTitle').value);
        formData.append('description', document.getElementById('attachmentDescription').value);
        
        this.selectedFiles.forEach(file => formData.append('file', file));

        this.updateStatus(statusElement, `Uploading ${this.selectedFiles.length} file(s) to local storage...`);
        this.updateProgress(progressElement, 20);

        const response = await fetch('/upload_attachments', { 
            method: 'POST', 
            body: formData 
        });

        this.updateStatus(statusElement, `Processing uploads and syncing to Synack API...`);
        this.updateProgress(progressElement, 60);

        if (!response.ok) {
            if (response.status === 500) {
                this.updateStatus(statusElement, `❌ Server error (500) - likely API connection issue`);
                throw new Error('Server error - check Synack API connection');
            } else if (response.status === 401) {
                this.updateStatus(statusElement, `❌ Authentication failed - check API credentials`);
                throw new Error('Authentication failed - check your Synack API credentials');
            } else {
                this.updateStatus(statusElement, `❌ Upload failed with status ${response.status}`);
                throw new Error(`Upload failed with status ${response.status}`);
            }
        }

        const data = await response.json();
        this.updateProgress(progressElement, 80);

        if (!data.success) {
            this.updateStatus(statusElement, `Error uploading files`);
            
            // Check if this is an API-related error that requires special handling
            if (data.api_error) {
                if (data.error_type === 'api_upload_failed') {
                    this.updateStatus(statusElement, `❌ Synack API upload failed - upload cancelled`);
                    throw new Error(data.message || 'Failed to upload to Synack API - required for submission');
                } else if (data.error_type === 'api_connection_failed') {
                    this.updateStatus(statusElement, `❌ Cannot connect to Synack API - check your connection`);
                    throw new Error(data.message || 'Cannot connect to Synack API - check your connection and credentials');
                } else {
                    this.updateStatus(statusElement, `❌ API error occurred`);
                    throw new Error(data.message || 'API error occurred');
                }
            }
            
            throw new Error(data.message || 'Upload failed');
        }

        // Update status for each uploaded file
        data.files.forEach(f => {
            this.updateStatus(statusElement, `✅ ${f.original_filename || f.filename} uploaded to Synack API`);
        });

        this.updateStatus(statusElement, `🎉 All files successfully uploaded and ready for submission!`);
        this.updateProgress(progressElement, 100);
    }

    async loadAttachments() {
        console.log(`Loading attachments for mission: ${this.missionId}`);

        const attachmentsContainer = document.getElementById('attachmentsList');
        if (!attachmentsContainer) {
            console.error('Attachments container not found');
            return;
        }

        // Show loading state
        attachmentsContainer.innerHTML = '<div class="loading-spinner">Loading attachments...</div>';

        try {
            // Make API request with cache buster
            const ts = Date.now();
            const response = await fetch(`/mission/${this.missionId}/attachments?ts=${ts}`);
            const data = await response.json();

            console.log("Attachments data:", data);

            if (data.success) {
                const attachments = data.attachments || [];
                this.renderAttachments(attachments, attachmentsContainer);
            } else {
                attachmentsContainer.innerHTML = `<div class="error-message">Error loading attachments: ${data.message || 'Unknown error'}</div>`;
                console.error("Error loading attachments:", data.message);
            }
        } catch (error) {
            console.error('Error fetching attachments:', error);
            attachmentsContainer.innerHTML = '<div class="error-message">Failed to load attachments. Please try refreshing.</div>';
        }
    }

    renderAttachments(attachments, container) {
        // Clear container
        container.innerHTML = '';

        if (attachments.length === 0) {
            container.innerHTML = '<div class="empty-state">No attachments</div>';
            return;
        }

        // Group attachments by title and description
        const groups = {};
        attachments.forEach(att => {
            const key = `${att.title || ''}|${att.description || ''}`;
            if (!groups[key]) {
                groups[key] = { title: att.title, description: att.description, items: [] };
            }
            groups[key].items.push(att);
        });

        Object.values(groups).forEach(group => {
            container.innerHTML += this.renderAttachmentGroup(group);
        });

        // Update count
        const countElement = document.getElementById('attachmentsCount');
        if (countElement) {
            countElement.textContent = attachments.length;
        }

        console.log(`Loaded ${attachments.length} attachments`);
    }

    renderAttachmentGroup(group) {
        let html = `<div class="attachment-group">`;
        html += `<div class="attachment-group-title">${group.title || 'Untitled'}</div>`;
        if (group.description) {
            html += `<div class="attachment-group-description">${group.description}</div>`;
        }
        html += `<div class="attachment-group-items">`;
        group.items.forEach(item => {
            html += this.renderAttachmentItem(item);
        });
        html += `</div></div>`;
        return html;
    }

    renderAttachmentItem(attachment) {
        const downloadUrl = `/mission/${this.missionId}/download_attachment/${attachment.id}`;
        return `
            <div class="attachment-item" data-id="${attachment.id}">
                <div class="attachment-preview">
                    <img src="${attachment.url}" alt="${attachment.title}" />
                </div>
                <div class="attachment-info">
                    ${attachment.uploaded_to_api ? '<span class="api-badge">API</span>' : ''}
                </div>
                <div class="attachment-actions">
                    <a href="${downloadUrl}" class="btn btn-sm btn-outline-primary download-btn" title="Download attachment">
                        <i class="fas fa-download"></i>
                    </a>
                    <button type="button" class="btn btn-sm btn-outline-danger delete-btn" onclick="window.attachmentsManager.deleteAttachment('${attachment.id}', event)" title="Delete attachment">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>`;
    }

    async deleteAttachment(attachmentId, event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }

        if (!confirm('Are you sure you want to delete this attachment? This will remove it from both your local storage and the Synack platform.')) {
            return;
        }

        console.log(`Deleting attachment ${attachmentId} from mission ${this.missionId}`);

        // Show loading state
        this.showFlashMessage('Deleting attachment...', 'info');

        try {
            const response = await fetch(`/mission/${this.missionId}/delete_attachment/${attachmentId}`, {
                method: 'DELETE'
            });

            const data = await response.json();
            console.log('Delete response:', data);

            if (data.success) {
                this.showFlashMessage('Attachment deleted successfully', 'success');

                // Remove the attachment from the UI
                const attachmentItem = document.querySelector(`.attachment-item[data-id="${attachmentId}"]`);
                if (attachmentItem) {
                    const groupContainer = attachmentItem.closest('.attachment-group');
                    attachmentItem.remove();
                    
                    // If the group has no more items remove the entire group
                    if (groupContainer && groupContainer.querySelectorAll('.attachment-item').length === 0) {
                        groupContainer.remove();
                    }

                    // Update attachment count if displayed
                    const countElement = document.getElementById('attachmentsCount');
                    if (countElement) {
                        const currentCount = parseInt(countElement.textContent) || 0;
                        countElement.textContent = Math.max(0, currentCount - 1);
                    }
                }

                // Reload attachments list
                this.loadAttachments();
            } else {
                this.showFlashMessage(`Failed to delete attachment: ${data.message}`, 'error');
            }
        } catch (error) {
            console.error('Error deleting attachment:', error);
            this.showFlashMessage('An error occurred while deleting the attachment', 'error');
        }

        return false;
    }

    showFlashMessage(message, type = 'info') {
        // Check if global showFlashMessage function exists, otherwise create our own
        if (typeof window.showFlashMessage === 'function') {
            window.showFlashMessage(message, type);
            return;
        }

        // Create flash message element if it doesn't exist
        let flashContainer = document.getElementById('flash-message-container');
        if (!flashContainer) {
            flashContainer = document.createElement('div');
            flashContainer.id = 'flash-message-container';
            flashContainer.style.position = 'fixed';
            flashContainer.style.top = '20px';
            flashContainer.style.right = '20px';
            flashContainer.style.zIndex = '9999';
            document.body.appendChild(flashContainer);
        }

        // Create message element
        const messageElement = document.createElement('div');
        messageElement.className = `flash-message flash-${type}`;
        messageElement.textContent = message;

        // Add to container
        flashContainer.appendChild(messageElement);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            messageElement.style.opacity = '0';
            setTimeout(() => {
                if (flashContainer.contains(messageElement)) {
                    flashContainer.removeChild(messageElement);
                }

                // Remove container if no more messages
                if (flashContainer.children.length === 0) {
                    document.body.removeChild(flashContainer);
                }
            }, 300);
        }, 5000);
    }
}

// Global function to be called from onclick handlers
window.openUploadModal = function(event) {
    if (window.attachmentsManager) {
        return window.attachmentsManager.openUploadModal(event);
    }
    console.error('Attachments manager not initialized');
    return false;
};

// Initialize the attachments manager when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Get mission ID from the container or global variable
    const container = document.querySelector('.mission-attachments-container');
    let missionId = null;
    
    if (container) {
        missionId = container.dataset.missionId;
    } else if (typeof window.missionId !== 'undefined') {
        missionId = window.missionId;
    }
    
    if (missionId) {
        window.attachmentsManager = new MissionAttachmentsManager(missionId);
        console.log('Mission Attachments Manager initialized for mission:', missionId);
    } else {
        console.error('Could not determine mission ID for attachments manager');
    }
}); 