// Preserve Unicode letters: Chinese color suffixes must not collapse to one URL.
export function productSlug(code) {
  return String(code).normalize("NFC").trim().toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
}
