#!/usr/bin/env node
"use strict";

// QA Squad installer. Thin wrapper around the `claude plugin` CLI.
// Zero dependencies; never builds shell command strings.

const { spawnSync } = require("node:child_process");
const path = require("node:path");

const MARKETPLACE_SOURCE = "salexcarvalho/qasquad";
const MARKETPLACE_NAME = "salexcarvalho-claude-plugins";
const PLUGIN_NAME = "qa-squad";
const PLUGIN_ID = `${PLUGIN_NAME}@${MARKETPLACE_NAME}`;
const SCOPES = ["user", "project", "local"];

const pkg = require(path.join(__dirname, "..", "package.json"));

const HELP = `qasquad ${pkg.version}

Install the QA Squad plugin for Claude Code.

Usage:
  qasquad install [--scope user|project|local]
  qasquad uninstall [--scope user|project|local]
  qasquad --help
  qasquad --version

Commands:
  install     Add the ${MARKETPLACE_NAME} marketplace and install ${PLUGIN_NAME}
  uninstall   Uninstall ${PLUGIN_NAME} (the marketplace stays registered)

Options:
  --scope     Installation scope (default: user)
  -h, --help  Show this help
  -v, --version  Show the version

Requires the Claude Code CLI (\`claude\`) on your PATH.
`;

function manualInstructions(scope) {
  const lines = [
    "Run these commands inside a Claude Code session instead:",
    "",
    `  /plugin marketplace add ${MARKETPLACE_SOURCE}`,
    `  /plugin install ${PLUGIN_ID}`,
  ];
  if (scope && scope !== "user") {
    lines.push("", `Then choose the "${scope}" scope when prompted.`);
  }
  return lines.join("\n");
}

function claudeAvailable() {
  const res = spawnSync("claude", ["--version"], { stdio: "ignore" });
  return !res.error && res.status === 0;
}

function runClaude(args) {
  console.log(`$ claude ${args.join(" ")}`);
  const res = spawnSync("claude", args, { stdio: "inherit" });
  if (res.error) {
    console.error(`Failed to run claude: ${res.error.message}`);
    return 1;
  }
  return res.status === null ? 1 : res.status;
}

function parseScope(args) {
  let scope = "user";
  const rest = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--scope") {
      scope = args[++i];
    } else if (a.startsWith("--scope=")) {
      scope = a.slice("--scope=".length);
    } else {
      rest.push(a);
    }
  }
  if (!SCOPES.includes(scope)) {
    return { error: `Invalid --scope "${scope}". Use one of: ${SCOPES.join(", ")}.` };
  }
  if (rest.length > 0) {
    return { error: `Unknown argument: ${rest[0]}` };
  }
  return { scope };
}

function requireClaude(scope) {
  if (claudeAvailable()) return true;
  console.error("The Claude Code CLI (`claude`) was not found on your PATH.");
  console.error("Install it from https://code.claude.com and try again.\n");
  console.error(manualInstructions(scope));
  return false;
}

function install(args) {
  const parsed = parseScope(args);
  if (parsed.error) return fail(parsed.error);
  if (!requireClaude(parsed.scope)) return 1;

  let code = runClaude(["plugin", "marketplace", "add", MARKETPLACE_SOURCE, "--scope", parsed.scope]);
  if (code !== 0) {
    console.error("\nCould not add the marketplace.\n");
    console.error(manualInstructions(parsed.scope));
    return code;
  }
  code = runClaude(["plugin", "install", PLUGIN_ID, "--scope", parsed.scope]);
  if (code !== 0) {
    console.error("\nCould not install the plugin.\n");
    console.error(manualInstructions(parsed.scope));
    return code;
  }
  console.log(`\nQA Squad installed (scope: ${parsed.scope}). Start Claude Code and run /qa-squad:qa-status.`);
  return 0;
}

function uninstall(args) {
  const parsed = parseScope(args);
  if (parsed.error) return fail(parsed.error);
  if (!requireClaude(parsed.scope)) return 1;
  return runClaude(["plugin", "uninstall", PLUGIN_ID, "--scope", parsed.scope]);
}

function fail(message) {
  console.error(`${message}\n`);
  console.error(HELP);
  return 2;
}

function main(argv) {
  const [cmd, ...rest] = argv;
  switch (cmd) {
    case undefined:
    case "-h":
    case "--help":
    case "help":
      console.log(HELP);
      return 0;
    case "-v":
    case "--version":
    case "version":
      console.log(pkg.version);
      return 0;
    case "install":
      return install(rest);
    case "uninstall":
      return uninstall(rest);
    default:
      return fail(`Unknown command: ${cmd}`);
  }
}

process.exitCode = main(process.argv.slice(2));
