"use strict";

// npm packaging checks: version sync across manifests and CLI smoke tests.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const BIN = path.join(ROOT, "bin", "qasquad.js");

function readJson(...parts) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, ...parts), "utf8"));
}

const pkg = readJson("package.json");
const plugin = readJson("plugins", "qa-squad", ".claude-plugin", "plugin.json");
const marketplace = readJson(".claude-plugin", "marketplace.json");

test("versions match across package.json, plugin.json and marketplace.json", () => {
  const entry = marketplace.plugins.find((p) => p.name === plugin.name);
  assert.ok(entry, "marketplace.json must list the plugin");
  assert.equal(plugin.version, pkg.version, "plugin.json version");
  assert.equal(entry.version, pkg.version, "marketplace.json plugin version");
});

test("package.json is publishable", () => {
  assert.equal(pkg.name, "@salexcarvalho/qasquad");
  assert.equal(pkg.bin.qasquad, "bin/qasquad.js");
  assert.equal(pkg.publishConfig.access, "public");
  assert.equal(pkg.dependencies, undefined, "no runtime dependencies");
  assert.ok(fs.existsSync(path.join(ROOT, pkg.bin.qasquad)));
});

test("bin is executable and starts with a node shebang", () => {
  if (process.platform !== "win32") {
    fs.accessSync(BIN, fs.constants.X_OK);
  }
  assert.ok(fs.readFileSync(BIN, "utf8").startsWith("#!/usr/bin/env node"));
});

test("--help prints usage and exits 0", () => {
  const res = spawnSync(process.execPath, [BIN, "--help"], { encoding: "utf8" });
  assert.equal(res.status, 0);
  assert.match(res.stdout, /qasquad install/);
  assert.match(res.stdout, /--scope/);
});

test("--version prints the package version", () => {
  const res = spawnSync(process.execPath, [BIN, "--version"], { encoding: "utf8" });
  assert.equal(res.status, 0);
  assert.equal(res.stdout.trim(), pkg.version);
});

test("unknown command and invalid scope fail with exit code 2", () => {
  for (const args of [["bogus"], ["install", "--scope", "galaxy"]]) {
    const res = spawnSync(process.execPath, [BIN, ...args], { encoding: "utf8" });
    assert.equal(res.status, 2, args.join(" "));
  }
});

test("install without the claude CLI prints manual instructions", () => {
  const res = spawnSync(process.execPath, [BIN, "install"], {
    encoding: "utf8",
    env: { ...process.env, PATH: "" },
  });
  assert.equal(res.status, 1);
  assert.match(res.stderr, /\/plugin marketplace add salexcarvalho\/qasquad/);
  assert.match(res.stderr, /\/plugin install qa-squad@salexcarvalho-claude-plugins/);
});
