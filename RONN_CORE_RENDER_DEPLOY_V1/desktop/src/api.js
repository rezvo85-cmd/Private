const id = (key, prefix) => {
  let value = localStorage.getItem(key);
  if (!value) {
    value = (crypto.randomUUID ? crypto.randomUUID() : prefix + Date.now() + Math.random().toString(36).slice(2))
      .replace(/[^A-Za-z0-9_-]/g, "");
    localStorage.setItem(key, value);
  }
  return value;
};

export class RonnApi {
  constructor(baseUrl) {
    this.baseUrl = String(baseUrl || "").replace(/\/+$/, "");
    this.clientId = id("ronnDesktopClient", "desktop-");
    this.deviceId = id("ronnDesktopDevice", "device-");
  }

  headers(extra = {}) {
    return {
      "X-RONN-Client": this.clientId,
      "X-RONN-Device": this.deviceId,
      "X-RONN-Account": "ronn_primary",
      ...extra,
    };
  }

  async request(path, { method = "GET", body = null } = {}) {
    if (!this.baseUrl) throw new Error("Enter your RONN Core URL.");
    const response = await window.ronnDesktop.core.request({
      baseUrl: this.baseUrl,
      path,
      method,
      headers: this.headers(body == null ? {} : { "Content-Type": "application/json" }),
      body,
    });
    if (!response.ok) {
      const detail = typeof response.data === "object" ? response.data?.detail : response.data;
      throw new Error(detail || `RONN Core returned HTTP ${response.status}.`);
    }
    return response.data;
  }

  unlock(secret) {
    return this.request("/api/v1/owner/unlock", {
      method: "POST",
      body: {
        secret,
        device_id: this.deviceId,
        device_name: "RONN Desktop",
        platform: navigator.platform || "desktop",
        app_version: "RONN-DESKTOP-1",
        return_token: false,
      },
    });
  }
}
