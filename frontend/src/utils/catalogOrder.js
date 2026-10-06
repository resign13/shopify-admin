const rank = (value) => value != null && Number.isFinite(Number(value))
  ? Number(value) : Number.MAX_SAFE_INTEGER;

export function compareProductCategories(left, right) {
  return rank(left?.categorySortOrder) - rank(right?.categorySortOrder)
    || rank(left?.categoryId) - rank(right?.categoryId);
}

export function sortProductsByCategory(products, categories = []) {
  // The full category list is already ordered by the backend. It also supports
  // older product responses which do not contain category rank metadata.
  const positions = new Map(categories.map((category, index) => [category.key, index]));
  return [...products].sort((left, right) => {
    const leftPosition = positions.get(left.categoryKey);
    const rightPosition = positions.get(right.categoryKey);
    if (leftPosition != null || rightPosition != null) {
      return (leftPosition ?? Number.MAX_SAFE_INTEGER) - (rightPosition ?? Number.MAX_SAFE_INTEGER);
    }
    return compareProductCategories(left, right);
  });
}
