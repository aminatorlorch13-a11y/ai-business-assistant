from pathlib import Path

template = Path("app/web/templates/dashboard.html")
js = Path("app/web/static/app.js")
css = Path("app/web/static/app.css")

html = template.read_text(encoding="utf-8")
javascript = js.read_text(encoding="utf-8")
styles = css.read_text(encoding="utf-8")

# Add a launcher to the existing dashboard header.
header_anchor = '<span class="ls-business">{{ business.name }}</span>'
if 'id="forge-terminal-toggle"' not in html:
    if header_anchor not in html:
        raise SystemExit("STOP: Dashboard header anchor not found.")
    html = html.replace(
        header_anchor,
        header_anchor + '''
            <button id="forge-terminal-toggle" class="secondary"
                    type="button" aria-controls="forge-terminal-panel"
                    aria-expanded="false">
                Forge terminal
            </button>''',
        1,
    )

# Add the terminal drawer before the dashboard footer.
footer_anchor = '    <footer class="ls-footer">'
panel = '''
    <section id="forge-terminal-panel" class="forge-terminal"
             aria-hidden="true" aria-label="Forge virtual terminal">
        <header class="forge-terminal-header">
            <div>
                <span class="forge-terminal-kicker">AMINATION FORGE</span>
                <h2>Workspace terminal</h2>
                <p id="forge-terminal-status" role="status">
                    Enter a project and completed job ID to begin.
                </p>
            </div>
            <div class="forge-terminal-actions">
                <button id="forge-terminal-hide" class="secondary"
                        type="button">Hide</button>
                <button id="forge-terminal-close" class="secondary"
                        type="button">Close session</button>
            </div>
        </header>

        <form id="forge-terminal-open-form" class="forge-terminal-open">
            <label>
                Forge project ID
                <input id="forge-terminal-project" name="project_id"
                       autocomplete="off" required>
            </label>
            <label>
                Completed Forge job ID
                <input id="forge-terminal-job" name="job_id"
                       autocomplete="off" required>
            </label>
            <button id="forge-terminal-open" type="submit">
                Open workspace
            </button>
        </form>

        <pre id="forge-terminal-output" class="forge-terminal-output"
             role="log" aria-live="polite">Forge terminal is ready.</pre>

        <form id="forge-terminal-command-form" class="forge-terminal-command">
            <label class="forge-terminal-command-label" for="forge-terminal-command">
                Command
            </label>
            <input id="forge-terminal-command" name="command"
                   autocomplete="off" spellcheck="false"
                   placeholder="help, ls, cat, check, build, test, run ..."
                   disabled required>
            <button id="forge-terminal-send" type="submit" disabled>
                Run
            </button>
        </form>

        <div class="forge-terminal-footer">
            <span>Commands run through the authorised Forge workspace.</span>
            <button id="forge-terminal-save" class="secondary"
                    type="button" disabled>Save workspace</button>
        </div>
        <p id="forge-terminal-error" class="forge-terminal-error"
           role="alert"></p>
    </section>
'''

if 'id="forge-terminal-panel"' not in html:
    if footer_anchor not in html:
        raise SystemExit("STOP: Dashboard footer anchor not found.")
    html = html.replace(footer_anchor, panel + "\n" + footer_anchor, 1)

# Wire the new UI after the existing dashboard setup.
if "wireForgeTerminal();" not in html:
    html = html.replace(
        "wireDashboard();",
        "wireDashboard();\n        wireForgeTerminal();",
        1,
    )

# Add the terminal controller once.
if "function wireForgeTerminal()" not in javascript:
    javascript += r'''

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
        openButton.disabled = value || active;
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
            openForm.querySelectorAll('input').forEach(input => {
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
            openForm.querySelectorAll('input').forEach(input => {
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
'''
    javascript += "\n"

styles += r'''

/* Forge terminal drawer */
.forge-terminal {
    position: fixed;
    z-index: 1000;
    top: 0;
    right: 0;
    width: min(720px, 100%);
    height: 100dvh;
    padding: 22px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow-y: auto;
    color: var(--text);
    background: linear-gradient(155deg, #0d171e, #05090d 72%);
    border-left: 1px solid var(--line-bright);
    box-shadow: -24px 0 80px rgba(0,0,0,.55);
    transform: translateX(105%);
    visibility: hidden;
    pointer-events: none;
    transition: transform .28s ease, visibility .28s;
}

.forge-terminal.is-open {
    transform: translateX(0);
    visibility: visible;
    pointer-events: auto;
}

.forge-terminal-header,
.forge-terminal-actions,
.forge-terminal-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.forge-terminal-header h2 {
    margin: 5px 0;
    font-size: 1.35rem;
}

.forge-terminal-header p,
.forge-terminal-footer span {
    color: var(--muted);
    font-size: .85rem;
}

.forge-terminal-kicker {
    color: var(--cyan);
    font-size: .7rem;
    font-weight: 900;
    letter-spacing: .18em;
}

.forge-terminal-actions button,
.forge-terminal-footer button {
    white-space: nowrap;
}

.forge-terminal-open {
    display: grid;
    grid-template-columns: 1fr 1fr auto;
    align-items: end;
    gap: 10px;
}

.forge-terminal-open label,
.forge-terminal-command-label {
    color: var(--muted);
    font-size: .82rem;
}

.forge-terminal-open input,
.forge-terminal-command input {
    min-width: 0;
    width: 100%;
    background: #050a0e;
    border: 1px solid var(--line-bright);
    color: var(--text);
}

.forge-terminal-output {
    flex: 1;
    min-height: 220px;
    max-height: 52vh;
    overflow: auto;
    padding: 16px;
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    color: #b9f5d4;
    background: #020604;
    border: 1px solid #234637;
    border-radius: 10px;
    font: .86rem/1.6 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.forge-terminal-command {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px;
    align-items: end;
}

.forge-terminal-command-label {
    grid-column: 1 / -1;
    margin-bottom: -7px;
}

.forge-terminal-command input {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.forge-terminal-command button:disabled,
.forge-terminal-open button:disabled,
.forge-terminal-footer button:disabled,
.forge-terminal-actions button:disabled {
    opacity: .45;
    cursor: not-allowed;
}

.forge-terminal-footer {
    flex-wrap: wrap;
    padding-top: 10px;
    border-top: 1px solid var(--line);
}

.forge-terminal-error {
    min-height: 1.2em;
    margin: 0;
    color: var(--danger);
}

@media (max-width: 600px) {
    .forge-terminal {
        padding: 16px;
    }

    .forge-terminal-open {
        grid-template-columns: 1fr;
    }

    .forge-terminal-header {
        align-items: flex-start;
        flex-direction: column;
    }

    .forge-terminal-actions {
        width: 100%;
    }

    .forge-terminal-actions button {
        flex: 1;
    }
}

@media (prefers-reduced-motion: reduce) {
    .forge-terminal {
        transition: none;
    }
}
'''

template.write_text(html, encoding="utf-8")
js.write_text(javascript, encoding="utf-8")
css.write_text(styles, encoding="utf-8")

print("Forge dashboard terminal UI installed.")
