// Display aliases only: never use these labels as inventory update keys.
export function inventorySizeLabel(value) {
  const raw = String(value ?? "");
  const aliases = {
    "28": "28/S", S: "28/S",
    "30": "30/M", M: "30/M",
    "32": "32/L", L: "32/L",
    "34": "34/XL", XL: "34/XL",
    "36": "36/2XL", XXL: "36/2XL", "2XL": "36/2XL",
  };
  return aliases[raw.trim().toUpperCase()] || raw;
}
