from pathlib import Path

p = Path("app/web/application.py")
s = p.read_text(encoding="utf-8")

anchor = '''    @app.get("/")
    def index():
'''

if anchor not in s:
    raise SystemExit("STOP: Flask route insertion point not found.")

routes = '''    def _forge_terminal_service():
        service = app.extensions.get("assistant_forge_terminal_service")
        if service is not None:
            return service

        composition = app.extensions.get("assistant_capability_composition")
        if composition is None:
            composition = build_production_capability_composition()
            app.extensions["assistant_capability_composition"] = composition

        service = composition.create_forge_terminal_service()
        app.extensions["assistant_forge_terminal_service"] = service
        return service

    def _forge_terminal_identity():
        business_id = getattr(g.principal, "business_id", None)
        if not business_id:
            raise PermissionError("An active business is required.")

        business = businesses.get(business_id)
        if business is None:
            raise PermissionError("The active business is unavailable.")

        access.require_execution(business_id)
        return business_id

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal")
    @login_required
    def forge_terminal_open(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        result = service.open_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "terminal": result}), 200

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal/command")
    @login_required
    def forge_terminal_command(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("A JSON request body is required.")

        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A non-empty terminal command is required.")
        if len(command) > 4096:
            raise ValueError("Terminal commands cannot exceed 4096 characters.")

        service = _forge_terminal_service()
        result = service.execute(business_id, project_id, job_id, command)
        return jsonify(result), 200

    @app.post("/api/forge/projects/<project_id>/jobs/<job_id>/terminal/save")
    @login_required
    def forge_terminal_save(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        result = service.save_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "result": result}), 200

    @app.delete("/api/forge/projects/<project_id>/jobs/<job_id>/terminal")
    @login_required
    def forge_terminal_close(project_id: str, job_id: str):
        require_csrf(request)
        business_id = _forge_terminal_identity()
        service = _forge_terminal_service()
        closed = service.close_session(business_id, project_id, job_id)
        return jsonify({"ok": True, "closed": closed}), 200

'''

s = s.replace(anchor, routes + anchor, 1)
p.write_text(s, encoding="utf-8")
print("Added authenticated Forge website API routes.")
