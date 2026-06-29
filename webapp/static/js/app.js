document.addEventListener('DOMContentLoaded', () => {
    const tabUpload    = document.getElementById('tab-upload');
    const tabYoutube   = document.getElementById('tab-youtube');
    const panelUpload  = document.getElementById('panel-upload');
    const panelYoutube = document.getElementById('panel-youtube');
    const dropZone     = document.getElementById('drop-zone');
    const fileInput    = document.getElementById('file-input');
    const fileInfo     = document.getElementById('file-info');
    const fileName     = document.getElementById('file-name');
    const btnClear     = document.getElementById('btn-clear');
    const youtubeUrl   = document.getElementById('youtube-url');
    const btnStart     = document.getElementById('btn-start');
    const confSlider   = document.getElementById('conf-slider');
    const confValue    = document.getElementById('conf-value');
    const iouSlider    = document.getElementById('iou-slider');
    const iouValue     = document.getElementById('iou-value');
    const paramsToggle = document.getElementById('params-toggle');
    const paramsBody   = document.getElementById('params-body');
    const paramsChevron = document.getElementById('params-chevron');
    const inputSection    = document.getElementById('input-section');
    const progressSection = document.getElementById('progress-section');
    const outputSection   = document.getElementById('output-section');
    const progressBar  = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const statusBadge  = document.getElementById('status-badge');
    const statFire     = document.getElementById('stat-fire');
    const statSmoke    = document.getElementById('stat-smoke');
    const statFrames   = document.getElementById('stat-frames');
    const outputVideo  = document.getElementById('output-video');
    const btnDownload  = document.getElementById('btn-download');
    const btnNew       = document.getElementById('btn-new');
    const resultSummary = document.getElementById('result-summary');

    let activeTab = 'upload';
    let selectedFile = null;

    function switchTab(tab) {
        activeTab = tab;
        selectedFile = null;
        fileInput.value = '';
        fileInfo.style.display = 'none';
        dropZone.querySelector('.drop-zone-content').style.display = '';
        tabUpload.classList.toggle('active', tab === 'upload');
        tabYoutube.classList.toggle('active', tab === 'youtube');
        panelUpload.classList.toggle('active', tab === 'upload');
        panelYoutube.classList.toggle('active', tab === 'youtube');
        updateStartButton();
    }

    tabUpload.addEventListener('click', () => switchTab('upload'));
    tabYoutube.addEventListener('click', () => switchTab('youtube'));

    paramsToggle.addEventListener('click', () => {
        paramsBody.classList.toggle('open');
        paramsChevron.classList.toggle('open');
    });

    confSlider.addEventListener('input', () => {
        confValue.textContent = parseFloat(confSlider.value).toFixed(2);
    });

    iouSlider.addEventListener('input', () => {
        iouValue.textContent = parseFloat(iouSlider.value).toFixed(2);
    });

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFile(files[0]);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        const allowed = ['.mp4','.avi','.mov','.mkv','.webm','.flv','.wmv'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!allowed.includes(ext)) {
            alert('Unsupported file format. Please use: ' + allowed.join(', '));
            return;
        }
        if (file.size > 500 * 1024 * 1024) {
            alert('File too large. Maximum size is 500MB.');
            return;
        }
        selectedFile = file;
        dropZone.querySelector('.drop-zone-content').style.display = 'none';
        fileInfo.style.display = 'flex';
        const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
        fileName.textContent = `${file.name} (${sizeMB} MB)`;
        updateStartButton();
    }

    btnClear.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedFile = null;
        fileInput.value = '';
        fileInfo.style.display = 'none';
        dropZone.querySelector('.drop-zone-content').style.display = '';
        updateStartButton();
    });

    youtubeUrl.addEventListener('input', updateStartButton);

    function updateStartButton() {
        if (activeTab === 'upload') {
            btnStart.disabled = !selectedFile;
        } else {
            btnStart.disabled = !youtubeUrl.value.trim();
        }
    }

    btnStart.addEventListener('click', async () => {
        const conf = parseFloat(confSlider.value);
        const iou = parseFloat(iouSlider.value);
        btnStart.disabled = true;
        inputSection.style.display = 'none';
        progressSection.style.display = '';
        outputSection.style.display = 'none';
        progressBar.style.width = '0%';
        progressText.textContent = 'Starting...';
        statusBadge.textContent = 'Starting';
        statFire.textContent = '0';
        statSmoke.textContent = '0';
        statFrames.textContent = '0';

        try {
            let jobId;
            if (activeTab === 'upload') {
                const formData = new FormData();
                formData.append('video', selectedFile);
                formData.append('conf', conf);
                formData.append('iou', iou);
                statusBadge.textContent = 'Uploading';
                progressText.textContent = 'Uploading video...';
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.error) throw new Error(data.error);
                jobId = data.job_id;
            } else {
                const url = youtubeUrl.value.trim();
                statusBadge.textContent = 'Downloading';
                progressText.textContent = 'Sending YouTube URL...';
                const res = await fetch('/api/youtube', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, conf, iou }),
                });
                const data = await res.json();
                if (data.error) throw new Error(data.error);
                jobId = data.job_id;
            }
            streamProgress(jobId);
        } catch (err) {
            alert('Error: ' + err.message);
            resetUI();
        }
    });

    function streamProgress(jobId) {
        const source = new EventSource(`/api/status/${jobId}`);
        source.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.error) { source.close(); alert('Error: ' + data.error); resetUI(); return; }
            const statusMap = { 'queued':'Queued', 'downloading':'Downloading', 'processing':'Processing', 'done':'Complete', 'error':'Error' };
            statusBadge.textContent = statusMap[data.status] || data.status;
            if (data.total > 0) { progressBar.style.width = Math.round((data.progress / data.total) * 100) + '%'; }
            progressText.textContent = data.message;
            if (data.detections) {
                statFire.textContent = data.detections.fire.toLocaleString();
                statSmoke.textContent = data.detections.smoke.toLocaleString();
                statFrames.textContent = data.detections.frames.toLocaleString();
            }
            if (data.status === 'done') { source.close(); progressBar.style.width = '100%'; showOutput(data); }
            if (data.status === 'error') { source.close(); setTimeout(() => { alert('Error: ' + data.message); resetUI(); }, 500); }
        };
        source.onerror = () => { source.close(); };
    }

    function showOutput(data) {
        setTimeout(() => {
            outputSection.style.display = '';
            outputSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            outputVideo.src = data.output;
            btnDownload.href = data.output;
            btnDownload.download = '';
            const d = data.detections;
            resultSummary.innerHTML = `<strong>Detection Summary</strong><br><strong>${d.fire.toLocaleString()}</strong> fire detections across <strong>${d.frames.toLocaleString()}</strong> frames<br><strong>${d.smoke.toLocaleString()}</strong> smoke detections<br>Confidence: <strong>${data.conf || '0.30'}</strong> | IoU: <strong>${data.iou || '0.50'}</strong>`;
        }, 500);
    }

    function resetUI() {
        inputSection.style.display = '';
        progressSection.style.display = 'none';
        outputSection.style.display = 'none';
        selectedFile = null;
        fileInput.value = '';
        fileInfo.style.display = 'none';
        dropZone.querySelector('.drop-zone-content').style.display = '';
        youtubeUrl.value = '';
        updateStartButton();
    }

    btnNew.addEventListener('click', resetUI);
});
