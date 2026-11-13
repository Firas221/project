// Single catalog of every staff screen. Portals choose which entries they show;
// the shell hides anything the signed-in user lacks permission for.
import * as fd from '../views/frontdesk.js';
import * as guests from '../views/guests.js';
import * as rooms from '../views/rooms.js';
import * as ops from '../views/operations.js';
import * as kitchen from '../views/kitchen.js';
import * as inv from '../views/inventory.js';
import * as fin from '../views/finance.js';
import * as admin from '../views/admin.js';
import { waitlistView } from '../views/waitlist.js';
import { myShiftsView, rosterView } from '../views/roster.js';

export const SCREENS = {
  dashboard: { label: 'Dashboard', icon: 'dashboard', perm: 'dashboard.view', view: fd.dashboardView, live: 60 },
  calendar: { label: 'Room calendar', icon: 'calendar', perm: 'reservations.view', view: fd.calendarView },
  reservations: { label: 'Reservations', icon: 'reservations', perm: 'reservations.view', view: fd.reservationsView },
  waitlist: { label: 'Waiting list', icon: 'list', perm: 'reservations.view', view: waitlistView, live: 60 },
  guests: { label: 'Guests', icon: 'guests', perm: 'guests.view', view: guests.guestsView },
  housekeeping: { label: 'Housekeeping', icon: 'housekeeping', perm: 'housekeeping.view', view: ops.housekeepingBoardView, live: 30 },
  maintenance: { label: 'Maintenance', icon: 'wrench', perm: 'maintenance.report', view: ops.maintenanceView, live: 60 },
  requests: { label: 'Guest requests', icon: 'bell', perm: 'requests.manage', view: ops.requestsView, live: 30 },
  orders: { label: 'Room service', icon: 'kitchen', perm: 'kitchen.view', view: kitchen.orderBoardView },
  'lost-found': { label: 'Lost & found', icon: 'box', perm: 'lostfound.report', view: ops.lostFoundView },
  reviews: { label: 'Reviews', icon: 'star', perm: 'reviews.manage', view: ops.reviewsView },
  cashier: { label: 'Cashier', icon: 'cash', perm: 'billing.payment', view: fin.cashierView },
  companies: { label: 'Corporate accounts', icon: 'building', perm: 'billing.view', view: fin.companiesView },
  invoices: { label: 'Tax invoices', icon: 'reservations', perm: 'billing.view', view: fin.invoicesView },
  rooms: { label: 'Rooms & rates', icon: 'rooms', perm: 'rooms.view', view: rooms.roomsView },
  menu: { label: 'Menu & recipes', icon: 'list', perm: 'kitchen.view', view: kitchen.menuView },
  inventory: { label: 'Inventory', icon: 'inventory', perm: 'inventory.view', view: inv.inventoryView },
  supplies: { label: 'Supplies', icon: 'inventory', perm: 'inventory.request', view: inv.mySuppliesView },
  reports: { label: 'Reports', icon: 'reports', perm: 'reports.view', view: fin.reportsView },
  'night-audit': { label: 'Night audit', icon: 'moon', perm: 'reports.view', view: fin.nightAuditView },
  roster: { label: 'Staff roster', icon: 'calendar', perm: 'roster.manage', view: rosterView },
  'my-shifts': { label: 'My shifts', icon: 'calendar', perm: null, view: myShiftsView },
  users: { label: 'Users', icon: 'guests', perm: 'users.manage', view: admin.usersView },
  roles: { label: 'Roles & permissions', icon: 'shield', perm: 'roles.manage', view: admin.rolesView },
  settings: { label: 'Settings', icon: 'settings', perm: 'settings.manage', view: admin.settingsView },
  audit: { label: 'Audit log', icon: 'search', perm: 'audit.view', view: admin.auditView },
};

/** Detail pages reachable by link (not in the sidebar). */
export const DETAIL_ROUTES = [
  { pattern: /^reservations\/(\d+)$/, nav: 'reservations', perm: 'reservations.view', view: fd.reservationView },
  { pattern: /^invoices\/(\d+)$/, nav: 'invoices', perm: 'billing.view', view: fd.invoiceView },
  { pattern: /^folio\/(\d+)$/, nav: 'reservations', perm: 'billing.view', view: fd.folioView },
  { pattern: /^guests\/(\d+)$/, nav: 'guests', perm: 'guests.view', view: guests.guestView },
  { pattern: /^guest-register$/, nav: 'guests', perm: 'guests.view', view: guests.registerView },
  { pattern: /^companies\/(\d+)$/, nav: 'companies', perm: 'billing.view', view: fin.companyView },
  { pattern: /^inventory\/(\d+)$/, nav: 'inventory', perm: 'inventory.view', view: inv.itemView },
  { pattern: /^tax$/, nav: 'reports', perm: 'reports.view', view: fin.taxView },
  { pattern: /^order-history$/, nav: 'orders', perm: 'kitchen.view', view: kitchen.deliveredView },
];

export const newReservation = fd.newReservation;
