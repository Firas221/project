// Entry point for the four staff portals. The page's <body data-portal="..."> selects which one starts.
import { startPortal } from '../core/shell.js';
import { DETAIL_ROUTES, SCREENS, newReservation } from './catalog.js';
import { housekeepingBoardView, myHistoryView, myTasksView } from '../views/operations.js';
import { deliveredView } from '../views/kitchen.js';

const has = (u, p) => u.role === 'admin' || u.permissions.includes(p);
const booking = { label: '+ New reservation', perm: 'reservations.manage', run: () => newReservation() };

const PORTALS = {
  // Administrator: the whole hotel, plus users, roles, settings and the audit log.
  admin: {
    title: 'Administration', allow: (u) => u.role === 'admin', topAction: booking,
    keys: ['dashboard', 'calendar', 'reservations', 'guests', 'cashier', 'companies', 'invoices', '|',
      'housekeeping', 'maintenance', 'requests', 'orders', 'menu', 'lost-found', 'reviews', '|',
      'rooms', 'inventory', 'reports', 'night-audit', '|', 'users', 'roles', 'settings', 'audit'],
  },
  // Front desk: reservations, guests, billing and guest services.
  staff: {
    title: 'Front desk', allow: (u) => has(u, 'dashboard.view'), topAction: booking,
    keys: ['dashboard', 'calendar', 'reservations', 'guests', 'cashier', 'companies', 'invoices', '|',
      'housekeeping', 'maintenance', 'requests', 'orders', 'lost-found', 'reviews', '|', 'rooms', 'inventory', 'supplies', 'reports'],
  },
  // Chef: kitchen order board, menu & recipes, kitchen stock and supply requests.
  kitchen: {
    title: 'Kitchen', allow: (u) => has(u, 'kitchen.view'),
    keys: ['orders', 'history', 'menu', 'supplies', 'inventory', 'maintenance'],
    screens: {
      orders: { label: 'Order board' },
      history: { label: 'Order history', icon: 'list', perm: 'kitchen.view', view: deliveredView },
      inventory: { label: 'Stock levels' },
      maintenance: { label: 'Report an issue' },
    },
  },
  // Housekeeper (maid): my rooms, completed work, lost & found, supplies, report issues.
  housekeeping: {
    title: 'Housekeeping', allow: (u) => has(u, 'housekeeping.work') || has(u, 'housekeeping.manage'),
    keys: ['tasks', 'history', 'lost-found', 'supplies', 'maintenance'],
    screens: {
      // Housekeepers see their own rooms; supervisors without "work" permission get the full board.
      tasks: { label: 'My rooms', icon: 'housekeeping', perm: null,
        view: (el, a) => (a.ctx.can('housekeeping.work') ? myTasksView : housekeepingBoardView)(el, a) },
      history: { label: 'Completed work', icon: 'list', perm: 'housekeeping.work', view: myHistoryView },
      maintenance: { label: 'Report an issue' },
    },
  },
};

const key = document.body.dataset.portal;
const def = PORTALS[key];
if (def) {
  const screen = (k) => ({ ...(SCREENS[k] || {}), ...((def.screens || {})[k] || {}) });
  const nav = def.keys.map((k, i) => (k === '|' ? { sep: true } : { ...screen(k), path: i === 0 ? '' : k }));
  const home = def.keys[0];
  startPortal({
    key, title: def.title, allow: def.allow, topAction: def.topAction, nav,
    // the home screen is also reachable by its own name (e.g. #/dashboard)
    routes: [{ pattern: new RegExp(`^${home}$`), nav: '', perm: screen(home).perm, view: screen(home).view }].concat(DETAIL_ROUTES),
  });
}
