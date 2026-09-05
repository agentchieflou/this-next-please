/*
 * Finding the dashboard, and starting one if there is none.
 *
 * This file is the whole of the shell's knowledge of the fleet, and it is deliberately small:
 * where `serve.json` is, how to ping, how to start the server, and how to read the event stream.
 * Everything else — what an agent's state means, whether it needs a person, what to say about it —
 * belongs to the server and is never reimplemented here. A shell with rules in it is a second
 * source of truth that will disagree with the tiles.
 */

import * as cp from "child_process";
import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";

export const CONTRACT = 1;

export interface ServeRecord {
  url: string;
  token: string;
  port: number;
  pid?: number;
  started?: string;
}

export interface Ping {
  ok: boolean;
  service: string;
  port: number;
  version: string;
  contract: number;
}

export interface Notification {
  repo: string;
  state: string;
  severity: "action" | "alert" | "info";
  ticket: string;
  title: string;
  body: string;
  at: string;
  key: string;
}

/** `$AGENTDATA_FLEET_DIR`, else `~/.agentdata/fleet` — the same rule the Python side uses. */
export function fleetDir(): string {
  const override = process.env.AGENTDATA_FLEET_DIR;
  if (override && override.trim()) {
    return override.trim();
  }
  return path.join(os.homedir(), ".agentdata", "fleet");
}

export function readServeRecord(): ServeRecord | undefined {
  try {
    const raw = fs.readFileSync(path.join(fleetDir(), "serve.json"), "utf8");
    const parsed = JSON.parse(raw) as ServeRecord;
    return parsed.port ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function get(url: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (c: Buffer) => chunks.push(c));
      response.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    });
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", reject);
  });
}

/** Is *our* dashboard on that port? Not "is the port open" — something else may hold it. */
export async function ping(port: number, timeoutMs = 2000): Promise<Ping | undefined> {
  try {
    const body = JSON.parse(await get(`http://127.0.0.1:${port}/api/ping`, timeoutMs)) as Ping;
    return body.service === "ad-fleet" ? body : undefined;
  } catch {
    return undefined;
  }
}

/** The record of a dashboard that is actually answering. A stale file is not a running server. */
export async function running(): Promise<ServeRecord | undefined> {
  const record = readServeRecord();
  if (!record) {
    return undefined;
  }
  return (await ping(record.port)) ? record : undefined;
}

/**
 * How to run the CLI here. `ad-fleet` is a console script and is frequently not on PATH — which is
 * the single most common way this package looks broken when it is merely unfound — so the module
 * form is the fallback rather than an afterthought.
 */
export function cliCommand(configured: string): { command: string; args: string[] } {
  if (configured.trim()) {
    const parts = configured.trim().split(/\s+/);
    return { command: parts[0], args: parts.slice(1) };
  }
  return { command: "ad-fleet", args: [] };
}

export function fallbackCommand(): { command: string; args: string[] } {
  return { command: process.platform === "win32" ? "py" : "python3", args: ["-m", "agentdata", "fleet"] };
}

/**
 * Start `ad-fleet serve`, detached, and wait for it to answer.
 *
 * Detached on purpose: closing the window that happened to launch it must not take the dashboard
 * down with it, and the other shells attach to the same server.
 */
export async function startServer(port: number, configured: string): Promise<ServeRecord> {
  const attempts = [cliCommand(configured), fallbackCommand()];
  let lastError = "";
  for (const attempt of attempts) {
    try {
      const child = cp.spawn(attempt.command, [...attempt.args, "serve", "--port", String(port)], {
        detached: true,
        stdio: "ignore",
        shell: process.platform === "win32"
      });
      child.unref();
    } catch (e) {
      lastError = String(e);
      continue;
    }
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      const record = await running();
      if (record) {
        return record;
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    lastError = `${attempt.command} did not start answering on ${port}`;
  }
  throw new Error(
    `could not start the fleet dashboard (${lastError}). ` +
      "Run `ad-fleet serve` in a terminal to see why, or set `fleet.command`."
  );
}

/**
 * Subscribe to the server's event stream and call back on notifications.
 *
 * A hand-rolled SSE reader rather than a dependency: the format is four lines and a blank, the
 * extension is meant to be installed from a `.vsix` with no `node_modules`, and every dependency
 * here is one more thing to audit for a corporate install.
 */
export class NotificationStream {
  private request?: http.ClientRequest;
  private stopped = false;
  private retry?: NodeJS.Timeout;

  constructor(
    private readonly record: ServeRecord,
    private readonly onNotification: (n: Notification) => void,
    private readonly onError?: (message: string) => void
  ) {}

  start(): void {
    if (this.stopped) {
      return;
    }
    const url = `http://127.0.0.1:${this.record.port}/api/events?t=${encodeURIComponent(this.record.token)}`;
    this.request = http.get(url, (response) => {
      response.setEncoding("utf8");
      let buffer = "";
      response.on("data", (chunk: string) => {
        buffer += chunk;
        let split = buffer.indexOf("\n\n");
        while (split >= 0) {
          this.frame(buffer.slice(0, split));
          buffer = buffer.slice(split + 2);
          split = buffer.indexOf("\n\n");
        }
      });
      response.on("end", () => this.reconnect());
    });
    this.request.on("error", (e) => {
      this.onError?.(String(e));
      this.reconnect();
    });
  }

  private frame(text: string): void {
    let event = "message";
    let data = "";
    for (const line of text.split("\n")) {
      if (line.startsWith("event: ")) {
        event = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        data += line.slice(6);
      }
    }
    if (event !== "notify" || !data) {
      return;
    }
    try {
      this.onNotification(JSON.parse(data) as Notification);
    } catch {
      /* a frame we cannot parse is a frame from a newer server; ignore it rather than die */
    }
  }

  private reconnect(): void {
    if (this.stopped) {
      return;
    }
    this.retry = setTimeout(() => this.start(), 3000);
  }

  dispose(): void {
    this.stopped = true;
    if (this.retry) {
      clearTimeout(this.retry);
    }
    this.request?.destroy();
  }
}

/** How many agents need a person right now, straight from the server's own answer. */
export async function needingHuman(record: ServeRecord): Promise<number> {
  try {
    const url = `http://127.0.0.1:${record.port}/api/fleet?t=${encodeURIComponent(record.token)}`;
    const body = JSON.parse(await get(url, 5000)) as { ok: boolean; repos: { needs_human: boolean }[] };
    return body.ok ? body.repos.filter((r) => r.needs_human).length : 0;
  } catch {
    return 0;
  }
}

export async function startAgent(record: ServeRecord, repo: string, ticket: string): Promise<{ ok: boolean; error?: string; hint?: string }> {
  return new Promise((resolve) => {
    const payload = JSON.stringify({ repo, ticket });
    const request = http.request(
      {
        host: "127.0.0.1",
        port: record.port,
        path: `/api/start?t=${encodeURIComponent(record.token)}`,
        method: "POST",
        timeout: 30000,
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) }
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (c: Buffer) => chunks.push(c));
        response.on("end", () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch {
            resolve({ ok: false, error: `the server answered ${response.statusCode}` });
          }
        });
      }
    );
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", (e) => resolve({ ok: false, error: String(e) }));
    request.write(payload);
    request.end();
  });
}

/** The repositories the fleet knows, so a command can offer the current folder if it is one. */
export async function repos(record: ServeRecord): Promise<{ repo: string; path: string }[]> {
  try {
    const url = `http://127.0.0.1:${record.port}/api/fleet?t=${encodeURIComponent(record.token)}`;
    const body = JSON.parse(await get(url, 5000)) as { ok: boolean; repos: { repo: string; path: string }[] };
    return body.ok ? body.repos : [];
  } catch {
    return [];
  }
}
