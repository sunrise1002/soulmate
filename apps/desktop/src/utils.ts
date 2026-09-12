export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function percentage(value: number): string {
  return `${String(Math.round(value * 100))}%`;
}

export function humanizeKey(value: string): string {
  return value
    .split(".")
    .map((part) => part.replaceAll("_", " "))
    .join(" · ");
}

export function preferenceLabel(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude < 0.15) return "Neutral";
  const direction = value > 0 ? "Prefers" : "Avoids";
  if (magnitude >= 0.75) return `Strongly ${direction.toLowerCase()}`;
  if (magnitude >= 0.4) return direction;
  return `Slightly ${direction.toLowerCase()}`;
}
