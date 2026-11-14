(() => {
  "use strict";

  const script = document.currentScript;
  const button = document.getElementById("wa-connect-button");
  const status = document.getElementById("wa-status");
  const consent = document.getElementById("wa-consent");
  if (!script || !button || !status || !consent) return;

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
    button.disabled = !consent.checked;
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
  consent.addEventListener("change", () => {
    button.disabled = !consent.checked || !window.FB;
  });
  loadSdk();

  button.addEventListener("click", async () => {
    if (!consent.checked) {
      say("Please confirm consent before connecting WhatsApp Business.");
      return;
    }
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
