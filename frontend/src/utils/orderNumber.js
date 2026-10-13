// Shortening is presentation-only. Never send this value to the API.
export function orderNumberParts(value, limit = 28) {
  const full = String(value ?? "");
  const match = /^(PO[0-9]{4}-)([\s\S]+)(-[0-9]{6,})$/.exec(full);
  if (!match) return { prefix: "", name: full, suffix: "", full };
  const [, prefix, originalName, suffix] = match;
  const chars = typeof Intl.Segmenter === "function"
    ? Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(originalName), x => x.segment)
    : Array.from(originalName);
  const budget = Math.max(0, limit - prefix.length - suffix.length);
  const name = chars.length > budget ? chars.slice(0, Math.max(0, budget - 3)).join("") + "..." : originalName;
  return { prefix, name, suffix, full };
}
