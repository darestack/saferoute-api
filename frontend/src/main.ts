// SafeRoute Homepage

import './global.css';

function initScrollAnimations(): void {
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px',
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-fade-in');
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  const elements = document.querySelectorAll('section > div');
  elements.forEach((el) => {
    observer.observe(el);
  });

  setTimeout(() => {
    elements.forEach((el) => {
      (el as HTMLElement).style.opacity = '';
    });
  }, 2000);
}

function initSmoothScroll(): void {
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', (e) => {
      const targetId = anchor.getAttribute('href');
      if (targetId === null || targetId === '#') return;

      const target = document.querySelector(targetId);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
}

function initCounterAnimations(): void {
  const counters = document.querySelectorAll('[data-count]');

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const target = parseInt((entry.target as HTMLElement).dataset.count || '0', 10);
          animateValue(entry.target, 0, target, 2000);
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.5 }
  );

  counters.forEach((counter) => observer.observe(counter));
}

function animateValue(
  element: Element,
  start: number,
  end: number,
  duration: number
): void {
  const range = end - start;
  const startTime = performance.now();

  function update(currentTime: number): void {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const current = Math.floor(start + range * easeOut);

    element.textContent = current.toLocaleString();

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

document.addEventListener('DOMContentLoaded', () => {
  initScrollAnimations();
  initSmoothScroll();
  initCounterAnimations();
});
