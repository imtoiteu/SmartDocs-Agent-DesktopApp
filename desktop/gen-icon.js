// Generate the source app icon (desktop/icon.png, 1024×1024) with zero
// dependencies — a flat SmartDocs-blue rounded square with a white "S" drawn
// on a pixel grid. `npx tauri icon desktop/icon.png` derives every platform
// format from it. Rerun only if the brand color changes.
"use strict";
const zlib = require("zlib");
const fs = require("fs");
const path = require("path");

const SIZE = 1024;
const BG = [0x4c, 0x8b, 0xf5, 0xff];   // --accent from the SmartDocs UI
const FG = [0xff, 0xff, 0xff, 0xff];

// 5×7 "S" glyph on a coarse grid, scaled up.
const GLYPH = [
  "01110",
  "10001",
  "10000",
  "01110",
  "00001",
  "10001",
  "01110",
];
const CELL = 96;                        // glyph cell size in pixels
const GW = 5 * CELL, GH = 7 * CELL;
const GX = (SIZE - GW) / 2, GY = (SIZE - GH) / 2;
const RADIUS = 180;                     // rounded-corner radius

function inRoundedSquare(x, y) {
  const r = RADIUS, m = SIZE - 1;
  const cx = x < r ? r : x > m - r ? m - r : x;
  const cy = y < r ? r : y > m - r ? m - r : y;
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

function glyphAt(x, y) {
  const gx = Math.floor((x - GX) / CELL), gy = Math.floor((y - GY) / CELL);
  return gy >= 0 && gy < 7 && gx >= 0 && gx < 5 && GLYPH[gy][gx] === "1";
}

const raw = Buffer.alloc(SIZE * (SIZE * 4 + 1));
for (let y = 0; y < SIZE; y++) {
  const row = y * (SIZE * 4 + 1);
  raw[row] = 0;                          // PNG filter: None
  for (let x = 0; x < SIZE; x++) {
    const px = inRoundedSquare(x, y) ? (glyphAt(x, y) ? FG : BG) : [0, 0, 0, 0];
    px.forEach((v, i) => { raw[row + 1 + x * 4 + i] = v; });
  }
}

function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crcTable = [];
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crcTable[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of body) crc = crcTable[(crc ^ b) & 0xff] ^ (crc >>> 8);
  const crcBuf = Buffer.alloc(4); crcBuf.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([len, body, crcBuf]);
}

const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0); ihdr.writeUInt32BE(SIZE, 4);
ihdr[8] = 8; ihdr[9] = 6;               // 8-bit RGBA

const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk("IHDR", ihdr),
  chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
  chunk("IEND", Buffer.alloc(0)),
]);

const out = path.join(__dirname, "icon.png");
fs.writeFileSync(out, png);
console.log(`wrote ${out} (${png.length} bytes)`);
