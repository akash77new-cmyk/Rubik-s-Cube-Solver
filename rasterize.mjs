/**
 * Rasterise every SVG under assets/ to a matching high-resolution PNG.
 *
 *   node tools/rasterize.mjs <assetsDir> <size>
 *
 * Optional tooling - the app only ever loads the SVGs. The PNGs exist so the
 * README and any bitmap-only consumer get crisp art instead of the original
 * low-resolution files.
 */
import { readdir, mkdir } from "node:fs/promises";
import { join, extname, basename, dirname } from "node:path";

const [, , assetsDir = "assets", sizeArg = "512"] = process.argv;
const size = Number.parseInt(sizeArg, 10);

let sharp;
try {
  ({ default: sharp } = await import("sharp"));
} catch {
  console.error("sharp is not installed - run `npm install sharp` first. Skipping PNGs.");
  process.exit(0);
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (extname(entry.name).toLowerCase() === ".svg") yield full;
  }
}

let count = 0;
for await (const svgPath of walk(assetsDir)) {
  const outPath = join(dirname(svgPath), `${basename(svgPath, ".svg")}.png`);
  await mkdir(dirname(outPath), { recursive: true });
  await sharp(svgPath, { density: 384 })
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png({ compressionLevel: 9 })
    .toFile(outPath);
  count += 1;
}
console.log(`Rasterised ${count} SVG files to ${size}px PNG`);
