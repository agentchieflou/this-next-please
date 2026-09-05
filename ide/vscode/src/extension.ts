/*
 * A shell, and nothing more.
 *
 * It hosts the `ad-fleet serve` page in a view, keeps a status-bar count, and turns the server's
 * own notifications into VS Code ones. There is no rule logic here: which agents need a person,
 * what to say about them and when to stay quiet are all decided by `agentdata/fleet/notify.py`,
 * and a second implementation in TypeScript would eventually disagree with the tiles it sits next
 * to. The only inbound kinds this file acts on are `notify` frames and the version on `ping`.
 */

import * as vscode from "vscode";

import {
  CONTRACT,
  Notification,
  NotificationStream,
  ServeRecord,
  needingHuman,
  ping,
  repos,
  running,
  startAgent,
  startServer
} from "./fleet";

let record: ServeRecord | undefined;
let stream: NotificationStream | undefined;
let status: vscode.StatusBarItem;
let provider: DashboardView | undefined;

function settings() {
  const config = vscode.workspace.getConfiguration("fleet");
  return {
    port: config.get<number>("port", 8765),
    command: config.get<string>("command", ""),
    notifications: config.get<boolean>("notifications", true)
  };
}

/** Attach to a running dashboard, or start one. Returns undefined and explains if it cannot. */
async function connect(startIfMissing: boolean): Promise<ServeRecord | undefined> {
  record = await running();
  if (!record && startIfMissing) {
    const s = settings();
    try {
      record = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: "Starting the fleet dashboard…" },
        () => startServer(s.port, s.command)
      );
    } catch (e) {
      vscode.window.showErrorMessage(String(e instanceof Error ? e.message : e));
      return undefined;
    }
  }
  if (record) {
    await checkVersion(record);
    listen(record);
    void refreshStatus();
  }
  return record;
}

/**
 * One balloon when the shell and the server are different ages, and never again for that pair.
 *
 * A shell built against an older contract can quietly mis-render rather than fail, which is the
 * kind of bug that gets blamed on the dashboard for a week.
 */
let warnedAbout = "";
async function checkVersion(r: ServeRecord): Promise<void> {
  const answer = await ping(r.port);
  if (!answer || answer.contract === CONTRACT || warnedAbout === answer.version) {
    return;
  }
  warnedAbout = answer.version;
  const update = "How do I update?";
  const choice = await vscode.window.showWarningMessage(
    `The fleet dashboard speaks contract ${answer.contract} and this extension speaks ${CONTRACT}. ` +
      "Some of the view may not work.",
    update
  );
  if (choice === update) {
    void vscode.window.showInformationMessage(
      "Update the CLI with `ad-update`, and the extension from the release it came from."
    );
  }
}

function listen(r: ServeRecord): void {
  stream?.dispose();
  stream = new NotificationStream(r, onNotification);
  stream.start();
}

function onNotification(n: Notification): void {
  void refreshStatus();
  if (!settings().notifications || n.severity === "info") {
    return;
  }
  const open = "Show";
  const show = n.severity === "alert" ? vscode.window.showErrorMessage : vscode.window.showWarningMessage;
  void show(`${n.title} — ${n.body}`, open).then((choice) => {
    if (choice === open) {
      void vscode.commands.executeCommand("fleet.open", n.repo);
    }
  });
}

async function refreshStatus(): Promise<void> {
  if (!record) {
    status.hide();
    return;
  }
  const count = await needingHuman(record);
  status.text = count > 0 ? `$(warning) fleet ${count}` : "$(server) fleet";
  status.tooltip = count > 0 ? `${count} agent(s) need you` : "The fleet is running";
  status.backgroundColor = count > 0 ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
  status.show();
}

/**
 * The view: an iframe on the dashboard, and nothing else.
 *
 * `#tile=<repo>` is the whole of the shell's vocabulary for "show me that one" — the same anchor
 * the Windows toasts use, so there is one way to focus a tile and not two.
 */
class DashboardView implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    void this.render();
  }

  async render(anchor = ""): Promise<void> {
    if (!this.view) {
      return;
    }
    const r = record ?? (await running());
    if (!r) {
      this.view.webview.html = notRunningHtml();
      return;
    }
    this.view.webview.html = frameHtml(`${r.url}${anchor ? `#tile=${encodeURIComponent(anchor)}` : ""}`);
  }

  reveal(): void {
    this.view?.show?.(true);
  }
}

function frameHtml(url: string): string {
  // `allow-same-origin` is what lets the page keep its own localStorage and open its event stream.
  // The frame is a loopback URL the user's own machine is serving; there is no third party here.
  return `<!doctype html>
<html><head><meta charset="utf-8">
<style>html,body,iframe{margin:0;padding:0;border:0;width:100%;height:100vh;display:block}</style>
</head><body>
<iframe src="${url}" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
</body></html>`;
}

function notRunningHtml(): string {
  return `<!doctype html>
<html><head><meta charset="utf-8">
<style>body{font:13px var(--vscode-font-family);color:var(--vscode-foreground);padding:1rem}
code{font-family:var(--vscode-editor-font-family)}</style>
</head><body>
<p>No fleet dashboard is running.</p>
<p>Run <code>ad-fleet serve</code>, or use <b>Fleet: Open the dashboard</b> to start one.</p>
</body></html>`;
}

export function activate(context: vscode.ExtensionContext): void {
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "fleet.open";
  context.subscriptions.push(status);

  provider = new DashboardView();
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("fleet.dashboard", provider, {
      webviewOptions: { retainContextWhenHidden: true }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("fleet.open", async (repo?: string) => {
      if (!(await connect(true))) {
        return;
      }
      await provider?.render(typeof repo === "string" ? repo : "");
      provider?.reveal();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("fleet.reload", async () => {
      record = undefined;
      await connect(false);
      await provider?.render();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("fleet.start", async () => {
      const r = await connect(true);
      if (!r) {
        return;
      }
      const known = await repos(r);
      if (known.length === 0) {
        void vscode.window.showWarningMessage(
          "No repositories are registered. Run `ad-fleet repo add <path>` first."
        );
        return;
      }
      // The open folder, if the fleet knows it — the common case is "this project, this ticket".
      const here = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath?.replace(/\\/g, "/").toLowerCase();
      const mine = known.find((k) => k.path.toLowerCase() === here);
      const repo =
        mine?.repo ??
        (await vscode.window.showQuickPick(known.map((k) => k.repo), { placeHolder: "Which repository?" }));
      if (!repo) {
        return;
      }
      const ticket = await vscode.window.showInputBox({
        prompt: `Ticket key to work in ${repo}`,
        placeHolder: "RDSD-101",
        validateInput: (v) => (/^[A-Za-z][A-Za-z0-9_]+-\d+$/.test(v.trim()) ? undefined : "keys look like RDSD-101")
      });
      if (!ticket) {
        return;
      }
      const answer = await startAgent(r, repo, ticket.trim().toUpperCase());
      if (answer.ok) {
        await provider?.render(repo);
        provider?.reveal();
      } else {
        // The server's own refusal, verbatim: it already says why and what would fix it, and
        // rewording it here would give the operator two different explanations of one rule.
        void vscode.window.showWarningMessage(`${answer.error ?? "refused"}${answer.hint ? ` — ${answer.hint}` : ""}`);
      }
    })
  );

  void connect(false);
}

export function deactivate(): void {
  stream?.dispose();
  stream = undefined;
}
