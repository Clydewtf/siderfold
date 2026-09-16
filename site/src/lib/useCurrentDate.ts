import { useEffect, useState } from 'react';

export function useCurrentDate(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const nextDay = new Date(now);
    nextDay.setHours(24, 0, 1, 0);
    const timer = window.setTimeout(() => setNow(new Date()), nextDay.getTime() - now.getTime());
    return () => window.clearTimeout(timer);
  }, [now]);

  return now;
}
