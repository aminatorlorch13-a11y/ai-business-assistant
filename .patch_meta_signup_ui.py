from pathlib import Path

module = Path("app/web/meta_whatsapp_signup.py")
source = module.read_text(encoding="utf-8")

if "def whatsapp_signup_page():" not in source:
    source = source.replace(
        "from flask import Blueprint, g, jsonify, request",
        "from flask import Blueprint, g, jsonify, request, render_template",
        1,
    )
    anchor = "    return blueprint"
    page_route = '''
    @blueprint.get("/integrations/whatsapp/connect")
    @login_required
    def whatsapp_signup_page():
        principal = principal_and_role()
        if principal is None:
            return jsonify({"error": "Business owner or administrator access is required."}), 403

        config = configuration()
        if config is None:
            return jsonify({"error": "Meta WhatsApp Embedded Signup is not configured."}), 503

        meta, config_id, _ = config
        signup_version = os.getenv("META_EMBEDDED_SIGNUP_VERSION", "v4").lower()
        if signup_version not in {"v4", "v5"}:
            return jsonify({"error": "Unsupported Embedded Signup version configuration."}), 503

        return render_template(
            "whatsapp_connect.html",
            meta_app_id=meta.app_id,
            config_id=config_id,
            graph_api_version=meta.graph_api_version,
            signup_version=signup_version,
        )

'''
    if anchor not in source:
        raise SystemExit("Blueprint return anchor missing; no changes made.")
    source = source.replace(anchor, page_route + anchor, 1)
    module.write_text(source, encoding="utf-8")

template = Path("app/web/templates/whatsapp_connect.html")
if template.exists():
    raise SystemExit("whatsapp_connect.html already exists; refusing to overwrite.")

template.write_text("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect WhatsApp Business | Amination AI</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
  <style>
    .wa-connect{max-width:680px;margin:48px auto;padding:28px;border-radius:16px}
    .wa-connect button{padding:13px 20px;border:0;border-radius:9px;cursor:pointer}
    .wa-connect button:disabled{opacity:.55;cursor:wait}
    #wa-status{margin-top:18px;white-space:pre-wrap}
  </style>
</head>
<body>
  <main class="wa-connect">
    <h1>Connect WhatsApp Business</h1>
    <p>Connect a WhatsApp Business Account to Amination AI.</p>
    <p>Only a business owner or administrator can start this process.</p>
    <p>Your Meta access token is exchanged and stored by the server. It is never displayed in this page.</p>
    <button id="wa-connect-button" type="button">Continue with Meta</button>
    <p id="wa-status" role="status" aria-live="polite">Ready when you are.</p>
    <p><a href="/dashboard">Return to dashboard</a></p>
  </main>
  <script
    src="{{ url_for('static', filename='meta-whatsapp-signup.js') }}"
    defer
    data-app-id="{{ meta_app_id }}"
    data-config-id="{{ config_id }}"
    data-graph-version="{{ graph_api_version }}"
    data-signup-version="{{ signup_version }}">
  </script>
</body>
</html>
""", encoding="utf-8")

js = Path("app/web/static/meta-whatsapp-signup.js")
if js.exists():
    raise SystemExit("meta-whatsapp-signup.js already exists; refusing to overwrite.")

js.write_text(r"""(() => {
  "use strict";

  const script = document.currentScript;
  const button = document.getElementById("wa-connect-button");
  const status = document.getElementById("wa-status");
  if (!script || !button || !status) return;

  const appId = script.dataset.appId;
  const configId = script.dataset.configId;
  const graphVersion = script.dataset.graphVersion;
  const signupVersion = script.dataset.signupVersion;

  let signupState = null;
  let authorizationCode = null;
  let sessionAssets = null;
  let submitting = false;

  const say = (message) => { status.textContent = message; };
  const csrfToken = () => {
    const item = document.cookie.split("; ").find(v => v.startsWith("assistant_csrf="));
    return item ? decodeURIComponent(item.substring("assistant_csrf=".length)) : "";
  };

  async function postJson(url, body) {
    const csrf = csrfToken();
    if (!csrf) throw new Error("Your security token is missing. Refresh the page and sign in again.");

    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf
      },
      body: JSON.stringify(body)
    });

    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
    return result;
  }

  function parseMetaMessage(event) {
    if (event.origin !== "https://www.facebook.com" &&
        event.origin !== "https://web.facebook.com" &&
        event.origin !== "https://m.facebook.com") return;

    if (typeof event.data !== "string") return;

    let message;
    try { message = JSON.parse(event.data); }
    catch (_) { return; }

    if (!message || message.type !== "WA_EMBEDDED_SIGNUP") return;

    if (message.event === "CANCEL") {
      say("Signup was cancelled. No connection was created.");
      button.disabled = false;
      return;
    }

    if (message.event === "ERROR") {
      say("Meta reported an error during signup. No connection was created.");
      button.disabled = false;
      return;
    }

    if (message.event !== "FINISH" &&
        message.event !== "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING") return;

    const data = message.data || {};
    const wabaId = data.waba_id || data.whatsapp_business_account_id || null;
    const phoneNumberId = data.phone_number_id || null;

    if (!wabaId || !phoneNumberId) {
      sessionAssets = null;
      say("Meta completed a signup event, but did not provide the account and phone IDs required by this Cloud API connection. Nothing was saved.");
      button.disabled = false;
      return;
    }

    sessionAssets = { waba_id: String(wabaId), phone_number_id: String(phoneNumberId) };
    completeIfReady();
  }

  async function completeIfReady() {
    if (submitting || !signupState || !authorizationCode || !sessionAssets) return;
    submitting = true;
    button.disabled = true;
    say("Verifying your WhatsApp account with Meta…");

    try {
      const result = await postJson("/api/integrations/meta/whatsapp/callback", {
        state: signupState,
        code: authorizationCode,
        waba_id: sessionAssets.waba_id,
        phone_number_id: sessionAssets.phone_number_id
      });

      say(
        "WhatsApp connection saved and verified.\\n" +
        "Display number: " + (result.display_phone_number || "Not supplied by Meta") +
        "\\nSender binding: not created yet. An administrator must complete the separate verified sender-binding step."
      );
    } catch (error) {
      say("Connection was not completed: " + error.message);
      button.disabled = false;
    } finally {
      submitting = false;
    }
  }

  window.addEventListener("message", parseMetaMessage);

  window.fbAsyncInit = function () {
    if (!window.FB) {
      say("Meta SDK did not load. Check your network and try again.");
      button.disabled = false;
      return;
    }

    window.FB.init({
      appId,
      autoLogAppEvents: true,
      xfbml: false,
      version: graphVersion
    });
    button.disabled = false;
    say("Meta is ready. Continue when you are ready.");
  };

  function loadSdk() {
    if (document.getElementById("facebook-jssdk")) return;
    const sdk = document.createElement("script");
    sdk.id = "facebook-jssdk";
    sdk.async = true;
    sdk.defer = true;
    sdk.crossOrigin = "anonymous";
    sdk.src = "https://connect.facebook.net/en_US/sdk.js";
    sdk.onerror = () => say("Could not load Meta's JavaScript SDK.");
    document.head.appendChild(sdk);
  }

  button.disabled = true;
  loadSdk();

  button.addEventListener("click", async () => {
    if (!window.FB) {
      say("Meta SDK is not ready yet.");
      return;
    }

    button.disabled = true;
    authorizationCode = null;
    sessionAssets = null;
    signupState = null;

    try {
      say("Preparing a secure, one-time signup session…");
      const attempt = await postJson("/api/integrations/meta/whatsapp/authorize", {
        consent_confirmed: true
      });
      signupState = attempt.state;

      const extras = {};
      if (signupVersion === "v5") extras.version = "v5";

      say("Opening Meta Embedded Signup…");
      window.FB.login((response) => {
        const code = response && response.authResponse && response.authResponse.code;
        if (!code) {
          say("Meta did not return an authorization code. No connection was created.");
          button.disabled = false;
          return;
        }
        authorizationCode = code;
        completeIfReady();
      }, {
        config_id: configId,
        response_type: "code",
        override_default_response_type: true,
        auth_type: "rerequest",
        extras
      });
    } catch (error) {
      say("Could not start signup: " + error.message);
      button.disabled = false;
    }
  });
})();
""", encoding="utf-8")

print("Created WhatsApp connection page and browser SDK handoff.")
