import { Star } from 'lucide-react';

export function FavoriteToggle({
  itemName,
  isFavorite,
  onToggle,
  className = ''
}: {
  itemName: string;
  isFavorite: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const label = isFavorite
    ? `Удалить ${itemName} из избранного`
    : `Добавить ${itemName} в избранное`;

  return (
    <button
      type="button"
      aria-pressed={isFavorite}
      aria-label={label}
      onClick={onToggle}
      className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-ink/10 bg-white/80 text-ink transition hover:bg-ink/5 ${className}`}
    >
      <Star className={`h-5 w-5 ${isFavorite ? 'fill-amber-400 text-amber-400' : ''}`} aria-hidden="true" />
    </button>
  );
}
