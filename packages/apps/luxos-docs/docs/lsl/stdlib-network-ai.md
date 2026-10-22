# LSL standard library: HTTP, servers and AI

`http`, `requests`, `httpserver` (and `lsl server`) and `ai` (`aikit`). The HTTP clients run
the system `/usr/bin/curl` by direct `execve` with its configuration on **stdin**, so request
bodies, Authorization headers and other secrets never appear in the process argv. Plain HTTP is
allowed only for numeric loopback `127.0.0.1` / `[::1]`; everything else requires HTTPS
(TLS 1.2+).

## requests — Python-style HTTP client

`load requests`. Every request returns a `Response`.

| Function | Description |
|---|---|
| `requests.get(url, headers=None, timeout=None)` | GET |
| `requests.post/put/patch/delete(url, data=None, headers=None, timeout=None)` | request with a body; List/Dictionary data is encoded as JSON (`Content-Type: application/json` added unless given) |
| `requests.head(url, headers=None, timeout=None)` | HEAD without a response body |
| `requests.request(method, url, data=None, headers=None, timeout=None)` | any method (lowercase names accepted) |
| `requests.post_stream(url, data, headers, timeout, on_chunk, method="POST")` | stream the body to `on_chunk(text)`, return a Response with the accumulated body |
| `Response(status, text)` | fields `status` (0 = transport failure), `status_code` (alias), `text`, `ok` (200–299); methods `json()`, `raise_for_status()` |

`headers` is a Dictionary (max 256 entries, not modified). Redirects are not followed.
`timeout` 1..3600 s, default 60. Errors: `ConnectionError` (status 0), `HTTPStatusError`
(status outside 200–299 in `raise_for_status`), `JsonError` (`json()` on invalid body),
`HTTPError` (invalid URL, header, method, timeout, body too large).

```lsl
load requests

response = requests.get("https://api.example.com/data")
if response.ok:
    print response.json()["items"]
else:
    print "HTTP", response.status
end

created = requests.post("https://api.example.com/items", {"name": "LSL"})
call created.raise_for_status()
```

## http — low-level client

`load http`. Returns a Dictionary `{"status": Int, "text": String, "ok": Bool}` (status `0`
means transport failure, the message is in `text`).

| Function | Description |
|---|---|
| `http.get(url, headers=None, timeout=None)` | GET |
| `http.post(url, body, headers, timeout, method="POST")` | POST (or another method); List/Dictionary body is JSON-encoded |
| `http.post_stream(url, body, headers, timeout, on_chunk, method="POST")` | streamed POST, `on_chunk(text)` per piece |
| `http.get_with(curl_path, ...)`, `post_with`, `post_stream_with` | same with an injected transport program (for tests) |
| `http.validate_url(url)`, `http.method_name(method)` | validation helpers |

Limits: URL 1..8192 bytes, safe ASCII, no user-info or fragment; response max 16 MiB; request
body max 4 MB encoded. Errors: `HTTPError`.

## httpserver — bounded HTTP/1.1 server

`load httpserver`. Syscall-only transport for Linux x86-64. Static files are opened relative
to one pinned directory handle with `openat2(RESOLVE_BENEATH|NO_MAGICLINKS|NO_SYMLINKS)`, so
path and symlink escapes fail in the kernel.

| Function | Description |
|---|---|
| `httpserver.serve(handler, address, port, max_requests)` | call `handler(request)` for each request (`0` = no limit) |
| `httpserver.serve_static(root, address, port, max_requests)` | serve GET/HEAD files from the pinned root |
| `httpserver.serve_static_tls(root, address, port, cert, key, max_requests)` | static HTTPS through the system nginx/OpenSSL; `max_requests` must be `0` |
| `httpserver.serve_workers(handler, address, port, workers, max_requests)` | worker pool of 1–64 threads (protect shared state with `lock`/atomics); returns the number of requests served |
| `httpserver.serve_listener(...)`, `serve_listener_workers(...)` | serve an existing listener |
| `httpserver.set_body_limit(n)` / `body_limit()` | request body limit (default unlimited) |
| `httpserver.stream_write(stream, data)` | send a String/ByteArray chunk; `False` when the client closed |
| `httpserver.sse_event(stream, data, event=None)` | send one Server-Sent Event |

The handler receives `{"ok", "method", "target", "version", "headers" (lowercase names),
"body" (ByteArray), "body_text"}` and returns e.g. `{"body": "text", "content_type": "text/plain;
charset=utf-8"}`, `{"status": 404, "body": "not found"}` or `{"content_type":
"text/event-stream", "stream": function(stream)}`. An error in the handler becomes `500`.
Invalid methods/targets/header values get `400`; repeated `Content-Length`,
`Transfer-Encoding` and `Host` are rejected. The plain `serve` accept loop is single-threaded.
Errors: `ServerError` (e.g. port in use).

```lsl
load httpserver

function handler(request):
    return {"body": request["method"] + " " + request["target"] + chr(10)}
end

call httpserver.serve(handler, "127.0.0.1", 8080, 0)
```

### lsl server

```bash
lsl server --dir ./public --bind 127.0.0.1 --port 8080
lsl server --dir ./public --tls-cert cert.pem --tls-key key.pem
lsl server --help          # defaults and all options (--once, --max-requests N)
```

## ai — OpenAI-compatible chat with tools

`load ai` (bundled; in 0.10.2 at the level of `aikit` 1.2.0). The same API is available as
the separately updatable registry package `aikit`: `lsl install ai` / `lsl update ai` install
`aikit`, and since 0.9.1 `load ai` uses the per-user `aikit.lsl` when it is newer than the
bundled module. On older LSL write `load aikit as ai`.

| Call | Result |
|---|---|
| `ai.request(endpoint, token, model, messages, options)` | decoded provider JSON (Dictionary); raises on HTTP errors |
| `ai.stream(endpoint, token, model, messages, options, on_event)` | calls `on_event(text)` for each content delta; returns `{"events", "tool_calls", "reasoning", "reasoning_events"}` (not the answer – assemble the text from the callbacks) |
| `ai.stream_text(text, on_event, cancel=None)` | parse already loaded SSE text, no network |
| `ai.content(response)` | `choices[0].message.content` (String or `None`) |
| `ai.tool_calls(response)` | List of `{id, name, arguments}` (`arguments` is a JSON String) |
| `ai.tool_message(id, name, result)` | message with role `tool` for the follow-up request |
| `ai.reasoning(response)` | model reasoning text or `None` |
| `ai.decode_response(response)` | decode an `http` result Dictionary |
| `ai.help()` / `ai.version` | short help / library version |

`messages` is a List (max 4096) of `{"role", "content"}`. Options (unknown keys are rejected):
`temperature` (0–2), `max_tokens`, `timeout` (1–3600, default 60), `retries` (0–10, for
transport errors and HTTP 408/429/5xx; in a stream only before the first text callback),
`cancel` (function → `AICancelled`), `transport_chunk`, `tools` (1–128 OpenAI-style function
definitions), `tool_choice` (`auto`, `none`, `required` or a specific function),
`on_tool_call`, `stream_reliability` (`live` or `transactional`), `reasoning`,
`reasoning_effort`, `on_reasoning`. Errors: `AIProviderError`, `AICancelled`.

```lsl
load ai
load env

token = env.require("LUX_AI_API")
model = env.get("LUX_AI_MODEL", "flash")
messages = [{"role": "user", "content": "Introduce yourself in one sentence."}]
response = ai.request("https://api.lux-ai.cz/v1/chat/completions", token, model, messages,
                      {"max_tokens": 500, "temperature": 0.7, "timeout": 60})
printl "Answer: {ai.content(response)}"
```

Tool calling: pass `{"tools": tools, "tool_choice": "required"}`, read
`ai.tool_calls(response)`, append the assistant message and one
`ai.tool_message(call["id"], call["name"], result)` per call, then repeat the request. Keep the
API key in `.env` (read with `load env`); the library does not store it and it is not passed in
argv. See the full streaming chatbot in [examples.md](examples.md).
