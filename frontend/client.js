/* Thin wrapper around the backend API. Every method returns parsed JSON or
   throws an Error whose message is the server's `detail` string. */
const API = (() => {
  const BASE = "/api";

  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }

    const res = await fetch(BASE + path, opts);
    if (res.status === 204) return null;

    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!res.ok) {
      const detail =
        data && typeof data === "object" && data.detail
          ? data.detail
          : typeof data === "string" && data
          ? data
          : `Request failed (${res.status})`;
      throw new Error(detail);
    }
    return data;
  }

  return {
    health: () => request("GET", "/health"),
    listProjects: () => request("GET", "/projects"),
    addProject: (url) => request("POST", "/projects", { url }),
    getProject: (id) => request("GET", `/projects/${id}`),
    deleteProject: (id) => request("DELETE", `/projects/${id}`),
    getMap: (id) => request("GET", `/projects/${id}/map`),
    buildMap: (id) => request("POST", `/projects/${id}/map`),
    listBranches: (id) => request("GET", `/projects/${id}/branches`),
    compare: (id, base, compare) =>
      request("POST", `/projects/${id}/compare`, { base, compare }),
    review: (id, base, compare) =>
      request("POST", `/projects/${id}/review`, { base, compare }),
  };
})();