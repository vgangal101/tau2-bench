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
            // Reload to pick up the new storage key
            window.location.reload();
        }

        let RATER_NAME = getRaterName();
        const STORAGE_KEY = RATER_NAME
            ? `tau2_annotations_${BATCH_NAME}_${RATER_NAME}`
            : `tau2_annotations_${BATCH_NAME}`;

        if (!RATER_NAME) {
            document.addEventListener('DOMContentLoaded', promptRaterName);
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                const badge = document.getElementById('raterDisplay');
                badge.textContent = RATER_NAME;
                badge.title = 'Click to change name';
                badge.style.cursor = 'pointer';
                badge.addEventListener('click', promptRaterName);
            });
        }

        function getStoredAnnotations() {
            try {
                return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
            } catch (e) {
                return {};
            }
        }
        
        function updateStatusIndicators() {
            const stored = getStoredAnnotations();
            let completedCount = 0;
            let inProgressCount = 0;
            let pendingCount = 0;
            
            document.querySelectorAll('#taskList tr').forEach(li => {
                const taskId = li.dataset.task;
                const simId = li.dataset.sim;
                const statusEl = li.querySelector('.status');
                
                // Exact key match: task_id + "_" + simulation_id
                const key = `${taskId}_${simId}`;
                const annotation = stored[key];
                
                if (annotation && annotation.completed) {
                    statusEl.className = 'status done';
                    statusEl.textContent = 'done';
                    completedCount++;
                } else if (annotation) {
                    statusEl.className = 'status in-progress';
                    statusEl.textContent = 'in progress';
                    inProgressCount++;
                } else {
                    statusEl.className = 'status pending';
                    statusEl.textContent = 'pending';
                    pendingCount++;
                }
            });
            
            document.getElementById('completedCount').textContent = completedCount;
            document.getElementById('inProgressCount').textContent = inProgressCount;
            document.getElementById('pendingCount').textContent = pendingCount;
        }
        
        function exportToCSV() {
            const stored = getStoredAnnotations();
            const annotations = Object.values(stored);
            
            if (annotations.length === 0) {
                alert('No annotations saved yet!');
                return;
            }
            
            const headers = [
                'batch', 'rater', 'task_id', 'simulation_id', 'trial',
                'error_source', 'error_type', 'notes', 'completed', 'created_at'
            ];
            
            let csv = headers.join(',') + '\n';
            
            function escapeCSV(val) {
                if (val === null || val === undefined) return '';
                val = String(val);
                if (val.includes(',') || val.includes('\n') || val.includes('"')) {
                    val = '"' + val.replace(/"/g, '""') + '"';
                }
                return val;
            }
            
            for (const ann of annotations) {
                const row = [
                    ann.batch || BATCH_NAME, ann.rater || RATER_NAME,
                    ann.task_id, ann.simulation_id, ann.trial,
                    ann.summary_error_source || '', ann.summary_error_type || '',
                    ann.summary_notes || '', ann.completed, ann.created_at
                ].map(escapeCSV);
                csv += row.join(',') + '\n';
            }
            
            // Download
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
        
        function clearAnnotations() {
            if (confirm('Are you sure you want to clear all saved annotations? This cannot be undone.')) {
                localStorage.removeItem(STORAGE_KEY);
                updateStatusIndicators();
                showImportStatus('All annotations cleared.', false);
            }
        }
        
        function showImportStatus(message, isError) {
            const el = document.getElementById('importStatus');
            el.textContent = message;
            el.className = 'import-status ' + (isError ? 'error' : 'success');
            setTimeout(() => { el.className = 'import-status'; }, 5000);
        }
        
        function importFromCSV(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = function(e) {
                try {
                    const csv = e.target.result;
                    const rows = parseCSV(csv);
                    
                    if (rows.length < 2) {
                        showImportStatus('CSV file is empty or has no data rows', true);
                        return;
                    }
                    
                    const headers = rows[0];
                    const requiredFields = ['task_id', 'simulation_id'];
                    for (const field of requiredFields) {
                        if (!headers.includes(field)) {
                            showImportStatus(`Missing required column: ${field}`, true);
                            return;
                        }
                    }
                    
                    const stored = getStoredAnnotations();
                    let importCount = 0;
                    
                    for (let i = 1; i < rows.length; i++) {
                        const values = rows[i];
                        if (values.length !== headers.length) continue;
                        
                        const row = {};
                        headers.forEach((h, idx) => { row[h] = values[idx]; });
                        
                        const key = `${row.task_id}_${row.simulation_id}`;
                        stored[key] = {
                            id: `imported_${Date.now()}_${importCount}`,
                            task_id: row.task_id,
                            simulation_id: row.simulation_id,
                            trial: parseInt(row.trial) || 0,
                            summary_error_source: row.error_source || null,
                            summary_error_type: row.error_type || null,
                            summary_notes: row.notes || '',
                            rater: row.rater || null,
                            batch: row.batch || BATCH_NAME,
                            created_at: row.created_at || new Date().toISOString(),
                            completed: row.completed === 'true' || row.completed === 'True' || row.completed === '1',
                        };
                        importCount++;
                    }
                    
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
                    updateStatusIndicators();
                    showImportStatus(`Successfully imported ${importCount} annotations`, false);
                    
                } catch (err) {
                    showImportStatus('Error parsing CSV: ' + err.message, true);
                }
            };
            reader.readAsText(file);
            event.target.value = ''; // Reset file input
        }
        
        function parseCSV(text) {
            const rows = [];
            let current = [];
            let field = '';
            let inQuotes = false;

            for (let i = 0; i < text.length; i++) {
                const ch = text[i];

                if (inQuotes) {
                    if (ch === '"' && text[i + 1] === '"') {
                        field += '"';
                        i++;
                    } else if (ch === '"') {
                        inQuotes = false;
                    } else {
                        field += ch;
                    }
                } else if (ch === '"') {
                    inQuotes = true;
                } else if (ch === ',') {
                    current.push(field);
                    field = '';
                } else if (ch === '\r') {
                    // skip \r, handle newline on \n
                } else if (ch === '\n') {
                    current.push(field);
                    field = '';
                    if (current.some(f => f.trim())) rows.push(current);
                    current = [];
                } else {
                    field += ch;
                }
            }
            current.push(field);
            if (current.some(f => f.trim())) rows.push(current);
            return rows;
        }
        
        // Column sorting
        document.querySelectorAll('th.sortable').forEach(th => {
            th.addEventListener('click', () => {
                const sortKey = th.dataset.sort;
                const isNumeric = th.dataset.type === 'number';
                const tbody = document.getElementById('taskList');
                const rows = Array.from(tbody.querySelectorAll('tr'));

                const wasAsc = th.classList.contains('sort-asc');
                document.querySelectorAll('th.sortable').forEach(h => {
                    h.classList.remove('sort-asc', 'sort-desc');
                });
                const dir = wasAsc ? 'desc' : 'asc';
                th.classList.add(`sort-${dir}`);

                rows.sort((a, b) => {
                    let va, vb;
                    if (sortKey === 'task') {
                        va = parseInt(a.dataset.task) || 0;
                        vb = parseInt(b.dataset.task) || 0;
                    } else if (sortKey === 'experiment') {
                        va = a.querySelector('.experiment-col')?.textContent || '';
                        vb = b.querySelector('.experiment-col')?.textContent || '';
                    } else if (sortKey === 'status') {
                        va = a.querySelector('.status')?.textContent || '';
                        vb = b.querySelector('.status')?.textContent || '';
                    }
                    let cmp = isNumeric ? va - vb : String(va).localeCompare(String(vb));
                    return dir === 'desc' ? -cmp : cmp;
                });

                rows.forEach(r => tbody.appendChild(r));
            });
        });

        // Update status on page load
        updateStatusIndicators();
