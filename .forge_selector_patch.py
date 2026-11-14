from pathlib import Path
import re

application = Path("app/web/application.py")
dashboard = Path("app/web/templates/dashboard.html")
javascript = Path("app/web/static/app.js")
styles = Path("app/web/static/app.css")

for path in (application, dashboard, javascript, styles):
    if not path.is_file():
        raise SystemExit(f"Required file is missing: {path}")

app_text = application.read_text()
html_text = dashboard.read_text()
js_text = javascript.read_text()
css_text = styles.read_text()

# 1. Fix lazy composition creation: use the database initialized by create_app().
wrong = "composition = build_production_capability_composition()"
right = (
    "composition = build_production_capability_composition(\n"
    "                database=app.extensions['assistant_database'],\n"
    "            )"
)
if wrong in app_text:
    app_text = app_text.replace(wrong, right, 1)
elif right not in app_text:
    raise SystemExit("Could not safely identify the lazy composition factory call.")

# 2. Add a tenant-scoped project/job discovery endpoint.
route_marker = (
    '    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal")'
)
route_code = '''    @app.get("/api/forge/terminal/projects")
    @login_required
    def forge_terminal_projects():
        business_id = _forge_terminal_identity()

        # Reuse the composition and database already owned by this Flask app.
        _forge_terminal_service()
        composition = app.extensions.get("assistant_capability_composition")
        if composition is None or composition.forge_job_store is None:
            return jsonify({"error": "Forge job storage is unavailable."}), 503

        database = app.extensions["assistant_database"]
        with database.connection() as connection:
            rows = connection.execute(
                """
                SELECT project_id, name
                FROM forge_projects
                WHERE business_id = ? AND status = 'ACTIVE'
                ORDER BY name ASC, project_id ASC
                LIMIT 100
                """,
                (business_id,),
            ).fetchall()

        projects = []
        for row in rows:
            project_id = row["project_id"]
            records = composition.forge_job_store.list_for_project(
                business_id, project_id
            )
            jobs = []

            for record in records:
                job = record.job
                status = getattr(job.status, "value", job.status)

                # Locked candidates and all non-vaulted jobs stay unavailable.
                if status != "completed_vaulted":
                    continue

                job_type = getattr(job.job_type, "value", job.job_type)
                phase = getattr(job.phase, "value", job.phase)
                created_at = job.created_at
                if hasattr(created_at, "isoformat"):
                    created_at = created_at.isoformat()

                jobs.append({
                    "job_id": job.job_id,
                    "job_type": str(job_type),
                    "phase": str(phase),
                    "created_at": str(created_at),
                })

                if len(jobs) >= 50:
                    break

            projects.append({
                "project_id": project_id,
                "name": row["name"],
                "jobs": jobs,
            })

        return jsonify({"ok": True, "projects": projects}), 200

'''
if route_code not in app_text:
    if app_text.count(route_marker) != 1:
        raise SystemExit("Could not safely locate the Forge terminal route insertion point.")
    app_text = app_text.replace(route_marker, route_code + route_marker, 1)

# 3. Make the existing project/job controls real selectors.
for element_id, name in (
    ("forge-terminal-project", "project_id"),
    ("forge-terminal-job", "job_id"),
):
    pattern = (
        rf'<input(?=[^>]*\bid="{re.escape(element_id)}")'
        rf'(?=[^>]*\bname="{re.escape(name)}")[^>]*>'
    )
    replacement = f'<select id="{element_id}" name="{name}" required></select>'
    html_text, count = re.subn(pattern, replacement, html_text, count=1)
    if count == 0 and replacement not in html_text:
        raise SystemExit(f"Could not safely replace the {element_id} input.")

# 4. Add project/job loading to the existing terminal controller.
anchor = "    let historyIndex = 0;"
loader = '''    let historyIndex = 0;
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
    loadProjects();'''

if anchor in js_text:
    js_text = js_text.replace(anchor, loader, 1)
elif "async function loadProjects()" not in js_text:
    raise SystemExit("Could not safely locate the terminal controller initialization.")

# Select controls must be locked while the session is active.
js_text = js_text.replace(
    "openForm.querySelectorAll('input').forEach(input => {",
    "openForm.querySelectorAll('input, select').forEach(input => {",
)
# Re-enable selectors after closing a session, if this controller has that block.
js_text = js_text.replace(
    "openForm.querySelectorAll('input').forEach(input => input.disabled = false);",
    "openForm.querySelectorAll('input, select').forEach(input => input.disabled = false);",
)

# Keep the open button state in sync with selection and session state.
js_text = js_text.replace(
    "openButton.disabled = value || active;",
    "openButton.disabled = value || active || !projectInput.value || !jobInput.value;",
    1,
)

# Include selects in the existing terminal form control styling.
css_text = css_text.replace(
    ".forge-terminal-open input",
    ".forge-terminal-open input,\\n.forge-terminal-open select",
)

application.write_text(app_text)
dashboard.write_text(html_text)
javascript.write_text(js_text)
styles.write_text(css_text)

print("Forge database wiring and business-scoped project/job selectors installed.")
