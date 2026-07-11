import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import type { RefObject } from 'react';

gsap.registerPlugin(ScrollTrigger, useGSAP);

export function useGsapEntrance(
  scope: RefObject<HTMLElement | null>,
  activeKey: string,
  reduceMotion: boolean
) {
  useGSAP(
    () => {
      const scopeElement = scope.current;
      if (!scopeElement) {
        return;
      }

      if (reduceMotion) {
        const cards = gsap.utils.toArray<HTMLElement>(
          scopeElement.querySelectorAll<HTMLElement>('[data-motion-card]')
        );
        const media = gsap.utils.toArray<HTMLElement>(
          scopeElement.querySelectorAll<HTMLElement>('[data-motion-media]')
        );
        gsap.set(cards, { autoAlpha: 1, y: 0, scale: 1 });
        gsap.set(media, { opacity: 1, scale: 1 });
        return;
      }

      const mediaQuery = gsap.matchMedia(scopeElement);

      mediaQuery.add(
        {
          desktop: '(min-width: 1024px)',
          motion: '(prefers-reduced-motion: no-preference)',
          reducedMotion: '(prefers-reduced-motion: reduce)'
        },
        ({ conditions }) => {
          const cards = gsap.utils.toArray<HTMLElement>(
            scopeElement.querySelectorAll<HTMLElement>('[data-motion-card]')
          );
          const media = gsap.utils.toArray<HTMLElement>(
            scopeElement.querySelectorAll<HTMLElement>('[data-motion-media]')
          );

          if (conditions?.reducedMotion) {
            gsap.set(cards, { autoAlpha: 1, y: 0, scale: 1 });
            gsap.set(media, { opacity: 1, scale: 1 });
            return;
          }

          if (!conditions?.motion) {
            return;
          }

          cards.forEach((card) => {
            gsap.fromTo(
              card,
              { autoAlpha: 0, y: 28, scale: 0.98 },
              {
                autoAlpha: 1,
                y: 0,
                scale: 1,
                duration: 0.75,
                ease: 'power3.out',
                scrollTrigger: {
                  trigger: card,
                  start: 'top 88%',
                  once: true
                }
              }
            );
          });

          media.forEach((item) => {
            gsap.fromTo(
              item,
              { scale: 0.86, opacity: 0.55 },
              {
                scale: 1,
                opacity: 1,
                ease: 'none',
                scrollTrigger: {
                  trigger: item,
                  start: 'top bottom',
                  end: 'bottom top',
                  scrub: true
                }
              }
            );
          });

          if (conditions.desktop) {
            const pinned = scopeElement.querySelector<HTMLElement>('[data-motion-pin]');
            const pinTitle = pinned?.querySelector<HTMLElement>('[data-motion-pin-title]');

            if (pinned && pinTitle) {
              ScrollTrigger.create({
                trigger: pinned,
                start: 'top 96px',
                end: 'bottom bottom',
                pin: pinTitle,
                pinSpacing: false
              });
            }
          }
        }
      );

      return () => mediaQuery.revert();
    },
    { scope, dependencies: [activeKey, reduceMotion], revertOnUpdate: true }
  );
}
