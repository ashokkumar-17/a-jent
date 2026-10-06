/* A-Jent dashboard — vanilla JS view layer */

const ROUTES = {
  jobs: { view: 'jobs', breadcrumb: 'Workspace / Jobs', title: 'Jobs', subtitle: 'A clearer next step for your search.' },
  agent: { view: 'agent', breadcrumb: 'Workspace / AI Agent', title: 'AI Agent', subtitle: 'A clear view of the work A-Jent has done for you.' },
  applied: { view: 'applied', breadcrumb: 'Workspace / Applications', title: 'Applications', subtitle: 'See only the progress returned by the application service.' },
  resume: { view: 'resume', breadcrumb: 'Workspace / Resume', title: 'Resume', subtitle: 'Keep one current document ready for matching.' },
  log: { view: 'log', breadcrumb: 'Workspace / Activity', title: 'Activity stream', subtitle: 'Technical details stay available when you need them.' },
  subscription: { view: 'subscription', breadcrumb: 'Workspace / Account', title: 'Subscription', subtitle: 'Keep notification delivery connected to your workspace.' },
  settings: { view: 'subscription', breadcrumb: 'Workspace / Account', title: 'Settings', subtitle: 'Manage the settings that keep A-Jent searching and sending relevant roles.' },
  profile: { view: 'profile', breadcrumb: 'Workspace / Profile', title: 'Profile', subtitle: 'A quiet ledger of the details A-Jent can use.' },
  coaching: { view: 'coaching', breadcrumb: 'Workspace / Coaching', title: 'Coaching', subtitle: 'Next steps grounded in the information A-Jent can actually read.' },
  interview: { view: 'interview', breadcrumb: 'Workspace / Interview', title: 'Interview', subtitle: 'A ready destination for practice when a question library is connected.' },
  notifications: { view: 'notifications', breadcrumb: 'Workspace / Notifications', title: 'Notifications', subtitle: 'Choose how A-Jent should keep you informed.' },
  help: { view: 'help', breadcrumb: 'Workspace / Help', title: 'Help', subtitle: 'Understand what A-Jent can confirm from the current workspace.' },
};

const state = {
  activeRoute: 'jobs',
  authenticated: false,
  user: null,
  authMode: 'login',
  allJobs: [],
  filteredJobs: [],
  selectedJobId: null,
  jobLoadState: 'idle',
  jobFilters: { query: '', source: '', location: '', minimumScore: 0, date: '', remoteOnly: false },
  jobSort: 'score',
  browseTab: 'recommended',
  detailOpen: false,
  lastDetailTrigger: null,
  stats: null,
  applied: { jobs: [], in_progress: 0, submitted: 0 },
  resume: null,
  subscription: null,
  logLines: [],
  logPaused: false,
  logSource: null,
  logRetryTimer: null,
  logRetryCount: 0,
  logBootstrapped: false,
  logAuthBlocked: false,
  appliedPoll: null,
  toastTimer: null,
};

class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function safeInitial(value) {
  const initial = String(value || 'J').trim().charAt(0).toUpperCase();
  return /[A-Z0-9]/.test(initial) ? initial : 'J';
}

function formatCount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : '—';
}

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? Math.max(0, Math.min(score, 1)) : 0;
}

function formatDate(iso) {
  if (!iso) return '';
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function fmtAgo(iso) {
  if (!iso) return '';
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return '';
  const minutes = Math.floor((Date.now() - time) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d ago` : formatDate(iso);
}

function isWithinDate(iso, range) {
  if (!range) return true;
  const time = new Date(iso || '').getTime();
  if (Number.isNaN(time)) return false;
  const age = Date.now() - time;
  return range === 'today' ? age <= 86400000 : age <= 604800000;
}

function normalizeJob(job, index = 0) {
  return {
    id: String(job?.id || `job-${index}`),
    title: String(job?.title || 'Untitled role'),
    company: String(job?.company || 'Company not returned'),
    url: String(job?.url || ''),
    source: String(job?.source || 'Source not returned'),
    location: String(job?.location || 'Location not returned'),
    score: formatScore(job?.score),
    found_at: String(job?.found_at || ''),
  };
}

function showToast(message, isError = false) {
  const toast = $('#toast');
  if (!toast) return;
  window.clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle('is-error', isError);
  toast.classList.add('is-visible');
  state.toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 3200);
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name.replace(/[-.\\+*?[\\]^$(){}|=!<>:-]/g, '\\$&') + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

async function getCsrfToken() {
  let token = getCookie('csrf_token');
  if (!token) {
    try {
      const res = await fetch('/api/csrf-token');
      const data = await res.json();
      token = data?.csrf_token;
    } catch (_) {}
  }
  return token;
}

async function fetchJSON(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const token = await getCsrfToken();
    if (token) {
      if (!options.headers) options.headers = {};
      if (options.headers instanceof Headers) {
        options.headers.set('X-CSRFToken', token);
      } else {
        options.headers['X-CSRFToken'] = token;
      }
    }
  }
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(payload?.error || `HTTP ${response.status}`, response.status);
  return payload;
}

function setAuthGate(visible) {
  $('#authGate')?.classList.toggle('is-hidden', !visible);
  document.body.classList.toggle('auth-required', visible);
  if (visible) {
    window.setTimeout(() => $('#authEmail')?.focus(), 40);
  }
}

function renderUser(user) {
  state.user = user || null;
  const displayName = user?.name || user?.email?.split('@')[0] || 'Your workspace';
  const initial = safeInitial(displayName);
  const shortName = displayName.split(/\s+/)[0] || 'Account';
  $('#topAvatar').textContent = initial;
  $('#sidebarAvatar').textContent = initial;
  $('#accountButtonLabel').textContent = shortName;
  $('#accountMenuName').textContent = displayName;
  $('#accountMenuEmail').textContent = user?.email || 'Signed-in workspace';
  $$('.account-copy strong').forEach((element) => { element.textContent = displayName; });
  $$('.account-copy span').forEach((element) => { element.textContent = user?.email || 'Current resume connected'; });
  renderJobsUtility();
  renderSubscription();
}

function setAuthMode(mode) {
  state.authMode = mode === 'register' ? 'register' : 'login';
  const registering = state.authMode === 'register';
  $('#authNameField')?.classList.toggle('is-hidden', !registering);
  $('#authPassword')?.setAttribute('autocomplete', registering ? 'new-password' : 'current-password');
  $('#authSubmit').textContent = registering ? 'Create account' : 'Log in to A-Jent';
  $('#authTitle').textContent = registering ? 'Start with a connected workspace.' : 'Keep your search connected.';
  $$('.auth-tab').forEach((tab) => {
    const active = tab.dataset.authMode === state.authMode;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  $('#authError').textContent = '';
}

async function checkSession() {
  try {
    const data = await fetchJSON('/api/auth/me', { credentials: 'same-origin' });
    if (!data.authenticated || !data.user) throw new ApiError('Authentication required.', 401);
    state.authenticated = true;
    renderUser(data.user);
    setAuthGate(false);
    return true;
  } catch (_) {
    state.authenticated = false;
    setAuthGate(true);
    setConnection('Sign in to continue', 'warning');
    return false;
  }
}

async function submitAuth(event) {
  event.preventDefault();
  const registering = state.authMode === 'register';
  const name = $('#authName')?.value.trim() || '';
  const email = $('#authEmail')?.value.trim() || '';
  const password = $('#authPassword')?.value || '';
  const error = $('#authError');
  const button = $('#authSubmit');
  error.textContent = '';
  if (!email || !email.includes('@')) { error.textContent = 'Enter a valid email address.'; return; }
  if (password.length < 4) { error.textContent = 'Password must be at least 4 characters.'; return; }
  button.disabled = true;
  button.textContent = registering ? 'Creating account…' : 'Signing in…';
  try {
    const data = await fetchJSON(`/api/auth/${registering ? 'register' : 'login'}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password }),
    });
    if (!data.authenticated || !data.user) throw new ApiError('The session could not be created.');
    state.authenticated = true;
    renderUser(data.user);
    setAuthGate(false);
    showRoute('jobs');
    await loadAll();
    startLiveLog();
    maybeShowEmailModal();
    showToast(registering ? 'Account created' : 'Welcome back');
  } catch (authError) {
    error.textContent = authError.message || 'Could not authenticate. Try again.';
  } finally {
    button.disabled = false;
    button.textContent = registering ? 'Create account' : 'Log in to A-Jent';
  }
}

async function logout() {
  try {
    await fetchJSON('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  } catch (_) {
    // Clear the local UI even if the server is already unavailable.
  }
  state.authenticated = false;
  state.user = null;
  state.logAuthBlocked = true;
  if (state.logSource) state.logSource.close();
  closeRoleDetails({ restoreFocus: false });
  setAuthGate(true);
  $('#accountMenu')?.classList.add('is-hidden');
  showToast('Signed out');
}

function toggleAccountMenu() {
  const menu = $('#accountMenu');
  const button = $('[data-action="toggle-account"]');
  const open = menu?.classList.toggle('is-hidden') === false;
  button?.setAttribute('aria-expanded', String(open));
}

function setConnection(text, tone = 'normal') {
  const stateEl = $('#connectionState');
  const textEl = $('#connectionText');
  if (textEl) textEl.textContent = text;
  stateEl?.classList.toggle('is-warning', tone === 'warning');
  stateEl?.classList.toggle('is-error', tone === 'error');
}

function setRouteHeader(route) {
  const config = ROUTES[route] || ROUTES.jobs;
  $('#pageBreadcrumb').textContent = config.breadcrumb;
  $('#pageTitle').textContent = config.title;
  $('#pageSubtitle').textContent = config.subtitle;
  document.title = `A-Jent — ${config.title}`;
}

function updateNavigation(route) {
  $$('[data-route]').forEach((control) => {
    const isActive = control.dataset.route === route || (route === 'subscription' && control.dataset.route === 'settings');
    if (control.classList.contains('nav-item')) {
      control.classList.toggle('is-active', isActive);
      if (isActive) control.setAttribute('aria-current', 'page');
      else control.removeAttribute('aria-current');
    }
  });
}

function updateBrowseTabs() {
  $$('.jobs-browse-tab').forEach((tab) => {
    const active = tab.dataset.browseTab === state.browseTab;
    tab.classList.toggle('is-active', active);
    if (active) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
}

function handleBrowseTab(tab) {
  const browseTab = tab?.dataset.browseTab;
  if (!browseTab || tab.disabled || tab.getAttribute('aria-disabled') === 'true') {
    if (browseTab === 'saved' || browseTab === 'external') showToast(`${browseTab === 'saved' ? 'Saved filters' : 'External roles'} are not connected yet`);
    return;
  }
  state.browseTab = browseTab;
  updateBrowseTabs();
  if (browseTab === 'applications') {
    showRoute('applied');
    return;
  }
  showRoute('jobs');
}

function showRoute(route = 'jobs') {
  const config = ROUTES[route] || ROUTES.jobs;
  state.activeRoute = route;
  setRouteHeader(route);
  updateNavigation(route);
  document.body.classList.toggle('jobs-route', config.view === 'jobs');
  $$('.route-view').forEach((view) => view.classList.toggle('is-active', view.dataset.view === config.view));

  if (config.view === 'jobs') {
    state.browseTab = 'recommended';
    updateBrowseTabs();
    renderJobs();
  }
  if (config.view === 'agent') renderAgent();
  if (config.view === 'applied') loadApplied();
  if (config.view === 'resume') loadResumeStatus();
  if (config.view === 'log') {
    startLiveLog();
    renderLogLines();
  }
  if (config.view === 'subscription') checkSubscriptionStatus();
  if (['profile', 'coaching', 'interview', 'notifications', 'help'].includes(config.view)) renderPlaceholder(config.view);
}

function populateJobFilters() {
  const sources = [...new Set(state.allJobs.map((job) => job.source).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const locations = [...new Set(state.allJobs.map((job) => job.location).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const sourceFilter = $('#sourceFilter');
  const locationFilter = $('#locationFilter');
  if (sourceFilter) {
    const current = sourceFilter.value;
    sourceFilter.innerHTML = '<option value="">Source</option>' + sources.map((source) => `<option value="${esc(source)}">${esc(source)}</option>`).join('');
    sourceFilter.value = sources.includes(current) ? current : '';
  }
  if (locationFilter) {
    const current = locationFilter.value;
    locationFilter.innerHTML = '<option value="">Location</option>' + locations.map((location) => `<option value="${esc(location)}">${esc(location)}</option>`).join('');
    locationFilter.value = locations.includes(current) ? current : '';
  }
}

function scoreBand(score) {
  if (score >= .7) return { key: 'strong', title: 'Strong alignment', description: 'Roles closest to your current resume', className: '', color: 'mint' };
  if (score >= .4) return { key: 'review', title: 'Worth reviewing', description: 'Good signals with a little more to check', className: 'review', color: 'blue' };
  return { key: 'other', title: 'Other matches', description: 'Roles A-Jent found, with a lighter signal', className: 'other', color: 'gray' };
}

function companyMarkStyle(company) {
  const colors = [
    ['#1d2723', '#ffffff'],
    ['#3869c8', '#ffffff'],
    ['#e7f6ef', '#087455'],
    ['#c86045', '#ffffff'],
    ['#13211a', '#ffffff'],
    ['#eef3ef', '#1d2723'],
    ['#dff2e7', '#087455'],
  ];
  const value = [...String(company || 'J')].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const [background, color] = colors[value % colors.length];
  return `background:${background};color:${color}`;
}

function renderJobResult(job) {
  const band = scoreBand(job.score);
  const percent = Math.round(job.score * 100);
  const found = fmtAgo(job.found_at) || 'Time not returned';
  const selected = state.selectedJobId === job.id;
  const actionState = job.url ? '' : ' disabled';
  return `<article class="job-result ${band.className}${selected ? ' is-selected' : ''}" data-job-id="${esc(job.id)}">
    <div class="job-result-main">
      <button class="job-result-select" type="button" data-action="select-job" data-job-id="${esc(job.id)}" aria-label="Open role details for ${esc(job.title)} at ${esc(job.company)}" aria-pressed="${selected}">
        <span class="company-mark" style="${companyMarkStyle(job.company)}">${esc(safeInitial(job.company))}</span>
        <span class="job-result-identity"><span class="job-result-kicker"><span class="job-age">${esc(found)}</span><span class="source-badge">${esc(job.source)}</span></span><span class="job-result-title">${esc(job.title)}</span><span class="job-result-company">${esc(job.company)}</span></span>
      </button>
      <div class="job-result-facts" aria-label="Role facts"><span><i class="ti ti-map-pin" aria-hidden="true"></i>${esc(job.location || 'Location not returned')}</span><span><i class="ti ti-clock" aria-hidden="true"></i>${esc(found)}</span><span><i class="ti ti-file-text" aria-hidden="true"></i>Resume matched</span></div>
      <div class="job-result-actions"><span class="job-result-source">Found by A-Jent</span><button class="ghost-button" type="button" data-action="open-role" data-job-id="${esc(job.id)}"${actionState}>Open role <i class="ti ti-arrow-up-right" aria-hidden="true"></i></button><button class="icon-button" type="button" data-action="copy-role" data-job-id="${esc(job.id)}" aria-label="Copy role link"${actionState}><i class="ti ti-link" aria-hidden="true"></i></button></div>
    </div>
    <aside class="job-score-panel" aria-label="${percent}% resume match"><span class="job-score-kicker">Resume match</span><strong class="job-score-number">${percent}%</strong><span class="job-score-label">${esc(band.title)}</span><div class="job-score-bar"><span style="width:${percent}%"></span></div><span class="job-score-note">Local comparison</span></aside>
  </article>`;
}

function renderMatchBand(band, jobs) {
  if (!jobs.length) return '';
  const className = band.key === 'review' ? 'review' : band.key === 'other' ? 'other' : '';
  return `<section class="match-band ${className}"><div class="band-label"><div><h3>${esc(band.title)}</h3><p>${esc(band.description)}</p></div><span class="band-counter">${String(jobs.length).padStart(2, '0')} roles</span></div><div class="job-result-list">${jobs.map(renderJobResult).join('')}</div></section>`;
}

function readJobFilters() {
  state.jobFilters = {
    query: ($('#searchInput')?.value || '').trim(),
    source: $('#sourceFilter')?.value || '',
    location: $('#locationFilter')?.value || '',
    minimumScore: Number($('#scoreFilter')?.value || 0),
    date: $('#dateFilter')?.value || '',
    remoteOnly: Boolean(state.jobFilters.remoteOnly),
  };
  state.jobSort = $('#sortSelect')?.value === 'recent' ? 'recent' : 'score';
}

function getActiveJobFilters() {
  const filters = state.jobFilters;
  return [
    filters.query ? { key: 'query', label: `Search: ${filters.query}` } : null,
    filters.source ? { key: 'source', label: `Source: ${filters.source}` } : null,
    filters.location ? { key: 'location', label: `Location: ${filters.location}` } : null,
    filters.minimumScore ? { key: 'minimumScore', label: `${Math.round(filters.minimumScore * 100)}%+ match` } : null,
    filters.date ? { key: 'date', label: filters.date === 'today' ? 'Posted today' : 'Posted this week' } : null,
    filters.remoteOnly ? { key: 'remoteOnly', label: 'Remote only' } : null,
  ].filter(Boolean);
}

function updateJobFilterSummary(resultCount = state.filteredJobs.length) {
  const active = getActiveJobFilters();
  const count = active.length;
  const countEl = $('#filterCount');
  if (countEl) countEl.textContent = String(count).padStart(2, '0');
  const utilityCount = $('#utilityFilterCount');
  if (utilityCount) utilityCount.textContent = String(count).padStart(2, '0');
  const status = $('#filterStatus');
  if (status) status.textContent = `${active.length ? `${active.map((item) => item.label).join(' · ')} · ` : ''}Showing ${formatCount(resultCount)} role${resultCount === 1 ? '' : 's'} found by A-Jent · sorted by ${state.jobSort === 'recent' ? 'most recent' : 'strongest alignment'}`;
  const chips = $('#activeFilterChips');
  if (chips) chips.innerHTML = active.length ? active.map((item) => `<button class="active-filter-chip" type="button" data-action="remove-filter" data-filter-key="${esc(item.key)}">${esc(item.label)} <i class="ti ti-x" aria-hidden="true"></i></button>`).join('') : '<span class="active-filter-empty">No active filters</span>';
  $('#remoteFilter')?.classList.toggle('is-active', state.jobFilters.remoteOnly);
  $('#remoteFilter')?.setAttribute('aria-pressed', String(state.jobFilters.remoteOnly));
  $('#scoreFilterChip')?.classList.toggle('is-active', state.jobFilters.minimumScore >= .7);
  $('#scoreFilterChip')?.setAttribute('aria-pressed', String(state.jobFilters.minimumScore >= .7));
  renderJobsUtility(active);
}

function renderJobsUtility(activeFilters = getActiveJobFilters()) {
  const displayName = state.user?.name || state.user?.email?.split('@')[0] || 'Your workspace';
  const email = state.user?.email || 'Not signed in';
  const applicationCount = Array.isArray(state.applied?.jobs) ? state.applied.jobs.length : 0;
  if ($('#utilityAvatar')) $('#utilityAvatar').textContent = safeInitial(displayName);
  if ($('#utilityUserName')) $('#utilityUserName').textContent = displayName;
  if ($('#utilityUserEmail')) $('#utilityUserEmail').textContent = email;
  if ($('#utilityApplicationsCount')) $('#utilityApplicationsCount').textContent = formatCount(applicationCount);
  if ($('#jobsApplicationsTabCount')) $('#jobsApplicationsTabCount').textContent = formatCount(applicationCount);
  if ($('#utilityFilterCount')) $('#utilityFilterCount').textContent = String(activeFilters.length).padStart(2, '0');
  if ($('#utilityFilterSummary')) $('#utilityFilterSummary').textContent = activeFilters.length ? activeFilters.map((item) => item.label).join(' · ') : 'No active filters';
}

function renderJobsLoading() {
  const grid = $('#jobsGrid');
  if (!grid) return;
  $('#resultsCount').textContent = 'Loading…';
  grid.innerHTML = `<div class="job-skeleton-list" aria-label="Loading roles" aria-busy="true">${[0, 1, 2].map(() => `<div class="job-skeleton"><span class="skeleton-mark"></span><span class="skeleton-lines"><i></i><i></i><i></i></span><span class="skeleton-score"><i></i><i></i></span></div>`).join('')}</div>`;
}

function renderJobsError(message) {
  const grid = $('#jobsGrid');
  if (!grid) return;
  grid.innerHTML = `<div class="empty-state jobs-empty-state surface"><div><i class="ti ti-refresh-alert" aria-hidden="true"></i><h3>Jobs could not refresh</h3><p>${esc(message || 'A-Jent could not read the latest jobs response.')}</p><button class="primary-button" type="button" data-action="retry-jobs">Retry jobs</button></div></div>`;
}

function renderJobs(jobs = null) {
  if (state.jobLoadState === 'loading') { renderJobsLoading(); return; }
  populateJobFilters();
  readJobFilters();
  const list = jobs || state.allJobs;
  const { query, source, location, minimumScore, date, remoteOnly } = state.jobFilters;
  let filtered = list.filter((job) => {
    const searchable = `${job.title} ${job.company}`.toLowerCase();
    const locationText = job.location.toLowerCase();
    return (!query || searchable.includes(query.toLowerCase())) && (!source || job.source === source) && (!location || job.location === location) && job.score >= minimumScore && isWithinDate(job.found_at, date) && (!remoteOnly || locationText.includes('remote'));
  });
  filtered.sort((a, b) => state.jobSort === 'recent' ? (new Date(b.found_at).getTime() || 0) - (new Date(a.found_at).getTime() || 0) || b.score - a.score : b.score - a.score || (new Date(b.found_at).getTime() || 0) - (new Date(a.found_at).getTime() || 0));
  state.filteredJobs = filtered;
  $('#resultsCount').textContent = `${formatCount(filtered.length)} role${filtered.length === 1 ? '' : 's'}`;
  updateJobFilterSummary(filtered.length);

  const grid = $('#jobsGrid');
  if (!grid) return;
  if (!filtered.length) {
    if (state.jobLoadState === 'error' && !state.allJobs.length) {
      renderJobsError('The jobs service did not return a usable response. Your workspace is still available.');
    } else {
      grid.innerHTML = `<div class="empty-state jobs-empty-state surface"><div><i class="ti ti-search-off" aria-hidden="true"></i><h3>${state.allJobs.length ? 'No roles match these filters' : 'No roles returned yet'}</h3><p>${state.allJobs.length ? 'Clear one filter to widen the field without losing your place.' : 'A-Jent keeps this space open until a connected jobs response is available.'}</p><button class="outline-button" type="button" data-action="reset-filters">${state.allJobs.length ? 'Clear filters' : 'Refresh roles'}</button></div></div>`;
    }
    state.selectedJobId = null;
    renderRoleDetails(null);
    closeRoleDetails({ restoreFocus: false });
    return;
  }
  const strong = filtered.filter((job) => job.score >= .7);
  const review = filtered.filter((job) => job.score >= .4 && job.score < .7);
  const other = filtered.filter((job) => job.score < .4);
  grid.innerHTML = renderMatchBand(scoreBand(.7), strong) + renderMatchBand(scoreBand(.4), review) + renderMatchBand(scoreBand(.1), other);
  if (!state.selectedJobId || !filtered.some((job) => job.id === state.selectedJobId)) state.selectedJobId = filtered[0].id;
  renderRoleDetails(filtered.find((job) => job.id === state.selectedJobId) || filtered[0]);
}

function findJobById(id) {
  return state.allJobs.find((item) => item.id === String(id)) || state.filteredJobs.find((item) => item.id === String(id)) || null;
}

function jobFromEvent(event) {
  const node = event?.target?.closest('[data-job-id]');
  return findJobById(node?.dataset.jobId) || findJobById(state.selectedJobId);
}

function renderRoleDetails(job) {
  const container = $('#roleDetailsContent');
  if (!container) return;
  if (!job) {
    container.innerHTML = `<div class="detail-empty"><div><i class="ti ti-layout-sidebar-right" aria-hidden="true"></i><h2>Select a role</h2><p>Choose a match from the results to review the local score and source details.</p></div></div>`;
    return;
  }
  const percent = Math.round(job.score * 100);
  const band = scoreBand(job.score);
  const found = fmtAgo(job.found_at) || 'Not returned';
  const status = state.applied.jobs.find((item) => String(item.id) === String(job.id));
  const statusLabel = status ? `${formatAppliedStatus(status)}` : 'No application record for this role yet.';
  const statusClass = status?.status === 'submitted' ? 'status-badge' : status?.status === 'failed' ? 'status-badge danger' : status ? 'status-badge warn' : 'status-badge neutral';
  container.innerHTML = `<div class="detail-header"><div><div class="eyebrow">Role details</div><div class="detail-status">Selected from results</div></div><button class="icon-button detail-close" id="roleDetailsClose" type="button" data-action="close-details" aria-label="Close role details"><i class="ti ti-x" aria-hidden="true"></i></button></div>
    <div class="detail-job-head"><span class="company-mark" style="${companyMarkStyle(job.company)}">${esc(safeInitial(job.company))}</span><div><h2 id="roleDetailsTitle">${esc(job.title)}</h2><p>${esc(job.company)}</p></div></div>
    <div class="match-coordinate"><div class="match-coordinate-row"><div><div class="eyebrow text-mint">Resume match</div><div class="coordinate-score">${percent}%</div></div><div class="coordinate-label">${esc(band.title)}<span>local resume comparison</span></div></div><div class="coordinate-ticks" aria-label="${percent}% match">${[0, 1, 2, 3, 4].map((tick) => `<span class="${tick < Math.ceil(percent / 20) ? 'is-on' : ''}"></span>`).join('')}</div><div class="coordinate-bar"><span style="width:${percent}%"></span></div></div>
    <dl class="detail-list"><div><dt>Location</dt><dd>${esc(job.location)}</dd></div><div><dt>Found by A-Jent</dt><dd class="mono">${esc(found)}</dd></div><div><dt>Source</dt><dd class="mono">${esc(job.source.toUpperCase())}</dd></div></dl>
    <div class="detail-section"><h3><i class="ti ti-file-text" aria-hidden="true"></i>What A-Jent can confirm</h3><p>A-Jent compares this role with your current resume. The score reflects the local match signal; it does not claim salary, applicant volume, seniority, or company details that were not returned.</p></div>
    <div class="detail-section"><div class="detail-section-heading"><h3>Application status</h3><span class="panel-note">ONLY WHEN AVAILABLE</span></div><div class="${statusClass}" style="margin-top:12px">${esc(statusLabel)}</div></div>
    <div class="detail-actions"><button class="dark-button" type="button" data-action="open-role" data-job-id="${esc(job.id)}" ${job.url ? '' : 'disabled'}>Open role <i class="ti ti-arrow-up-right" aria-hidden="true"></i></button><button class="outline-button" type="button" data-action="copy-role" data-job-id="${esc(job.id)}" aria-label="Copy role link" ${job.url ? '' : 'disabled'}><i class="ti ti-link" aria-hidden="true"></i></button></div>
    <div class="detail-footer"><span>Role <span class="mono">${String(state.filteredJobs.indexOf(job) + 1).padStart(2, '0')}</span> of ${state.filteredJobs.length}</span><span class="detail-nav"><button class="outline-button" type="button" data-action="previous-role" aria-label="Previous role"><i class="ti ti-chevron-left" aria-hidden="true"></i></button><button class="outline-button" type="button" data-action="next-role" aria-label="Next role"><i class="ti ti-chevron-right" aria-hidden="true"></i></button></span></div>`;
}

function openRoleDetails(job, trigger = null) {
  if (!job) return;
  const details = $('#roleDetails');
  const scrim = $('#roleDetailsScrim');
  if (!details || !scrim) return;
  state.selectedJobId = job.id;
  state.detailOpen = true;
  state.lastDetailTrigger = trigger || document.activeElement;
  renderRoleDetails(job);
  details.classList.remove('is-hidden');
  scrim.classList.remove('is-hidden');
  document.body.classList.add('role-drawer-open');
  window.requestAnimationFrame(() => $('#roleDetailsClose')?.focus());
}

function closeRoleDetails({ restoreFocus = true } = {}) {
  state.detailOpen = false;
  $('#roleDetails')?.classList.add('is-hidden');
  $('#roleDetailsScrim')?.classList.add('is-hidden');
  document.body.classList.remove('role-drawer-open');
  const trigger = state.lastDetailTrigger;
  state.lastDetailTrigger = null;
  if (restoreFocus && trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus());
}

function selectJob(id, trigger = null) {
  const job = findJobById(id);
  if (!job) return;
  state.selectedJobId = job.id;
  renderJobs();
  const renderedTrigger = $$('[data-action="select-job"]').find((element) => element.dataset.jobId === job.id);
  openRoleDetails(job, renderedTrigger || trigger);
}

function removeFilter(key) {
  if (key === 'query') $('#searchInput').value = '';
  if (key === 'source') $('#sourceFilter').value = '';
  if (key === 'location') $('#locationFilter').value = '';
  if (key === 'minimumScore') $('#scoreFilter').value = '0';
  if (key === 'date') $('#dateFilter').value = '';
  if (key === 'remoteOnly') state.jobFilters.remoteOnly = false;
  renderJobs();
}

function resetFilters() {
  ['searchInput', 'sourceFilter', 'locationFilter', 'dateFilter'].forEach((id) => { const el = $(`#${id}`); if (el) el.value = ''; });
  const score = $('#scoreFilter');
  if (score) score.value = '0';
  state.jobFilters.remoteOnly = false;
  renderJobs();
}

function selectRelativeJob(direction) {
  if (!state.filteredJobs.length) return;
  const current = Math.max(0, state.filteredJobs.findIndex((job) => job.id === state.selectedJobId));
  const next = (current + direction + state.filteredJobs.length) % state.filteredJobs.length;
  selectJob(state.filteredJobs[next].id, state.lastDetailTrigger);
}

function renderAgent() {
  const stats = state.stats || {};
  const last = stats.last_cycle || null;
  const cycles = Array.isArray(stats.recent_cycles) ? stats.recent_cycles : [];
  const outcomes = [
    { label: 'Roles seen', value: formatCount(stats.total_seen), suffix: 'all sources', color: 'mint', ticks: 4 },
    { label: 'Matches found', value: formatCount(stats.total_matches), suffix: 'above your threshold', color: 'soft', ticks: 3 },
    { label: 'Applications sent', value: formatCount(stats.total_applied), suffix: 'from the agent queue', color: 'warm', ticks: 2 },
  ];
  $('#agentOutcomes').innerHTML = outcomes.map((item) => `<div class="outcome-cell"><div class="outcome-label">${item.label}</div><div class="outcome-value"><strong>${esc(item.value)}</strong><span>${item.suffix}</span></div><div class="outcome-ticks">${[0, 1, 2, 3, 4].map((tick) => `<span class="${tick < item.ticks ? 'is-on' : ''}"></span>`).join('')}</div></div>`).join('');
  $('#agentLastChecked').textContent = last?.timestamp ? `${fmtAgo(last.timestamp)} · source results available` : 'No completed cycle returned';
  const newMatches = last?.new_matches;
  $('#latestSearchPanel').innerHTML = `<div class="latest-summary"><div><strong>${esc(newMatches == null ? '—' : formatCount(newMatches))}</strong><span>new matches</span></div><div class="cycle-status"><strong>${last ? 'Search finished' : 'Waiting for a cycle'}</strong><span>${last?.timestamp ? esc(fmtAgo(last.timestamp)) : 'last_cycle not returned'}</span></div></div><div class="metric-grid"><div class="metric"><strong>${esc(last?.total_fetched == null ? '—' : formatCount(last.total_fetched))}</strong><label>Roles fetched</label></div><div class="metric"><strong>${esc(last?.unseen == null ? '—' : formatCount(last.unseen))}</strong><label>Unseen roles</label></div><div class="metric"><strong>${esc(last?.passed_location_filter == null ? '—' : formatCount(last.passed_location_filter))}</strong><label>Passed filters</label></div><div class="metric match"><strong>${esc(newMatches == null ? '—' : formatCount(newMatches))}</strong><label>New matches</label></div></div>`;
  renderSourceBreakdown(stats.source_breakdown || {});
  renderCycleHistory(cycles);
  renderAgentApplications();
  renderLogLines();
}

function renderSourceBreakdown(sourceBreakdown) {
  const entries = Object.entries(sourceBreakdown).filter(([, count]) => Number.isFinite(Number(count))).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 8);
  const max = Math.max(...entries.map(([, count]) => Number(count)), 1);
  $('#sourceBreakdown').innerHTML = entries.length ? `<div class="source-list">${entries.map(([name, count]) => `<div class="source-row"><span class="source-name">${esc(name)}</span><span class="source-track"><span class="source-fill" style="width:${(Number(count) / max) * 100}%"></span></span><span class="source-count">${esc(formatCount(count))}</span></div>`).join('')}</div>` : '<div class="empty-state"><div><i class="ti ti-chart-bar-off" aria-hidden="true"></i><p>No source totals returned by the current stats response.</p></div></div>';
}

function renderCycleHistory(cycles) {
  const rows = [...cycles].reverse().slice(0, 10);
  $('#cycleHistory').innerHTML = rows.length ? rows.map((cycle) => `<div class="history-row"><span class="history-time">${esc(fmtAgo(cycle.timestamp) || 'time not returned')}</span><div class="history-main"><strong>Search completed</strong><span>${esc(cycle.total_fetched == null ? '—' : formatCount(cycle.total_fetched))} fetched · ${esc(cycle.unseen == null ? '—' : formatCount(cycle.unseen))} unseen · ${esc(cycle.passed_location_filter == null ? '—' : formatCount(cycle.passed_location_filter))} passed</span></div><div class="history-score"><strong>${esc(cycle.new_matches == null ? '—' : formatCount(cycle.new_matches))}</strong><span>new matches</span></div></div>`).join('') : '<div class="empty-state"><div><i class="ti ti-history" aria-hidden="true"></i><p>No completed cycles returned yet.</p></div></div>';
}

function formatAppliedStatus(job) {
  if (job.status === 'in_progress') return String({ starting: 'Starting', checking_login: 'Checking login', navigating: 'Opening job page', finding_apply_button: 'Finding apply button', filling_form: 'Filling form', submitting: 'Submitting' }[job.progress_stage] || 'In progress');
  return String(job.status || 'Unknown').replace(/_/g, ' ');
}

function renderAgentApplications() {
  const jobs = Array.isArray(state.applied.jobs) ? state.applied.jobs.slice(0, 5) : [];
  $('#agentApplicationQueue').innerHTML = jobs.length ? jobs.map(renderApplicationRow).join('') + '<div class="application-empty">Statuses reflect the agent response. If a submission fails, A-Jent keeps the backend note here and leaves the source link available.</div>' : '<div class="application-empty">No application records returned yet. A-Jent will keep this space available when the application service responds.</div>';
}

function renderApplicationRow(job) {
  const status = job.status === 'submitted' ? 'done' : job.status === 'failed' ? 'failed' : 'progress';
  return `<article class="application-row"><div><div class="application-title">${esc(job.title || 'Untitled role')}</div><div class="application-company">${esc(job.company || 'Company not returned')}</div><div class="application-meta"><span>${esc(job.platform || job.source || 'Source not returned')}</span><span>applied ${esc(fmtAgo(job.applied_at) || 'time not returned')}</span><span>stage: ${esc(job.progress_stage || job.status || 'unknown')}</span></div></div><div class="application-score"><strong>${job.score == null ? '—' : `${Math.round(formatScore(job.score) * 100)}%`}</strong><span class="application-status ${status}">${esc(formatAppliedStatus(job))}</span></div></article>`;
}

function renderPlaceholder(route) {
  const configs = {
    profile: { eyebrow: 'Profile ledger', title: 'Review the details A-Jent can use.', description: 'Profile data stays private and remains read-only until a connected profile update route is available.', callout: 'Profile data is not connected yet', rows: [['Personal', 'No personal details returned'], ['Education', 'No education history returned'], ['Work experience', 'No work experience returned'], ['Skills', 'No skills returned'], ['Preferences', 'No preferences returned']], actions: [{ label: 'Review resume', route: 'resume' }, { label: 'Open settings', route: 'settings' }] },
    coaching: { eyebrow: 'Next steps, not noise', title: 'Coaching stays grounded in what A-Jent can read.', description: 'Recommendations become personal when the current resume and profile details are available.', callout: 'Capability check', rows: [['Review current resume', 'Check the document A-Jent compares with roles.'], ['Review profile details', 'Keep the details behind your job matching clear.'], ['Prepare for interviews', 'Interview practice will appear when a question library is connected.']], actions: [{ label: 'Open resume', route: 'resume' }, { label: 'Open profile', route: 'profile' }] },
    interview: { eyebrow: 'Interview / 00', title: 'Prepare with a clearer starting point.', description: 'This space is ready for interview practice, but A-Jent does not have a connected question library yet.', callout: 'Ready when connected', rows: [['Technical practice', 'Role-based technical prompts'], ['Behavioral practice', 'Structured response rehearsal'], ['Company-specific preparation', 'Question sets from a connected source']], actions: [{ label: 'Review resume', route: 'resume' }, { label: 'Review profile details', route: 'profile' }] },
    notifications: { eyebrow: 'Account / Notifications', title: 'Keep alerts on your terms.', description: 'Notification delivery is tied to the subscription and email routes already available in this workspace.', callout: 'Email alerts are optional', rows: [['Job alerts', 'Register an email from the optional onboarding prompt.'], ['Subscription', 'Manage notification delivery and renewal from Settings.'], ['Agent cadence', 'The AI Agent view reports completed source cycles.']], actions: [{ label: 'Open settings', route: 'settings' }, { label: 'Open agent', route: 'agent' }] },
    help: { eyebrow: 'Workspace / Help', title: 'A clear boundary around what A-Jent knows.', description: 'A-Jent shows returned data plainly and leaves unsupported capabilities visible as connected-state placeholders.', callout: 'Source-aware by design', rows: [['Jobs', 'Roles and match signals come from /api/jobs.'], ['Resume', 'Upload status comes from /api/resume-status.'], ['Applications', 'Progress comes from /api/applied-jobs when available.']], actions: [{ label: 'Open jobs', route: 'jobs' }, { label: 'Open activity', route: 'log' }] },
  };
  const config = configs[route] || configs.help;
  const view = $(`#view-${route}`);
  if (!view) return;
  view.innerHTML = `<div class="view-intro"><div><div class="eyebrow">${esc(config.eyebrow)}</div><h2>${esc(ROUTES[route]?.title || route)}</h2><p>${esc(config.description)}</p></div><div class="connection-state"><span>Connected-state view</span></div></div><div class="placeholder-layout"><section class="surface placeholder-hero"><div class="eyebrow">${esc(config.eyebrow)}</div><h2>${esc(config.title)}</h2><p>${esc(config.description)}</p><div class="placeholder-actions">${config.actions.map((action) => `<button class="dark-button" type="button" data-route="${esc(action.route)}">${esc(action.label)} <i class="ti ti-arrow-up-right" aria-hidden="true"></i></button>`).join('')}</div><div class="capability-list" style="margin-top:24px">${config.rows.map(([title, detail]) => `<div class="capability-row"><div><strong>${esc(title)}</strong><span>${esc(detail)}</span></div><span class="status-badge neutral">Unavailable</span></div>`).join('')}</div></section><aside class="placeholder-callout"><h3>${esc(config.callout)}</h3><p>Nothing is being hidden—this destination is waiting for a supported source before it presents an action as available.</p></aside></div>`;
}

async function loadAll() {
  setConnection('A-Jent is checking the workspace');
  state.jobLoadState = 'loading';
  if (!state.allJobs.length) renderJobsLoading();
  const [statsResult, jobsResult, appliedResult] = await Promise.allSettled([fetchJSON('/api/stats'), fetchJSON('/api/jobs'), fetchJSON('/api/applied-jobs')]);
  const results = [statsResult, jobsResult, appliedResult];
  if (results.some((result) => result.status === 'rejected' && (result.reason?.status === 401 || result.reason?.status === 403))) {
    state.authenticated = false;
    state.jobLoadState = 'error';
    setAuthGate(true);
    setConnection('Session expired — sign in again', 'warning');
    return;
  }
  let hadError = false;
  if (statsResult.status === 'fulfilled') state.stats = statsResult.value;
  else hadError = true;
  if (jobsResult.status === 'fulfilled') {
    state.allJobs = Array.isArray(jobsResult.value?.jobs) ? jobsResult.value.jobs.map(normalizeJob) : [];
    state.jobLoadState = 'ready';
    $('#jobsStateBanner')?.classList.add('is-hidden');
  } else {
    hadError = true;
    state.jobLoadState = 'error';
    const banner = $('#jobsStateBanner');
    if (banner) {
      banner.innerHTML = `<strong>Jobs are showing the last successful results.</strong> ${esc(jobsResult.reason?.message || 'A-Jent could not refresh the jobs service.')} <button class="banner-action" type="button" data-action="retry-jobs">Retry jobs</button>`;
      banner.className = 'state-banner is-warning';
      banner.classList.remove('is-hidden');
    }
  }
  if (appliedResult.status === 'fulfilled') state.applied = appliedResult.value;
  else hadError = true;
  state.allJobs = state.allJobs.map(normalizeJob);
  renderJobs();
  renderJobsUtility();
  renderAgent();
  renderAgentApplications();
  checkSubscriptionStatus();
  const updated = $('#jobsUpdated');
  if (updated) updated.textContent = hadError ? 'last successful data · partial refresh' : `updated ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  setConnection(hadError ? 'Some workspace sources are unavailable' : 'Search connected', hadError ? 'warning' : 'normal');
  $('#lastUpdated')?.remove();
}

async function loadApplied() {
  try {
    const data = await fetchJSON('/api/applied-jobs');
    state.applied = data || { jobs: [] };
    renderApplied();
    renderAgentApplications();
    renderJobsUtility();
    if (Number(data?.in_progress) > 0 && !state.appliedPoll) {
      state.appliedPoll = window.setInterval(() => { if (state.activeRoute === 'applied' || state.activeRoute === 'agent') loadApplied(); else { window.clearInterval(state.appliedPoll); state.appliedPoll = null; } }, 5000);
    } else if (!Number(data?.in_progress) && state.appliedPoll) {
      window.clearInterval(state.appliedPoll); state.appliedPoll = null;
    }
  } catch (error) {
    $('#appliedContent').innerHTML = `<div class="empty-state"><div><i class="ti ti-database-off" aria-hidden="true"></i><h3>Application service not connected</h3><p>${error.status === 401 || error.status === 403 ? 'Sign in to see application records returned for your workspace.' : 'Try again when the application service is available.'}</p></div></div>`;
  }
}

function renderApplied() {
  const jobs = Array.isArray(state.applied.jobs) ? state.applied.jobs : [];
  $('#appliedCount').textContent = `${formatCount(jobs.length)} record${jobs.length === 1 ? '' : 's'}`;
  $('#appliedContent').innerHTML = jobs.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Job</th><th>Company</th><th>Platform</th><th>Score</th><th>Applied</th><th>Progress</th></tr></thead><tbody>${jobs.map((job) => `<tr><td>${job.url ? `<a href="${esc(job.url)}" target="_blank" rel="noopener">${esc(job.title || 'Untitled role')}</a>` : esc(job.title || 'Untitled role')}</td><td>${esc(job.company || '—')}</td><td>${esc(job.platform || job.source || '—')}</td><td>${job.score == null ? '—' : `${Math.round(formatScore(job.score) * 100)}%`}</td><td class="muted">${esc(fmtAgo(job.applied_at) || '—')}</td><td><span class="status-badge ${job.status === 'submitted' ? '' : job.status === 'failed' ? 'danger' : 'warn'}">${esc(formatAppliedStatus(job))}</span></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state"><div><i class="ti ti-send-off" aria-hidden="true"></i><h3>No auto-applied jobs yet</h3><p>Enable auto-apply in config.yaml and add a resume before expecting records here.</p></div></div>';
}

async function loadResumeStatus() {
  try {
    state.resume = await fetchJSON('/api/resume-status');
    renderResumeStatus();
  } catch (error) {
    const banner = $('#resumeStateBanner');
    if (banner) { banner.textContent = error.status === 401 || error.status === 403 ? 'Connect your workspace to read the current resume status.' : 'The resume status could not be loaded. You can retry without losing the current surface.'; banner.className = 'state-banner is-warning'; }
    $('#resumeStatus').innerHTML = '<div class="empty-state"><div><i class="ti ti-file-off" aria-hidden="true"></i><h3>Resume status unavailable</h3><p>A-Jent will not guess the current document until the endpoint responds.</p></div></div>';
  }
}

function renderResumeStatus() {
  const info = state.resume?.resume;
  const resumes = state.resume?.resumes || [];
  const badge = $('#resumePrimaryBadge');
  const agentNameEl = $('#agentPrimaryResumeName');
  const countBadge = $('#resumesCountBadge');

  if (countBadge) {
    countBadge.textContent = `${resumes.length} ${resumes.length === 1 ? 'resume' : 'resumes'}`;
  }

  if (agentNameEl) {
    if (info?.filename) {
      agentNameEl.textContent = info.filename;
      agentNameEl.title = `Current Primary Resume: ${info.filename}`;
    } else {
      agentNameEl.textContent = 'No resume uploaded';
    }
  }

  if (!info) {
    badge.textContent = 'No document';
    badge.className = 'status-badge neutral';
    $('#resumeStatus').innerHTML = '<div class="empty-state"><div><i class="ti ti-file-off" aria-hidden="true"></i><h3>No current resume returned</h3><p>Upload a PDF, DOCX, or DOC to give A-Jent a comparison source.</p></div></div>';
    const uploadResultEl = $('#uploadResult');
    if (uploadResultEl) {
      uploadResultEl.innerHTML = '';
      uploadResultEl.className = 'upload-result';
    }
  } else {
    badge.textContent = 'Primary Resume';
    badge.className = 'status-badge';
    const isDocx = (info.filename || '').endsWith('.docx') || (info.filename || '').endsWith('.doc');
    $('#resumeStatus').innerHTML = `
      <div class="document-info">
        <span class="file-icon"><i class="${isDocx ? 'ti ti-file-type-doc' : 'ti ti-file-type-pdf'}" aria-hidden="true"></i></span>
        <div>
          <h3>${esc(info.filename)}</h3>
          <p>Primary document connected to your A-Jent workspace.</p>
        </div>
      </div>
      <div class="document-metrics">
        <div class="document-metric"><strong>${esc(`${info.size_kb ?? '—'} KB`)}</strong><span>File size</span></div>
        <div class="document-metric"><strong>${esc(fmtAgo(info.modified) || '—')}</strong><span>Last updated</span></div>
        <div class="document-metric"><strong>${info.chars_extracted ? `${info.chars_extracted.toLocaleString()} chars` : 'Extracted'}</strong><span>Text extraction</span></div>
      </div>
      <div class="document-status">
        <span><i class="ti ti-circle-check" aria-hidden="true"></i>Source of truth for AI Agent job matching &amp; auto-apply.</span>
        <span class="mono">${esc(info.modified ? formatDate(info.modified) : '')}</span>
      </div>`;
    const uploadResultEl = $('#uploadResult');
    if (uploadResultEl && uploadResultEl.children.length === 0) {
      renderSearchTrigger(uploadResultEl, false);
    }
  }

  const listEl = $('#uploadedResumesList');
  if (!listEl) return;

  if (resumes.length === 0) {
    listEl.innerHTML = `
      <div class="empty-state resume-empty-state">
        <div>
          <i class="ti ti-file-upload" aria-hidden="true"></i>
          <h3>No uploaded resumes yet</h3>
          <p>Upload your first resume using the drop zone above. It will automatically be set as your Primary Resume for the AI Agent.</p>
        </div>
      </div>`;
    return;
  }

  listEl.innerHTML = resumes.map((r) => {
    const isPrimary = Boolean(r.is_primary);
    const isDocx = (r.filename || '').endsWith('.docx') || (r.filename || '').endsWith('.doc');
    return `
      <div class="resume-item-card ${isPrimary ? 'is-primary' : ''}" data-resume-id="${esc(r.id)}">
        <div class="resume-item-main">
          <div class="resume-item-icon ${isPrimary ? 'is-primary' : ''}">
            <i class="${isDocx ? 'ti ti-file-type-doc' : 'ti ti-file-type-pdf'}" aria-hidden="true"></i>
          </div>
          <div class="resume-item-details">
            <div class="resume-item-title-row">
              <h4 class="resume-item-name">${esc(r.filename)}</h4>
              ${isPrimary ? '<span class="status-badge primary-badge"><i class="ti ti-star-filled" aria-hidden="true"></i> Primary Resume</span>' : ''}
              ${isPrimary ? '<span class="agent-source-tag"><i class="ti ti-robot" aria-hidden="true"></i> Used by Agent</span>' : ''}
            </div>
            <div class="resume-item-meta">
              <span><i class="ti ti-file" aria-hidden="true"></i> ${esc(`${r.size_kb ?? '—'} KB`)}</span>
              <span><i class="ti ti-clock" aria-hidden="true"></i> Uploaded ${esc(fmtAgo(r.uploaded_at) || formatDate(r.uploaded_at) || 'Recently')}</span>
              ${r.chars_extracted ? `<span><i class="ti ti-text-caption" aria-hidden="true"></i> ${r.chars_extracted.toLocaleString()} chars</span>` : ''}
            </div>
          </div>
        </div>
        <div class="resume-item-actions">
          ${isPrimary ? `
            <button class="primary-indicator-btn" type="button" disabled title="Currently set as your Primary Resume for all agent actions">
              <i class="ti ti-check" aria-hidden="true"></i> Current Primary
            </button>
          ` : `
            <button class="outline-button make-primary-btn" type="button" data-action="set-primary" data-resume-id="${esc(r.id)}" data-resume-name="${esc(r.filename)}">
              <i class="ti ti-star" aria-hidden="true"></i> Set as Primary
            </button>
            <button class="icon-button delete-resume-btn" type="button" data-action="delete-resume" data-resume-id="${esc(r.id)}" data-resume-name="${esc(r.filename)}" title="Remove this resume">
              <i class="ti ti-trash" aria-hidden="true"></i>
            </button>
          `}
        </div>
      </div>`;
  }).join('');
}

async function setPrimaryResume(resumeId, resumeName, buttonEl) {
  if (!resumeId) return;
  const originalText = buttonEl ? buttonEl.innerHTML : '';
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.innerHTML = '<i class="ti ti-loader-2 ti-spin" aria-hidden="true"></i> Setting…';
  }
  try {
    const data = await fetchJSON('/api/set-primary-resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_id: resumeId }),
    });
    if (!data.success) throw new ApiError(data.error || 'Could not update primary resume.');
    await loadResumeStatus();
    showToast(`Primary resume updated to ${resumeName}. AI Agent updated.`);
  } catch (err) {
    showToast(err.message || 'Failed to update primary resume.', true);
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.innerHTML = originalText;
    }
  }
}

async function deleteResume(resumeId, resumeName) {
  if (!resumeId) return;
  const confirmed = window.confirm(`Delete "${resumeName}" from your uploaded resumes?`);
  if (!confirmed) return;
  try {
    const data = await fetchJSON('/api/delete-resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_id: resumeId }),
    });
    if (!data.success) throw new ApiError(data.error || 'Could not delete resume.');
    await loadResumeStatus();
    showToast(`"${resumeName}" removed.`);
  } catch (err) {
    showToast(err.message || 'Failed to delete resume.', true);
  }
}


let _searchPollInterval = null;

function renderSearchTrigger(container, isFreshUpload = false) {
  if (!container) return;
  const headerText = isFreshUpload ? '✓ Resume uploaded successfully' : '✓ Primary resume ready';
  const subText = 'Your resume is ready for job matching.';
  container.className = 'upload-result success';
  container.innerHTML = `
    <div class="upload-confirm-box">
      <div class="upload-confirm-header">
        <i class="ti ti-circle-check" aria-hidden="true"></i>
        <strong>${headerText}</strong>
      </div>
      <p class="upload-confirm-subtext">${subText}</p>
      <div class="search-trigger-actions">
        <button class="primary-button start-search-btn" id="startSearchBtn" type="button">
          🚀 Start Job Search
        </button>
      </div>
      <div class="search-status-banner is-hidden" id="searchTriggerStatus" role="status"></div>
    </div>
  `;
  const startBtn = $('#startSearchBtn');
  if (startBtn) {
    startBtn.addEventListener('click', handleStartSearch);
  }
}

async function handleStartSearch() {
  const btn = $('#startSearchBtn');
  const statusEl = $('#searchTriggerStatus');
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = '⏳ Starting Job Search...';

  if (statusEl) {
    statusEl.className = 'search-status-banner is-hidden';
    statusEl.textContent = '';
  }

  try {
    const token = await getCsrfToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-CSRFToken'] = token;

    const response = await fetch('/api/start-search', {
      method: 'POST',
      headers,
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok || !data.success) {
      const errMsg = data.message || data.error || 'Unable to start job search. Please try again.';
      throw new Error(errMsg);
    }

    if (statusEl) {
      statusEl.className = 'search-status-banner running';
      statusEl.innerHTML = `
        <div class="search-status-header">
          <i class="ti ti-search" aria-hidden="true"></i>
          <strong>🔎 Job search started</strong>
        </div>
        <p>A-Jent is now searching for matching jobs.</p>
      `;
      statusEl.classList.remove('is-hidden');
    }
    btn.textContent = '🔎 Job Search Running...';
    btn.disabled = true;
    showToast('Job search started');

    pollSearchStatus();
  } catch (error) {
    if (statusEl) {
      statusEl.className = 'search-status-banner error';
      statusEl.innerHTML = `
        <div class="search-status-header">
          <i class="ti ti-alert-triangle" aria-hidden="true"></i>
          <strong>⚠ Unable to start job search.</strong>
        </div>
        <p>${esc(error.message || 'Please try again.')}</p>
      `;
      statusEl.classList.remove('is-hidden');
    }
    btn.disabled = false;
    btn.textContent = '🚀 Start Job Search';
    showToast(error.message || 'Unable to start job search', true);
  }
}

function pollSearchStatus() {
  if (_searchPollInterval) clearInterval(_searchPollInterval);
  let pollAttempts = 0;
  const maxAttempts = 30;

  _searchPollInterval = setInterval(async () => {
    pollAttempts++;
    try {
      const res = await fetch('/api/search-status');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.running || pollAttempts >= maxAttempts) {
        clearInterval(_searchPollInterval);
        _searchPollInterval = null;
        const btn = $('#startSearchBtn');
        const statusEl = $('#searchTriggerStatus');
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🚀 Start Job Search';
        }
        if (statusEl && !data.running) {
          statusEl.className = 'search-status-banner running';
          statusEl.innerHTML = `
            <div class="search-status-header">
              <i class="ti ti-circle-check" aria-hidden="true"></i>
              <strong>✓ Job search completed</strong>
            </div>
            <p>A-Jent has completed matching roles against your resume.</p>
          `;
        }
        loadAll();
      }
    } catch (e) {
      // Ignore polling errors
    }
  }, 3000);
}

async function uploadResume(file) {
  if (!file) return;
  const result = $('#uploadResult');
  result.className = 'upload-result';
  result.textContent = `Uploading ${file.name}…`;
  try {
    const form = new FormData();
    form.append('file', file);
    const token = await getCsrfToken();
    const headers = {};
    if (token) headers['X-CSRFToken'] = token;
    const response = await fetch('/api/upload-resume', { method: 'POST', headers, body: form });
    const data = await response.json();
    if (!response.ok || !data.success) throw new ApiError(data.error || `HTTP ${response.status}`, response.status);
    renderSearchTrigger(result, true);
    await loadResumeStatus();
    showToast('Resume uploaded');
  } catch (error) {
    result.className = 'upload-result error';
    result.textContent = `⚠ ${error.message || 'Upload failed.'}`;
    showToast('Resume upload could not finish', true);
  }
}

function handleDrop(event) {
  event.preventDefault();
  $('#dropZone')?.classList.remove('is-dragging');
  uploadResume(event.dataTransfer?.files?.[0]);
}

async function checkSubscriptionStatus() {
  try {
    state.subscription = await fetchJSON('/api/subscription-status');
    renderSubscription();
    const params = new URLSearchParams(window.location.search);
    const status = params.get('sub');
    if (status === 'success') { showToast('Subscription activated'); window.history.replaceState({}, '', '/'); }
    if (status === 'pending') { showToast('Payment pending — checking again'); window.history.replaceState({}, '', '/'); window.setTimeout(checkSubscriptionStatus, 5000); }
  } catch (error) {
    $('#subscriptionStatusBadge').textContent = 'Unavailable';
    $('#subscriptionStatusBadge').className = 'status-badge warn';
    $('#subLoading').innerHTML = '<div><i class="ti ti-credit-card-off" aria-hidden="true"></i><h3>Subscription status unavailable</h3><p>A-Jent will keep the checkout surface available when the endpoint responds.</p></div>';
  }
}

function renderSubscription() {
  const data = state.subscription || {};
  const active = Boolean(data.active);
  $('#subLoading')?.classList.toggle('is-hidden', active || data.active === false);
  $('#subActiveCard')?.classList.toggle('is-hidden', !active);
  $('#subPaywall')?.classList.toggle('is-hidden', active || data.active !== false);

  const planName = data.plan === 'trial' ? 'Trial' : data.plan === 'monthly' ? 'Monthly' : (data.plan || 'Standard');
  if ($('#subscriptionStatusBadge')) {
    $('#subscriptionStatusBadge').textContent = active ? (data.plan === 'trial' ? 'Trial Active' : 'Active') : (data.active === false ? 'Inactive' : 'Checking');
    $('#subscriptionStatusBadge').className = `status-badge ${active ? '' : 'warn'}`;
  }
  $('#subAlertBanner')?.classList.toggle('is-hidden', !(data.subscription_required && !active));

  const userEmail = data.email || state.user?.email || '—';
  const userName = data.name || state.user?.name || (userEmail.includes('@') ? userEmail.split('@')[0] : 'Your account');

  if ($('#subActiveEmail')) $('#subActiveEmail').textContent = userEmail;
  if ($('#subActivePlan')) $('#subActivePlan').textContent = planName;
  if ($('#subDaysLeft')) $('#subDaysLeft').textContent = data.days_left == null ? '—' : `${data.days_left} days`;
  if ($('#subAmount')) $('#subAmount').textContent = data.amount == null ? '₹75 / mo' : `₹${data.amount} / mo`;
  if ($('#subActiveUserLabel')) $('#subActiveUserLabel').textContent = `${userName} (${userEmail})`;

  if ($('#subPaywallAvatar')) $('#subPaywallAvatar').textContent = safeInitial(userName);
  if ($('#subPaywallUserName')) $('#subPaywallUserName').textContent = userName;
  if ($('#subPaywallUserEmail')) $('#subPaywallUserEmail').textContent = userEmail;
}

async function startPayment(kind) {
  if (!state.authenticated || !state.user) {
    showToast('Please sign in to manage your subscription', true);
    setAuthGate(true);
    return;
  }
  const button = kind === 'renew' ? $('#renewBtn') : $('#payBtn');
  const originalText = button ? button.textContent : '';
  if (button) {
    button.disabled = true;
    button.textContent = 'Preparing subscription…';
  }
  try {
    const data = await fetchJSON('/api/create-order', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (data.error) throw new Error(data.error);

    if (data.simulated) {
      showToast(data.message || 'Subscription activated successfully!');
      await checkSubscriptionStatus();
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
      return;
    }

    if (button) button.textContent = 'Connecting to payment gateway…';
    await loadScript('https://sdk.cashfree.com/js/v3/cashfree.js');
    const cashfree = window.Cashfree({ mode: data.env === 'prod' ? 'production' : 'sandbox' });
    cashfree.checkout({ paymentSessionId: data.payment_session_id, redirectTarget: '_self' });
    if (button) button.textContent = 'Redirecting to Cashfree…';
  } catch (error) {
    showToast(`Payment could not start: ${error.message}`, true);
    if (button) {
      button.disabled = false;
      button.textContent = originalText || (kind === 'renew' ? 'Renew for ₹75/mo' : 'Pay ₹75 & Activate Subscription');
    }
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const script = document.createElement('script');
    script.src = src; script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
  });
}

function renderLogLines() {
  const html = state.logLines.length ? state.logLines.map((line) => { const cls = line.includes('[ERROR]') || line.includes('[CRITICAL]') ? 'level-error' : line.includes('[WARNING]') || line.includes('[WARN]') ? 'level-warn' : line.includes('[INFO]') ? 'level-ok' : ''; return `<div class="log-line-main ${cls}">${esc(line)}</div>`; }).join('') : '<div class="log-line-main">Waiting for activity from the agent…</div>';
  if ($('#logLines')) $('#logLines').innerHTML = html;
  if ($('#agentLogLines')) $('#agentLogLines').innerHTML = state.logLines.map((line) => `<div class="log-line ${line.includes('[ERROR]') ? 'level-error' : line.includes('[WARN') ? 'level-warn' : 'level-ok'}">${esc(line)}</div>`).join('') || '<div class="log-line">Waiting for activity from the agent…</div>';
  $('#logLineCount').textContent = `${state.logLines.length} lines`;
}

function setLogConnection(text, warning = true) {
  $('#liveBadge').textContent = text;
  $('#agentStreamState').textContent = text;
  $('#agentReconnectNote').textContent = warning ? 'Activity updates are paused while A-Jent reconnects. Your last loaded history remains visible.' : 'Live activity is connected.';
}

async function startLiveLog() {
  if (state.logAuthBlocked) return;
  if (state.logSource) state.logSource.close();
  if (state.logRetryTimer) window.clearTimeout(state.logRetryTimer);

  if (!state.logBootstrapped) {
    state.logBootstrapped = true;
    try {
      const history = await fetchJSON('/api/log?n=80');
      if (Array.isArray(history.lines)) { state.logLines = history.lines.map(String).slice(-500); renderLogLines(); }
    } catch (error) {
      if (error.status === 401 || error.status === 403) {
        state.logAuthBlocked = true;
        setLogConnection('Sign in for activity', true);
        renderLogLines();
        return;
      }
    }
  }

  if (state.logRetryCount >= 2) {
    setLogConnection('Unavailable', true);
    return;
  }
  try {
    state.logSource = new EventSource('/api/log/stream');
    state.logSource.onopen = () => { state.logRetryCount = 0; setLogConnection('Live stream', false); };
    state.logSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (!state.logPaused && payload.line) { state.logLines.push(String(payload.line)); state.logLines = state.logLines.slice(-500); renderLogLines(); }
      } catch (_) { /* Ignore malformed stream events. */ }
    };
    state.logSource.onerror = () => {
      state.logRetryCount += 1;
      setLogConnection(state.logRetryCount >= 2 ? 'Unavailable' : 'Reconnecting…', true);
      if (state.logSource) { state.logSource.close(); state.logSource = null; }
      if (state.logRetryCount < 2) state.logRetryTimer = window.setTimeout(startLiveLog, 5000);
    };
  } catch (_) {
    setLogConnection('Unavailable', true);
  }
}

function togglePause() {
  state.logPaused = !state.logPaused;
  const label = state.logPaused ? 'Resume updates' : 'Pause updates';
  $('#logPauseButton').textContent = state.logPaused ? 'Resume' : 'Pause';
  $('#agentPauseButton').textContent = label;
  setLogConnection(state.logPaused ? 'Updates paused' : state.logAuthBlocked ? 'Sign in for activity' : 'Reconnecting…', state.logPaused || state.logAuthBlocked);
}

function dismissEmailModal() {
  localStorage.setItem('a_jent_email_dismissed', '1');
  $('#emailModalBackdrop')?.classList.add('is-hidden');
}

async function submitEmailModal() {
  const input = $('#emailModalInput');
  const error = $('#emailModalError');
  const button = $('#emailModalBtn');
  const email = input.value.trim();
  error.textContent = '';
  if (!email || !email.includes('@')) { error.textContent = 'Enter a valid email address.'; input.focus(); return; }
  button.disabled = true; button.textContent = 'Saving…';
  try {
    const data = await fetchJSON('/api/subscribe-email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) });
    if (!data.success) throw new Error(data.error || 'Could not save email.');
    localStorage.setItem('a_jent_email', email);
    $('#emailModal').innerHTML = '<div class="modal-icon" aria-hidden="true"><i class="ti ti-circle-check"></i></div><h2>You are all set</h2><p>A-Jent will use this address for new-match alerts when notifications are active.</p>';
    showToast('Email registered');
    window.setTimeout(dismissEmailModal, 1400);
  } catch (errorValue) {
    error.textContent = errorValue.message || 'Network error. Try again later.';
    button.disabled = false; button.textContent = 'Set up job alerts';
  }
}

function maybeShowEmailModal() {
  if (localStorage.getItem('a_jent_email_dismissed') || localStorage.getItem('jent_email_dismissed') || localStorage.getItem('a_jent_email') || localStorage.getItem('jent_email')) return;
  window.setTimeout(() => { $('#emailModalBackdrop')?.classList.remove('is-hidden'); $('#emailModalInput')?.focus(); }, 450);
}

function bindEvents() {
  document.addEventListener('click', (event) => {
    const routeControl = event.target.closest('[data-route]');
    if (routeControl) { event.preventDefault(); showRoute(routeControl.dataset.route); return; }
    const browseTab = event.target.closest('[data-browse-tab]');
    if (browseTab) { handleBrowseTab(browseTab); return; }
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (!action) return;
    if (action === 'toggle-filters') $('#filterControls')?.classList.toggle('is-collapsed');
    if (action === 'sort-score') { $('#sortSelect').value = 'score'; renderJobs(); }
    if (action === 'reset-filters') resetFilters();
    if (action === 'remove-filter') removeFilter(event.target.closest('[data-filter-key]')?.dataset.filterKey);
    if (action === 'remote-filter') { state.jobFilters.remoteOnly = !state.jobFilters.remoteOnly; renderJobs(); }
    if (action === 'score-filter') { $('#scoreFilter').value = state.jobFilters.minimumScore >= .7 ? '0' : '0.7'; renderJobs(); }
    if (action === 'retry-jobs') loadAll();
    if (action === 'select-job') selectJob(event.target.closest('[data-job-id]')?.dataset.jobId, event.target.closest('[data-action="select-job"]'));
    if (action === 'close-details') closeRoleDetails();
    if (action === 'open-role') { const job = jobFromEvent(event); if (job?.url) window.open(job.url, '_blank', 'noopener'); }
    if (action === 'copy-role') { const job = jobFromEvent(event); if (job?.url) navigator.clipboard?.writeText(job.url).then(() => showToast('Role link copied')).catch(() => showToast('Role link could not be copied', true)); }
    if (action === 'previous-role') selectRelativeJob(-1);
    if (action === 'next-role') selectRelativeJob(1);
    if (action === 'toggle-technical') { const section = $('#technicalDetails'); const open = section.classList.toggle('is-open'); event.target.closest('[data-action="toggle-technical"]')?.setAttribute('aria-expanded', String(open)); }
    if (action === 'toggle-log-pause') togglePause();
    if (action === 'scroll-log') $('#logLines').scrollTop = $('#logLines').scrollHeight;
    if (action === 'refresh-applied') loadApplied();
    if (action === 'focus-upload') { showRoute('resume'); window.setTimeout(() => $('#dropZone')?.focus(), 40); }
    if (action === 'set-primary') {
      const btn = event.target.closest('[data-action="set-primary"]');
      const resId = btn?.dataset.resumeId;
      const resName = btn?.dataset.resumeName || 'Selected resume';
      if (resId) setPrimaryResume(resId, resName, btn);
    }
    if (action === 'delete-resume') {
      const btn = event.target.closest('[data-action="delete-resume"]');
      const resId = btn?.dataset.resumeId;
      const resName = btn?.dataset.resumeName || 'Selected resume';
      if (resId) deleteResume(resId, resName);
    }
    if (action === 'notifications') showToast('Notifications are managed from Settings');
    if (action === 'toggle-account') toggleAccountMenu();
    if (action === 'account-settings') { $('#accountMenu')?.classList.add('is-hidden'); showRoute('settings'); }
    if (action === 'logout') logout();
    if (action === 'mobile-menu') $('#mobileRouteNav')?.classList.toggle('is-hidden');
  });

  $('#searchInput')?.addEventListener('input', () => renderJobs());
  ['sourceFilter', 'locationFilter', 'scoreFilter', 'dateFilter', 'sortSelect'].forEach((id) => $(`#${id}`)?.addEventListener('change', () => renderJobs()));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.detailOpen) closeRoleDetails();
  });
  $('#dropZone')?.addEventListener('click', () => $('#resumeInput')?.click());
  $('#dropZone')?.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('#resumeInput')?.click(); } });
  $('#dropZone')?.addEventListener('dragover', (event) => { event.preventDefault(); $('#dropZone').classList.add('is-dragging'); });
  $('#dropZone')?.addEventListener('dragleave', () => $('#dropZone').classList.remove('is-dragging'));
  $('#dropZone')?.addEventListener('drop', handleDrop);
  $('#resumeInput')?.addEventListener('change', (event) => uploadResume(event.target.files[0]));
  $('#emailModalBtn')?.addEventListener('click', submitEmailModal);
  $('#emailModalSkip')?.addEventListener('click', dismissEmailModal);
  $('#emailModalInput')?.addEventListener('keydown', (event) => { if (event.key === 'Enter') submitEmailModal(); });
  $('#payBtn')?.addEventListener('click', () => startPayment('subscribe'));
  $('#renewBtn')?.addEventListener('click', () => startPayment('renew'));
  $('#authForm')?.addEventListener('submit', submitAuth);
  $$('.auth-tab').forEach((tab) => tab.addEventListener('click', () => setAuthMode(tab.dataset.authMode)));
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.account-control')) {
      $('#accountMenu')?.classList.add('is-hidden');
      $('[data-action="toggle-account"]')?.setAttribute('aria-expanded', 'false');
    }
  });
}

bindEvents();
setAuthMode('login');
checkSession().then((authenticated) => {
  if (!authenticated) return;
  showRoute('jobs');
  loadAll();
  startLiveLog();
  maybeShowEmailModal();
});
window.setInterval(() => {
  if (state.authenticated) loadAll();
}, 60000);
