import { useLayoutEffect, useRef } from 'react';
import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useGsapEntrance } from './useGsapEntrance';

const mocks = vi.hoisted(() => ({
  fromTo: vi.fn(),
  matchMediaAdd: vi.fn(),
  matchMediaRevert: vi.fn(),
  scrollTriggerCreate: vi.fn(),
  set: vi.fn()
}));

vi.mock('@gsap/react', () => ({
  useGSAP: (
    callback: () => void | (() => void),
    config: { dependencies?: readonly unknown[] }
  ) => useLayoutEffect(callback, config.dependencies),
}));

vi.mock('gsap', () => ({
  default: {
    fromTo: mocks.fromTo,
    matchMedia: () => ({
      add: (_conditions: unknown, callback: (context: { conditions: Record<string, boolean> }) => void) => {
        mocks.matchMediaAdd();
        callback({ conditions: { desktop: true, motion: true, reducedMotion: false } });
      },
      revert: mocks.matchMediaRevert
    }),
    registerPlugin: vi.fn(),
    set: mocks.set,
    utils: {
      toArray: <T,>(values: Iterable<T> | ArrayLike<T>) => Array.from(values)
    }
  }
}));

vi.mock('gsap/ScrollTrigger', () => ({
  ScrollTrigger: { create: mocks.scrollTriggerCreate }
}));

function MotionFixture({ reduceMotion }: { reduceMotion: boolean }) {
  const scope = useRef<HTMLElement>(null);
  useGsapEntrance(scope, 'home', reduceMotion);

  return (
    <section ref={scope}>
      <article data-motion-card>Card</article>
      <div data-motion-media>Media</div>
      <div data-motion-pin><h2 data-motion-pin-title>Title</h2></div>
    </section>
  );
}

describe('useGsapEntrance', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reverts active effects and renders static content when local reduced motion is enabled', () => {
    const view = render(<MotionFixture reduceMotion={false} />);

    expect(mocks.fromTo).toHaveBeenCalledTimes(2);
    expect(mocks.scrollTriggerCreate).toHaveBeenCalledTimes(1);

    view.rerender(<MotionFixture reduceMotion />);

    expect(mocks.matchMediaRevert).toHaveBeenCalledTimes(1);
    expect(mocks.matchMediaAdd).toHaveBeenCalledTimes(1);
    expect(mocks.fromTo).toHaveBeenCalledTimes(2);
    expect(mocks.scrollTriggerCreate).toHaveBeenCalledTimes(1);
    expect(mocks.set).toHaveBeenCalledTimes(2);
  });
});
