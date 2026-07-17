type RouteMap = Record<string, () => void>;

class Router {
  private routes: RouteMap = {};
  private current: string = '';

  add(path: string, handler: () => void): void {
    this.routes[path] = handler;
  }

  navigate(path: string): void {
    if (path === this.current) return;
    this.current = path;
    Object.entries(this.routes).forEach(([name, handler]) => {
      const el = document.getElementById(`${name}-section`);
      if (el) {
        el.classList.toggle('hidden', name !== path);
      }
    });
    const handler = this.routes[path];
    if (handler) handler();
  }

  start(): void {
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.slice(1) || 'dashboard';
      this.navigate(hash);
    });
    const initial = window.location.hash.slice(1) || 'dashboard';
    this.navigate(initial);
  }
}

export const router = new Router();
