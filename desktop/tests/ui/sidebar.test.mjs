// Sidebar state logic — expanded/collapsed persistence, drawer breakpoint
// and keyboard navigation math (static/sidebar.js `logic`).
// Run: node --test desktop/tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const { logic } = require(path.join(root, 'static', 'sidebar.js'));

test('collapsed preference round-trips through storage', () => {
  assert.equal(logic.initialCollapsed(logic.storeValue(true)), true);
  assert.equal(logic.initialCollapsed(logic.storeValue(false)), false);
  assert.equal(logic.initialCollapsed(null), false);          // first run: expanded
  assert.equal(logic.initialCollapsed('garbage'), false);
});

test('the storage key holds a flag, never anything sensitive', () => {
  assert.equal(logic.COLLAPSE_KEY, 'sd.sidebar.collapsed');
  assert.equal(logic.storeValue(true), '1');
  assert.equal(logic.storeValue(false), '0');
});

test('narrow windows switch to the overlay drawer', () => {
  assert.equal(logic.isDrawer(480), true);
  assert.equal(logic.isDrawer(860), true);                    // boundary inclusive
  assert.equal(logic.isDrawer(861), false);
  assert.equal(logic.isDrawer(1280), false);
});

test('arrow keys move focus with wrap-around; Home/End jump', () => {
  assert.equal(logic.nextIndex('ArrowDown', 0, 5), 1);
  assert.equal(logic.nextIndex('ArrowDown', 4, 5), 0);        // wraps
  assert.equal(logic.nextIndex('ArrowUp', 0, 5), 4);          // wraps
  assert.equal(logic.nextIndex('Home', 3, 5), 0);
  assert.equal(logic.nextIndex('End', 0, 5), 4);
  assert.equal(logic.nextIndex('Tab', 2, 5), -1);             // untouched keys
  assert.equal(logic.nextIndex('ArrowDown', 0, 0), -1);       // empty list
});
