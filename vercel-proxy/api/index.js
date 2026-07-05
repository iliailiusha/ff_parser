const TELEGRAM_API = "https://api.telegram.org";

export default async function handler(request) {
  const url = new URL(request.url);
  const botPath = url.pathname.replace(/^\/api\//, "");
  const targetUrl = `${TELEGRAM_API}/${botPath}${url.search}`;

  const headers = {};
  const ct = request.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;

  let body;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.text();
  }

  const resp = await fetch(targetUrl, { method: request.method, headers, body: body || undefined });

  return new Response(resp.body, {
    status: resp.status,
    headers: {
      ...Object.fromEntries(resp.headers),
      "Access-Control-Allow-Origin": "*",
    },
  });
}

export const config = {
  runtime: "edge",
};
