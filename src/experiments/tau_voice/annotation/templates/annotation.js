        // Column toggle functionality
        document.querySelectorAll('.column-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const col = btn.dataset.col;
                btn.classList.toggle('hidden');
                
                // Toggle only table cells (th and td), not the buttons themselves
                document.querySelectorAll(`th[data-col="${col}"], td[data-col="${col}"]`).forEach(cell => {
                    cell.classList.toggle('col-hidden');
                });
            });
        });
        
        // Auto-collapse empty columns on load
        function checkEmptyColumns() {
            const cols = ['agent-tools', 'user-tools'];
            
            cols.forEach(col => {
                const cells = document.querySelectorAll(`td[data-col="${col}"]`);
                let isEmpty = true;
                
                cells.forEach(cell => {
                    // Check if cell has any real content (not just "-")
                    if (cell.textContent.trim() !== '-' && cell.textContent.trim() !== '') {
                        isEmpty = false;
                    }
                });
                
                if (isEmpty) {
                    // Collapse this column
                    const btn = document.querySelector(`.column-toggle[data-col="${col}"]`);
                    if (btn && !btn.classList.contains('hidden')) {
                        btn.click();
                    }
                }
            });
        }
        
        // Run on page load
        checkEmptyColumns();
        
        // Error data from LLM judge review
        const judgeErrors = __ERRORS_JSON__;
        
        // Mark rows that have errors
        function markErrorRows() {
            judgeErrors.forEach(err => {
                document.querySelectorAll('tr[data-tick-start]').forEach(row => {
                    const rowStart = parseInt(row.dataset.tickStart);
                    const rowEnd = parseInt(row.dataset.tickEnd);
                    
                    // Check if this row overlaps with the error tick range
                    if (rowStart <= err.tick_end && rowEnd >= err.tick_start) {
                        row.classList.add('has-error');
                        if (err.source === 'agent') {
                            row.classList.add('has-agent-error');
                        } else {
                            row.classList.add('has-user-error');
                        }
                        
                        // Update marker with error info
                        const marker = row.querySelector('.error-marker');
                        const tooltip = row.querySelector('.error-tooltip');
                        if (marker && tooltip) {
                            // Store error IDs for navigation
                            const existingIds = marker.dataset.errorIds || '';
                            marker.dataset.errorIds = existingIds ? `${existingIds},${err.id}` : err.id;
                            
                            // Build tooltip content
                            const errorLine = `<div><strong>${err.source.toUpperCase()}</strong> (${err.severity}): ${err.tags.join(', ')}</div>`;
                            tooltip.innerHTML += errorLine;
                        }
                    }
                });
            });
        }
        markErrorRows();
        
        // Click on error marker to navigate to error in review section
        document.querySelectorAll('.error-marker').forEach(marker => {
            marker.addEventListener('click', (e) => {
                e.stopPropagation();
                const errorIds = marker.dataset.errorIds;
                if (errorIds) {
                    const firstErrorId = errorIds.split(',')[0];
                    const errorItem = document.querySelector(`.error-item[data-error-id="${firstErrorId}"]`);
                    if (errorItem) {
                        // Open the review section if closed
                        const reviewSection = document.querySelector('.review-section details');
                        if (reviewSection && !reviewSection.open) {
                            reviewSection.open = true;
                        }
                        
                        // Open this specific error
                        if (!errorItem.open) {
                            errorItem.open = true;
                        }
                        
                        // Scroll to error
                        errorItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        
                        // Highlight animation
                        errorItem.style.transition = 'background 0.3s';
                        errorItem.style.background = '#ffeb3b';
                        setTimeout(() => {
                            errorItem.style.background = '';
                        }, 1500);
                    }
                }
            });
        });
        
        // Click on error ticks to navigate to that part of the conversation
        document.querySelectorAll('.clickable-error').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();  // Don't toggle the details
                const tickStart = parseInt(el.dataset.tickStart);
                const tickEnd = parseInt(el.dataset.tickEnd);
                
                // Find the first row that overlaps with this tick range
                let targetRow = null;
                document.querySelectorAll('tr[data-tick-start]').forEach(row => {
                    const rowStart = parseInt(row.dataset.tickStart);
                    const rowEnd = parseInt(row.dataset.tickEnd);
                    
                    if (rowStart <= tickEnd && rowEnd >= tickStart && !targetRow) {
                        targetRow = row;
                    }
                });
                
                if (targetRow) {
                    // Scroll to row
                    targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    
                    // Add highlight animation
                    targetRow.classList.remove('error-highlight');
                    void targetRow.offsetWidth;  // Trigger reflow
                    targetRow.classList.add('error-highlight');
                    
                    // Play audio from this point
                    const clickAudio = document.getElementById('mainAudio');
                    if (clickAudio) {
                        const startTime = parseFloat(targetRow.dataset.startTime);
                        if (!isNaN(startTime)) {
                            clickAudio.currentTime = startTime;
                            clickAudio.play();
                        }
                    }
                }
            });
        });
        

        // ============================================================
        // Audio controls and annotation form (second script block)
        // ============================================================

        // Audio controls (after sticky player is in DOM)
        const mainAudio = document.getElementById('mainAudio');
        if (mainAudio) {
            // Click on tick or time to seek
            document.querySelectorAll('.clickable-time').forEach(cell => {
                cell.addEventListener('click', (e) => {
                    const row = cell.closest('tr');
                    const startTime = parseFloat(row.dataset.startTime);
                    if (!isNaN(startTime)) {
                        mainAudio.currentTime = startTime;
                        mainAudio.play();
                        
                        // Highlight current row
                        document.querySelectorAll('tr.playing').forEach(r => r.classList.remove('playing'));
                        row.classList.add('playing');
                    }
                });
            });
            
            // Update highlighted row during playback
            mainAudio.addEventListener('timeupdate', () => {
                const currentTime = mainAudio.currentTime;
                let activeRow = null;
                
                document.querySelectorAll('tr[data-start-time]').forEach(row => {
                    const startTime = parseFloat(row.dataset.startTime);
                    if (startTime <= currentTime) {
                        activeRow = row;
                    }
                });
                
                // Only update if changed (no auto-scroll so user can browse freely)
                const currentPlaying = document.querySelector('tr.playing');
                if (activeRow && activeRow !== currentPlaying) {
                    if (currentPlaying) currentPlaying.classList.remove('playing');
                    activeRow.classList.add('playing');
                }
            });
            
            // Clear highlight when audio ends
            mainAudio.addEventListener('ended', () => {
                document.querySelectorAll('tr.playing').forEach(r => r.classList.remove('playing'));
            });
            
            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Don't trigger if user is typing in an input
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                
                switch (e.code) {
                    case 'Space':
                        e.preventDefault();
                        if (mainAudio.paused) {
                            mainAudio.play();
                        } else {
                            mainAudio.pause();
                        }
                        break;
                    case 'ArrowLeft':
                        e.preventDefault();
                        mainAudio.currentTime = Math.max(0, mainAudio.currentTime - 5);
                        break;
                    case 'ArrowRight':
                        e.preventDefault();
                        mainAudio.currentTime = Math.min(mainAudio.duration, mainAudio.currentTime + 5);
                        break;
                }
            });
        }
        
        // Annotation form handling - Error Editor
        const annotationMeta = {
            simulation_id: "__SIMULATION_ID__",
            task_id: "__TASK_ID__",
            trial: __TRIAL__
        };
        
        const BATCH_NAME = '__BATCH_NAME__';
        const RATER_KEY = `tau2_rater_${BATCH_NAME}`;

        function getRaterName() {
            return localStorage.getItem(RATER_KEY);
        }

        function promptRaterName() {
            const overlay = document.getElementById('raterModal');
            overlay.classList.add('active');
            document.getElementById('raterNameInput').focus();
        }

        function submitRaterName() {
            const name = document.getElementById('raterNameInput').value.trim();
            if (!name) return;
            localStorage.setItem(RATER_KEY, name);
            document.getElementById('raterModal').classList.remove('active');
            document.getElementById('raterDisplay').textContent = name;
            initPage();
        }

        let RATER_NAME = getRaterName();
        const STORAGE_KEY = RATER_NAME
            ? `tau2_annotations_${BATCH_NAME}_${RATER_NAME}`
            : `tau2_annotations_${BATCH_NAME}`;

        function initPage() {
            RATER_NAME = getRaterName();
            // Re-derive storage key with rater name
            const newKey = `tau2_annotations_${BATCH_NAME}_${RATER_NAME}`;
            if (newKey !== STORAGE_KEY) {
                window.location.reload();
                return;
            }
            if (document.getElementById('raterDisplay')) {
                document.getElementById('raterDisplay').textContent = RATER_NAME;
            }
            initializeForm();
        }

        if (!RATER_NAME) {
            document.addEventListener('DOMContentLoaded', promptRaterName);
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                const badge = document.getElementById('raterDisplay');
                if (badge) {
                    badge.textContent = RATER_NAME;
                    badge.title = 'Click to change name';
                    badge.style.cursor = 'pointer';
                    badge.addEventListener('click', promptRaterName);
                }
            });
        }

        function getStoredAnnotations() {
            try {
                return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            } catch (e) {
                return {};
            }
        }
        
        function initializeForm() {
            const key = `${annotationMeta.task_id}_${annotationMeta.simulation_id}`;
            const stored = getStoredAnnotations();
            const saved = stored[key];
            
            if (saved) {
                document.getElementById('summaryErrorSource').value = saved.summary_error_source || '';
                document.getElementById('summaryErrorType').value = saved.summary_error_type || '';
                document.getElementById('summaryNotes').value = saved.summary_notes || '';
                document.getElementById('markComplete').checked = saved.completed || false;
                showStatus(saved.completed ? 'Loaded completed annotation' : 'Loaded saved annotation');
            }
        }
        
        function generateAnnotation() {
            return {
                id: `annotation_${Date.now().toString(36)}`,
                simulation_id: annotationMeta.simulation_id,
                task_id: annotationMeta.task_id,
                trial: annotationMeta.trial,
                summary_error_source: document.getElementById('summaryErrorSource').value || null,
                summary_error_type: document.getElementById('summaryErrorType').value || null,
                summary_notes: document.getElementById('summaryNotes').value,
                rater: RATER_NAME,
                batch: BATCH_NAME,
                created_at: new Date().toISOString(),
                completed: document.getElementById('markComplete').checked,
            };
        }
        
        function saveToLocalStorage() {
            const annotation = generateAnnotation();
            const key = `${annotationMeta.task_id}_${annotationMeta.simulation_id}`;
            const stored = getStoredAnnotations();
            stored[key] = annotation;
            localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
            return annotation;
        }
        
        function showStatus(message, isError = false) {
            const statusEl = document.getElementById('statusMessage');
            statusEl.textContent = message;
            statusEl.className = 'status-message ' + (isError ? 'error' : 'success');
            setTimeout(() => {
                statusEl.className = 'status-message';
            }, 3000);
        }
        
        // Initialize on page load
        initializeForm();
        
        // Form fields auto-save
        ['summaryErrorSource', 'summaryErrorType', 'summaryNotes'].forEach(id => {
            const el = document.getElementById(id);
            el.addEventListener('change', () => { saveToLocalStorage(); showStatus('Auto-saved'); });
            if (el.tagName === 'TEXTAREA') {
                el.addEventListener('blur', () => { saveToLocalStorage(); showStatus('Auto-saved'); });
            }
        });
        
        function autoBackupCSV() {
            const stored = getStoredAnnotations();
            const annotations = Object.values(stored);
            if (annotations.length === 0) return;

            const headers = [
                'batch', 'rater', 'task_id', 'simulation_id', 'trial',
                'error_source', 'error_type', 'notes', 'completed', 'created_at'
            ];

            function escapeCSV(val) {
                if (val === null || val === undefined) return '';
                val = String(val);
                if (val.includes(',') || val.includes('\n') || val.includes('"')) {
                    val = '"' + val.replace(/"/g, '""') + '"';
                }
                return val;
            }

            let csv = headers.join(',') + '\n';
            for (const ann of annotations) {
                csv += [
                    ann.batch || BATCH_NAME, ann.rater || RATER_NAME,
                    ann.task_id, ann.simulation_id, ann.trial,
                    ann.summary_error_source || '', ann.summary_error_type || '',
                    ann.summary_notes || '', ann.completed, ann.created_at
                ].map(escapeCSV).join(',') + '\n';
            }

            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${BATCH_NAME}_${RATER_NAME}_${new Date().toISOString().slice(0,19).replace(/:/g, '-')}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // Mark complete checkbox
        document.getElementById('markComplete').addEventListener('change', () => {
            const isComplete = document.getElementById('markComplete').checked;
            saveToLocalStorage();
            if (isComplete) {
                autoBackupCSV();
                showStatus('Marked as complete! Backup CSV downloaded.');
            } else {
                showStatus('Marked as in progress');
            }
        });
        
        document.getElementById('copyAnnotationBtn').addEventListener('click', () => {
            const annotation = saveToLocalStorage();
            const json = JSON.stringify(annotation, null, 2);
            
            navigator.clipboard.writeText(json).then(() => {
                showStatus('Saved & copied to clipboard!');
            }).catch(err => {
                showStatus('Failed to copy: ' + err, true);
            });
        });
        
        document.getElementById('downloadAnnotationBtn').addEventListener('click', () => {
            const annotation = saveToLocalStorage();
            const json = JSON.stringify(annotation, null, 2);
            
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${BATCH_NAME}_${RATER_NAME}_task${annotationMeta.task_id}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            
            showStatus('Saved & downloaded!');
        });
        
        // Guidelines modal
        const modal = document.getElementById('guidelinesModal');
        const helpBtn = document.getElementById('helpBtn');
        const modalClose = document.getElementById('modalClose');
        
        function openGuidelines() {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
        
        function closeGuidelines() {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
        
        helpBtn.addEventListener('click', openGuidelines);
        modalClose.addEventListener('click', closeGuidelines);
        
        // Close on click outside modal content
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeGuidelines();
            }
        });
        
        // Keyboard shortcuts for modal
        document.addEventListener('keydown', (e) => {
            // Don't trigger if typing in a form field
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            
            if (e.key === 'g' || e.key === 'G') {
                if (!modal.classList.contains('active')) {
                    e.preventDefault();
                    openGuidelines();
                }
            }
            
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                closeGuidelines();
            }
        });
