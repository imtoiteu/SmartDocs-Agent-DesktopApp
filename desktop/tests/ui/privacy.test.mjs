// Local-only privacy UI state — behavioral tests for the exact computation
// the settings panel and the top-bar chip render from (static/privacy-ui.js).
// Run: node --test desktop/tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const { compute } = require(path.join(root, 'static', 'privacy-ui.js'));

const CLOUD = { processing_mode: 'cloud_allowed', env_locked: false, cloud_ack: true };
const LOCAL = { processing_mode: 'local_only', env_locked: false, cloud_ack: true };

test('switching to Local only immediately flips every control state', () => {
  const before = compute(CLOUD);
  const after = compute(LOCAL);
  assert.equal(before.btnLabel, 'Switch to Local only');
  assert.equal(after.btnLabel, 'Allow cloud processing…');   // label changes
  assert.equal(before.ariaPressed, 'false');
  assert.equal(after.ariaPressed, 'true');                   // aria-pressed semantics
  assert.notEqual(before.badgeClass, after.badgeClass);      // visible state change
  assert.match(after.statusText, /Local only/);              // shows Local only active
});

test('top-bar chip stays synchronized with the settings state', () => {
  assert.match(compute(LOCAL).chipText, /Local only/);
  assert.match(compute(CLOUD).chipText, /Cloud/);
});

test('cloud-provider controls are unavailable in Local only', () => {
  assert.equal(compute(LOCAL).providerControlsDisabled, true);
  assert.equal(compute(CLOUD).providerControlsDisabled, false);
});

test('a click means the OPPOSITE mode (never re-submits the current one)', () => {
  assert.equal(compute(CLOUD).enableCloudOnClick, false);    // → switch to local
  assert.equal(compute(LOCAL).enableCloudOnClick, true);     // → back to cloud
});

test('already-accepted disclosure is not asked again', () => {
  assert.equal(compute({ ...LOCAL, cloud_ack: false }).needsAckOnEnable, true);
  assert.equal(compute({ ...LOCAL, cloud_ack: true }).needsAckOnEnable, false);
});

test('env-locked ALLOW_CLOUD disables the toggle and explains why', () => {
  const ui = compute({ ...CLOUD, env_locked: true });
  assert.equal(ui.btnDisabled, true);
  assert.match(ui.note, /ALLOW_CLOUD/);
});

test('uses translations when available, falls back otherwise', () => {
  const dict = { settings_disable_cloud: 'Chuyển sang Chỉ cục bộ' };
  const ui = compute(CLOUD, (k) => dict[k] || null);
  assert.equal(ui.btnLabel, 'Chuyển sang Chỉ cục bộ');
});
