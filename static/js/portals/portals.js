// Entry point for the staff portals. The page's <body data-portal="..."> selects which one starts.
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
    keys: ['dashboard', 'calendar', 'reservations', 'waitlist', 'guests', 'cashier', 'companies', 'invoices', '|',
      'housekeeping', 'maintenance', 'requests', 'orders', 'menu', 'lost-found', 'reviews', '|',
      'rooms', 'inventory', 'reports', 'night-audit', '|', 'users', 'roles', 'settings', 'audit'],
  },
  // Manager: every department, rates, reports, the audit log and closing the day — but not users, roles or settings.
  manager: {
    title: 'Management', allow: (u) => u.role === 'admin' || u.role === 'manager', topAction: booking,
    keys: ['dashboard', 'calendar', 'reservations', 'waitlist', 'guests', 'cashier', 'companies', 'invoices', '|',
      'housekeeping', 'maintenance', 'requests', 'orders', 'menu', 'lost-found', 'reviews', '|',
      'rooms', 'inventory', 'reports', 'night-audit', 'audit'],
  },
  // Accountant: reports, tax invoices, corporate accounts and cashier shifts; reservations and guests are read-only.
  finance: {
    title: 'Accounting', allow: (u) => has(u, 'billing.view') && has(u, 'reports.view'),
    keys: ['reports', 'invoices', 'companies', 'cashier', 'night-audit', '|', 'reservations', 'guests', 'inventory'],
    screens: { inventory: { label: 'Stock value' } },
  },
  // Maintenance technician: repair tickets, room list, found items and supplies.
  maintenance: {
    title: 'Maintenance', allow: (u) => has(u, 'maintenance.manage'),
    keys: ['maintenance', 'rooms', 'lost-found', 'supplies'],
    screens: { maintenance: { label: 'Repair tickets' }, rooms: { label: 'Rooms' } },
  },
  // Storekeeper: stock, purchasing and the departments' supply requests.
  store: {
    title: 'Store', allow: (u) => has(u, 'inventory.manage'),
    keys: ['inventory', 'maintenance'],
    screens: { inventory: { label: 'Stock & purchasing' }, maintenance: { label: 'Report an issue' } },
  },
  // Front desk: reservations, guests, billing and guest services.
  staff: {
    title: 'Front desk', allow: (u) => has(u, 'dashboard.view'), topAction: booking,
    keys: ['dashboard', 'calendar', 'reservations', 'waitlist', 'guests', 'cashier', 'companies', 'invoices', '|',
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
    keys: ['tasks', 'history', 'rooms', 'lost-found', 'supplies', 'maintenance'],
    screens: {
      rooms: { label: 'Rooms' },   // supervisors only: housekeepers do not have "rooms.view"
      // Housekeepers see their own rooms; supervisors without "work" permission get the full board.
      tasks: { label: 'My rooms', icon: 'housekeeping', perm: null, live: 30,
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
  if (key === 'housekeeping') nav[0].labelFor = (u) => (has(u, 'housekeeping.work') ? 'My rooms' : 'Housekeeping board');
  const home = def.keys[0];
  startPortal({
    key, title: def.title, allow: def.allow, topAction: def.topAction, nav,
    // the home screen is also reachable by its own name (e.g. #/dashboard)
    routes: [{ pattern: new RegExp(`^${home}$`), nav: '', perm: screen(home).perm, view: screen(home).view, live: screen(home).live }].concat(DETAIL_ROUTES),
  });
}
