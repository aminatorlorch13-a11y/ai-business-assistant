function csrf(){
    return document.cookie.split('; ')
        .find(x=>x.startsWith('assistant_csrf='))
        ?.split('=')[1] || '';
}

async function api(url,options={}){
    const headers={
        'Content-Type':'application/json',
        'X-CSRF-Token':csrf(),
        ...(options.headers||{})
    };

    const r=await fetch(url,{
        credentials:'same-origin',
        ...options,
        headers
    });

    const data=await r.json().catch(()=>({}));

    if(!r.ok){
        throw new Error(data.error||'Request failed.');
    }

    return data;
}

function wireAuthForm(id,url){
    document.getElementById(id).addEventListener('submit',async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const error=document.getElementById('error');
        error.textContent='';

        try{
            await api(url,{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            location.href='/dashboard';
        }catch(x){
            error.textContent=x.message;
        }
    });
}

function wireSignupForm(){
    document.getElementById('signup').addEventListener('submit',async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const error=document.getElementById('error');
        error.textContent='';

        try{
            await api('/api/auth/signup',{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            location.href='/login';
        }catch(x){
            error.textContent=x.message;
        }
    });
}

function addMessage(who,text){
    const box=document.getElementById('messages');
    const div=document.createElement('div');

    div.className='message '+who;
    div.textContent=text;

    box.appendChild(div);
    box.scrollTop=box.scrollHeight;
}


let sharedSpeechAudioContext = null;
let activeSpeechPlayback = null;
let speechRequestSequence = 0;

function dispatchAssistantState(state) {
    window.dispatchEvent(new CustomEvent('amination:state', {
        detail: {state}
    }));
}

function dispatchAssistantAudioLevel(level) {
    window.dispatchEvent(new CustomEvent('amination:audio-level', {
        detail: {level}
    }));
}

function prepareSpeechAudioContext() {
    const AudioContextClass =
        window.AudioContext || window.webkitAudioContext;

    if (!AudioContextClass) return null;

    try {
        if (!sharedSpeechAudioContext) {
            sharedSpeechAudioContext = new AudioContextClass();
        }

        if (sharedSpeechAudioContext.state === 'suspended') {
            const resumeResult = sharedSpeechAudioContext.resume();
            if (resumeResult && typeof resumeResult.catch === 'function') {
                resumeResult.catch(() => {});
            }
        }

        return sharedSpeechAudioContext;
    } catch (error) {
        return null;
    }
}

function finishAssistantSpeech(playback, stopSource = false) {
    if (activeSpeechPlayback !== playback) return;

    activeSpeechPlayback = null;

    if (playback.animationFrame) {
        cancelAnimationFrame(playback.animationFrame);
    }

    if (playback.source) {
        playback.source.onended = null;

        if (stopSource) {
            try {
                playback.source.stop();
            } catch (error) {
                // The source may already have stopped.
            }
        }

        try {
            playback.source.disconnect();
        } catch (error) {
            // Already disconnected.
        }
    }

    if (playback.analyser) {
        try {
            playback.analyser.disconnect();
        } catch (error) {
            // Already disconnected.
        }
    }

    if (playback.audio) {
        playback.audio.onended = null;
        playback.audio.onerror = null;
        playback.audio.onplay = null;
        playback.audio.pause();
        playback.audio.removeAttribute('src');
        playback.audio.load();
    }

    if (playback.objectUrl) {
        URL.revokeObjectURL(playback.objectUrl);
    }

    dispatchAssistantAudioLevel(0);
    dispatchAssistantState('idle');
}

function stopAssistantSpeech() {
    if (activeSpeechPlayback) {
        finishAssistantSpeech(activeSpeechPlayback, true);
    } else {
        dispatchAssistantAudioLevel(0);
    }
}

async function playAssistantSpeech(data, audioContext, requestId) {
    if (
        !data ||
        data.speech_available !== true ||
        typeof data.speech_audio_base64 !== 'string' ||
        !data.speech_audio_base64
    ) {
        throw new Error('No playable speech audio was returned.');
    }

    if (requestId !== speechRequestSequence) return;

    const binary = atob(data.speech_audio_base64);
    const bytes = new Uint8Array(binary.length);

    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }

    const blob = new Blob([bytes], {
        type: data.speech_mime_type || 'audio/mpeg'
    });

    const playback = {
        source: null,
        analyser: null,
        animationFrame: null,
        audio: null,
        objectUrl: URL.createObjectURL(blob)
    };

    activeSpeechPlayback = playback;

    if (audioContext) {
        if (audioContext.state === 'suspended') {
            await audioContext.resume();
        }

        if (requestId !== speechRequestSequence) {
            finishAssistantSpeech(playback, false);
            return;
        }

        const audioBuffer = await audioContext.decodeAudioData(
            bytes.buffer.slice(0)
        );

        if (requestId !== speechRequestSequence) {
            finishAssistantSpeech(playback, false);
            return;
        }

        const source = audioContext.createBufferSource();
        const analyser = audioContext.createAnalyser();

        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.72;

        source.buffer = audioBuffer;
        source.connect(analyser);
        analyser.connect(audioContext.destination);

        playback.source = source;
        playback.analyser = analyser;

        const samples = new Float32Array(analyser.fftSize);

        function measureAudio() {
            if (activeSpeechPlayback !== playback) return;

            analyser.getFloatTimeDomainData(samples);

            let squareSum = 0;

            for (let i = 0; i < samples.length; i++) {
                squareSum += samples[i] * samples[i];
            }

            const rms = Math.sqrt(squareSum / samples.length);
            const level = Math.min(1, rms * 8);

            dispatchAssistantAudioLevel(level);

            playback.animationFrame =
                requestAnimationFrame(measureAudio);
        }

        source.onended = () => {
            finishAssistantSpeech(playback, false);
        };

        dispatchAssistantState('speaking');
        source.start(0);
        measureAudio();
        return;
    }

    // Playback remains available on browsers without Web Audio support.
    const audio = new Audio(playback.objectUrl);
    playback.audio = audio;

    audio.onplay = () => {
        if (activeSpeechPlayback === playback) {
            dispatchAssistantState('speaking');
        }
    };

    audio.onended = () => {
        finishAssistantSpeech(playback, false);
    };

    audio.onerror = () => {
        finishAssistantSpeech(playback, false);
    };

    try {
        await audio.play();
    } catch (error) {
        finishAssistantSpeech(playback, false);
        throw new Error('The browser could not start audio playback.');
    }
}

function wireDashboard(){
    document.getElementById('logout').onclick=async()=>{
        try{
            await api('/api/auth/logout',{method:'POST'});
        }finally{
            location.href='/login';
        }
    };

    document.getElementById('assistant-form').onsubmit=async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const text=f.get('message');
        const err=document.getElementById('assistant-error');

        if(typeof text !== 'string' || !text.trim()){
            return;
        }

        err.textContent='';

        const requestId = ++speechRequestSequence;

        stopAssistantSpeech();

        // Unlock the browser audio engine during the user's Send gesture.
        const audioContext = prepareSpeechAudioContext();

        dispatchAssistantState('processing');
        addMessage('user',text);
        e.target.reset();

        try{
            const data=await api('/api/assistant/message',{
                method:'POST',
                body:JSON.stringify({message:text})
            });

            if(requestId !== speechRequestSequence){
                return;
            }

            addMessage('assistant',data.message);

            if(data.speech_available === true){
                try{
                    await playAssistantSpeech(
                        data,
                        audioContext,
                        requestId
                    );
                }catch(speechError){
                    if(requestId === speechRequestSequence){
                        err.textContent =
                            'Your text response is ready, but voice playback failed.';
                        stopAssistantSpeech();
                    }
                }
            }else{
                if(data.speech_error){
                    err.textContent=data.speech_error;
                }

                dispatchAssistantAudioLevel(0);
                dispatchAssistantState('idle');
            }
        }catch(x){
            if(requestId === speechRequestSequence){
                err.textContent=x.message;
                stopAssistantSpeech();
                dispatchAssistantState('idle');
            }
        }
    };

    document.getElementById('config-form').onsubmit=async e=>{
        e.preventDefault();

        const f=new FormData(e.target);
        const msg=document.getElementById('config-message');

        try{
            const saved = await api('/api/business/config',{
                method:'POST',
                body:JSON.stringify(Object.fromEntries(f))
            });

            const voiceLabel =
                saved.assistant_voice === 'female' ? 'Female' : 'Male';
            msg.textContent = `Saved. ${voiceLabel} voice selected for new replies.`;
        }catch(x){
            msg.textContent=x.message;
        }
    };

    document.querySelectorAll(
        '#config-form input[name="assistant_voice"]'
    ).forEach(input => {
        input.addEventListener('change', () => {
            const form = document.getElementById('config-form');
            if (form) form.requestSubmit();
        });
    });
}

function founderValue(value){
    return value===null ||
           value===undefined ||
           value===''
        ? '—'
        : String(value);
}

function founderField(label,value){
    const div=document.createElement('div');
    div.className='founder-field';

    const strong=document.createElement('strong');
    strong.textContent=label;

    const text=document.createElement('span');
    text.textContent=founderValue(value);

    div.appendChild(strong);
    div.appendChild(text);

    return div;
}

function renderFounderBusinesses(items){
    const box=document.getElementById('businesses');
    box.textContent='';

    if(!items.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No businesses found.';
        box.appendChild(empty);
        return;
    }

    for(const item of items){
        const article=document.createElement('article');
        article.className='founder-business';

        const title=document.createElement('h3');
        title.textContent=founderValue(item.name);
        article.appendChild(title);

        const grid=document.createElement('div');
        grid.className='founder-business-grid';

        grid.appendChild(
            founderField('Business ID',item.business_id)
        );

        grid.appendChild(
            founderField('Users',item.user_count)
        );

        grid.appendChild(
            founderField(
                'Owner',
                item.owner
                    ? `${founderValue(item.owner.display_name)} (${founderValue(item.owner.email)})`
                    : 'No owner membership'
            )
        );

        grid.appendChild(
            founderField('Owner User ID',item.owner?.user_id)
        );

        grid.appendChild(
            founderField('Assistant',item.assistant?.name)
        );

        grid.appendChild(
            founderField('Voice',item.assistant?.voice)
        );

        grid.appendChild(
            founderField('Commercial Status',item.commercial?.status)
        );

        grid.appendChild(
            founderField(
                'Execution Allowed',
                item.commercial?.execution_allowed
            )
        );

        grid.appendChild(
            founderField(
                'Execution Reason',
                item.commercial?.execution_reason
            )
        );

        grid.appendChild(
            founderField(
                'Trial Started',
                item.commercial?.trial_started_at
            )
        );

        grid.appendChild(
            founderField(
                'Trial Ends',
                item.commercial?.trial_ends_at
            )
        );

        grid.appendChild(
            founderField(
                'Paid Evidence',
                item.commercial?.paid
            )
        );

        grid.appendChild(
            founderField(
                'Purchase Count',
                item.commercial?.purchase_count
            )
        );

        grid.appendChild(
            founderField(
                'Last Event',
                item.operational?.last_event_at
            )
        );

        article.appendChild(grid);

        if(item.commercial?.last_purchase){
            const purchase=item.commercial.last_purchase;
            const purchaseBox=document.createElement('div');

            purchaseBox.className='founder-field';
            purchaseBox.style.marginTop='12px';

            purchaseBox.appendChild(
                founderField(
                    'Payment Provider',
                    purchase.provider
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Payment Amount',
                    purchase.amount
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Payment Currency',
                    purchase.currency
                )
            );

            purchaseBox.appendChild(
                founderField(
                    'Paid At',
                    purchase.paid_at
                )
            );

            article.appendChild(purchaseBox);
        }

        box.appendChild(article);
    }
}

function renderFounderEvents(items){
    const box=document.getElementById('events');
    box.textContent='';

    if(!items.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No platform events recorded.';
        box.appendChild(empty);
        return;
    }

    for(const item of items){
        const article=document.createElement('article');
        article.className='founder-event';

        const heading=document.createElement('strong');

        heading.textContent=
            `${founderValue(item.event_type)} · `+
            `${founderValue(item.outcome)}`;

        const details=document.createElement('p');
        details.className='muted';

        details.textContent=
            `${founderValue(item.occurred_at)} · `+
            `${founderValue(item.channel)} · `+
            `${founderValue(item.action)}`;
article.appendChild(heading);
        article.appendChild(details);
box.appendChild(article);
    }
}

function setFounderMetric(key,metric){
    const value=document.getElementById(`metric-${key}`);
    const status=document.getElementById(`metric-${key}-status`);

    if(!value || !status){
        return;
    }

    value.textContent=founderValue(metric?.value);

    status.textContent=
        metric?.status === 'available'
            ? 'AUTHORITATIVE'
            : founderValue(metric?.status).toUpperCase();
}

function setFounderInstrumentationMetric(key,metric){
    const value=document.getElementById(`metric-${key}`);
    const status=document.getElementById(`metric-${key}-status`);

    if(!value || !status){
        return;
    }

    value.textContent=founderValue(metric?.value);
    status.textContent=founderValue(metric?.status).toUpperCase();
}

function setFounderText(id,value){
    const element=document.getElementById(id);

    if(element){
        element.textContent=founderValue(value);
    }
}

function renderFounderChannels(channels){
    const box=document.getElementById('channel-events');

    if(!box){
        return;
    }

    box.textContent='';

    const entries=Object.entries(channels||{});

    if(!entries.length){
        const empty=document.createElement('p');
        empty.className='muted';
        empty.textContent='No channel telemetry recorded.';
        box.appendChild(empty);
        return;
    }

    for(const [channel,count] of entries){
        const cell=document.createElement('div');
        cell.className='channel-cell';

        const label=document.createElement('span');
        label.textContent=channel;

        const value=document.createElement('strong');
        value.textContent=founderValue(count);

        cell.appendChild(label);
        cell.appendChild(value);

        box.appendChild(cell);
    }
}

function renderFounderAnalytics(data){
    setFounderMetric('businesses',data.businesses);
    setFounderMetric('active',data.active_businesses);
    setFounderMetric('trials',data.trial_businesses);
    setFounderMetric('conversions',data.trial_conversions);
    setFounderMetric('conversion-rate',data.trial_conversion_rate);
    setFounderMetric('revenue',data.revenue);
    setFounderMetric('execution-volume',data.execution_volume);
    setFounderMetric('events',data.recorded_events);

    setFounderText('state-trial',data.trial_businesses?.value);
    setFounderText('state-active',data.active_businesses?.value);
    setFounderText('state-expired',data.expired_businesses?.value);
    setFounderText('state-suspended',data.suspended_businesses?.value);

    setFounderText('events-success',data.successful_events?.value);
    setFounderText('events-failure',data.failed_events?.value);
    setFounderText('events-denied',data.denied_events?.value);
    setFounderText('events-error-count',data.error_events?.value);

    setFounderInstrumentationMetric(
        'integration-health',
        data.integration_health
    );

    setFounderInstrumentationMetric(
        'website-visitors',
        data.website_visitors
    );

    setFounderInstrumentationMetric(
        'website-page-views',
        data.website_page_views
    );

    setFounderInstrumentationMetric(
        'purchases',
        data.verified_purchases
    );

    renderFounderChannels(data.channel_events);
}

async function loadFounderAnalytics(){
    const banner=document.querySelector('.telemetry-label');

    try{
        const data=await api('/api/founder/analytics');

        renderFounderAnalytics(data);

        if(banner){
            banner.textContent='LIVE DATA';
        }
    }catch(x){
        if(banner){
            banner.textContent='TELEMETRY ERROR';
        }

        const metricIds=[
            'metric-businesses',
            'metric-active',
            'metric-trials',
            'metric-conversions',
            'metric-conversion-rate',
            'metric-revenue',
            'metric-execution-volume',
            'metric-events'
        ];

        for(const id of metricIds){
            const element=document.getElementById(id);

            if(element){
                element.textContent='ERROR';
            }
        }
    }
}

async function loadFounderBusinesses(){
    const error=document.getElementById('founder-error');
    error.textContent='';

    try{
        const data=await api('/api/founder/businesses');
        renderFounderBusinesses(data.businesses||[]);
    }catch(x){
        error.textContent=x.message;
    }
}

async function loadFounderEvents(){
    const error=document.getElementById('events-error');
    error.textContent='';

    try{
        const data=await api('/api/founder/events');
        renderFounderEvents(data.events||[]);
    }catch(x){
        error.textContent=x.message;
    }
}

function wireFounderDashboard(){
    document.getElementById('founder-logout').onclick=async()=>{
        try{
            await api('/api/auth/logout',{method:'POST'});
        }finally{
            location.href='/login';
        }
    };

    document.getElementById('refresh-businesses').onclick=
        loadFounderBusinesses;

    document.getElementById('refresh-events').onclick=
        loadFounderEvents;

    loadFounderAnalytics();
    loadFounderBusinesses();
    loadFounderEvents();
}


function wireForgeTerminal() {
    const panel = document.getElementById('forge-terminal-panel');
    if (!panel) return;

    const byId = id => document.getElementById(id);
    const toggle = byId('forge-terminal-toggle');
    const hide = byId('forge-terminal-hide');
    const close = byId('forge-terminal-close');
    const openForm = byId('forge-terminal-open-form');
    const commandForm = byId('forge-terminal-command-form');
    const projectInput = byId('forge-terminal-project');
    const jobInput = byId('forge-terminal-job');
    const commandInput = byId('forge-terminal-command');
    const output = byId('forge-terminal-output');
    const status = byId('forge-terminal-status');
    const error = byId('forge-terminal-error');
    const save = byId('forge-terminal-save');
    const openButton = byId('forge-terminal-open');
    const sendButton = byId('forge-terminal-send');

    let active = false;
    let busy = false;
    let projectId = '';
    let jobId = '';
    let commandHistory = [];
    let historyIndex = 0;
    let projects = [];

    function addOption(select, value, label) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    }

    function refreshOpenButton() {
        openButton.disabled = busy || active ||
            !projectInput.value || !jobInput.value;
    }

    function populateJobs(projectId) {
        jobInput.replaceChildren();
        addOption(jobInput, '', 'Choose a completed Forge job');
        const project = projects.find(item => item.project_id === projectId);
        if (project) {
            for (const job of project.jobs) {
                const label = `${job.job_id} — ${job.job_type}`;
                addOption(jobInput, job.job_id, label);
            }
        }
        jobInput.disabled = !project || project.jobs.length === 0;
        refreshOpenButton();
    }

    async function loadProjects() {
        projectInput.disabled = true;
        jobInput.disabled = true;
        projectInput.replaceChildren();
        jobInput.replaceChildren();
        addOption(projectInput, '', 'Loading active projects…');
        addOption(jobInput, '', 'Choose a project first');

        try {
            const result = await api('/api/forge/terminal/projects');
            projects = Array.isArray(result.projects) ? result.projects : [];
            projectInput.replaceChildren();
            addOption(projectInput, '', 'Choose an active Forge project');

            for (const project of projects) {
                const label = project.jobs.length
                    ? `${project.name} (${project.jobs.length} eligible jobs)`
                    : `${project.name} (no eligible jobs)`;
                addOption(projectInput, project.project_id, label);
            }

            projectInput.disabled = projects.length === 0;
            populateJobs('');
            if (projects.length === 0) {
                showError('No active Forge projects are available for this business.');
            }
        } catch (requestError) {
            projectInput.replaceChildren();
            addOption(projectInput, '', 'Projects could not be loaded');
            jobInput.replaceChildren();
            addOption(jobInput, '', 'Choose a project first');
            showError(requestError.message);
        }
        refreshOpenButton();
    }

    projectInput.addEventListener('change', () => {
        populateJobs(projectInput.value);
    });
    jobInput.addEventListener('change', refreshOpenButton);
    loadProjects();

    const endpoint = () =>
        `/api/forge/projects/${encodeURIComponent(projectId)}` +
        `/jobs/${encodeURIComponent(jobId)}/terminal`;

    function showPanel() {
        panel.classList.add('is-open');
        panel.setAttribute('aria-hidden', 'false');
        toggle.setAttribute('aria-expanded', 'true');
        toggle.textContent = 'Hide terminal';
    }

    function hidePanel() {
        panel.classList.remove('is-open');
        panel.setAttribute('aria-hidden', 'true');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.textContent = 'Forge terminal';
        // Hiding the panel deliberately does not close the session.
    }

    function writeOutput(value) {
        const text = typeof value === 'string'
            ? value
            : JSON.stringify(value, null, 2);
        output.textContent += '\n' + text;
        output.scrollTop = output.scrollHeight;
    }

    function setBusy(value) {
        busy = value;
        openButton.disabled = value || active || !projectInput.value || !jobInput.value;
        sendButton.disabled = value || !active;
        commandInput.disabled = value || !active;
        save.disabled = value || !active;
        close.disabled = value || !active;
        status.textContent = value
            ? 'Working…'
            : active ? 'Workspace session active.' : 'No active session.';
    }

    function showError(message) {
        error.textContent = message || 'The terminal request failed.';
    }

    toggle.addEventListener('click', () => {
        if (panel.classList.contains('is-open')) hidePanel();
        else showPanel();
    });

    hide.addEventListener('click', hidePanel);

    openForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy || active) return;

        const nextProject = projectInput.value.trim();
        const nextJob = jobInput.value.trim();

        if (!nextProject || !nextJob) {
            showError('Enter both the project ID and completed job ID.');
            return;
        }

        projectId = nextProject;
        jobId = nextJob;
        error.textContent = '';
        setBusy(true);

        try {
            const result = await api(endpoint(), {method: 'POST'});
            active = true;
            commandHistory = [];
            historyIndex = 0;
            output.textContent = 'Forge workspace session opened.';
            if (result.terminal !== undefined) {
                writeOutput(result.terminal);
            }
            openForm.querySelectorAll('input, select').forEach(input => {
                input.disabled = true;
            });
            setBusy(false);
            showPanel();
            commandInput.focus();
        } catch (requestError) {
            active = false;
            setBusy(false);
            showError(requestError.message);
        }
    });

    commandForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (!active || busy) return;

        const command = commandInput.value.trim();
        if (!command) return;

        error.textContent = '';
        commandHistory.push(command);
        historyIndex = commandHistory.length;
        writeOutput('$ ' + command);
        commandInput.value = '';
        setBusy(true);

        try {
            const result = await api(endpoint() + '/command', {
                method: 'POST',
                body: JSON.stringify({command})
            });

            if (result.output !== undefined) {
                writeOutput(result.output);
                const remaining = {...result};
                delete remaining.output;
                if (Object.keys(remaining).length) writeOutput(remaining);
            } else {
                writeOutput(result);
            }
        } catch (requestError) {
            showError(requestError.message);
            writeOutput('Request failed: ' + requestError.message);
        } finally {
            setBusy(false);
            commandInput.focus();
        }
    });

    commandInput.addEventListener('keydown', event => {
        if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
        event.preventDefault();

        if (event.key === 'ArrowUp' && historyIndex > 0) {
            historyIndex--;
            commandInput.value = commandHistory[historyIndex] || '';
        } else if (
            event.key === 'ArrowDown' &&
            historyIndex < commandHistory.length - 1
        ) {
            historyIndex++;
            commandInput.value = commandHistory[historyIndex] || '';
        } else if (event.key === 'ArrowDown') {
            historyIndex = commandHistory.length;
            commandInput.value = '';
        }
    });

    save.addEventListener('click', async () => {
        if (!active || busy) return;
        error.textContent = '';
        setBusy(true);

        try {
            const result = await api(endpoint() + '/save', {
                method: 'POST'
            });
            writeOutput('Workspace save response:');
            writeOutput(result);
        } catch (requestError) {
            showError(requestError.message);
        } finally {
            setBusy(false);
        }
    });

    close.addEventListener('click', async () => {
        if (!active || busy) return;
        if (!window.confirm(
            'Close this Forge terminal session? Unsaved changes may be lost. Save first if needed.'
        )) return;

        error.textContent = '';
        setBusy(true);

        try {
            const result = await api(endpoint(), {method: 'DELETE'});
            writeOutput('Terminal session closed.');
            writeOutput(result);
            active = false;
            projectId = '';
            jobId = '';
            openForm.querySelectorAll('input, select').forEach(input => {
                input.disabled = false;
            });
            setBusy(false);
            hidePanel();
            status.textContent = 'Session closed. Open a workspace to continue.';
        } catch (requestError) {
            setBusy(false);
            showError(requestError.message);
        }
    });

    setBusy(false);
}
