'use strict';
const toggle = document.querySelector('.sidebar-toggle');
if (toggle) toggle.addEventListener('click', () => {
  const hidden = document.querySelector('.viewer').classList.toggle('sidebar-hidden');
  toggle.setAttribute('aria-expanded', String(!hidden));
});
const launchForm = document.querySelector('#launch-form');
if (launchForm) {
  const status = document.querySelector('#viewer-status');
  const retry = document.querySelector('#retry-report');
  const frame = document.querySelector('#report-frame');
  let expiry;
  async function openReport(event) {
    if (event) event.preventDefault();
    clearTimeout(expiry);
    status.className = 'sr-only';
    status.textContent = 'Opening report…';
    retry.disabled = true;
    const body = new FormData(launchForm);
    body.set('path', launchForm.dataset.reportPath);
    try {
      const response = await fetch(launchForm.action, {method: 'POST', body, credentials: 'same-origin', redirect: 'error'});
      if (!response.ok) throw new Error('Access unavailable');
      const data = await response.json();
      frame.dataset.reportOrigin = new URL(data.url).origin;
      frame.src = data.url;
      status.textContent = 'Report requested.';
      retry.disabled = false;
      clearTimeout(expiry);
      expiry = setTimeout(() => {status.className = 'viewer-notice'; status.textContent = 'The report session has expired. Reload to continue using report resources.';}, 3600000);
    } catch (error) {
      status.textContent = 'Unable to open the report. Your session or access may have changed. Try reloading the page or signing in again.';
      status.className = 'viewer-notice';
      retry.disabled = false;
    }
  }
  launchForm.addEventListener('submit', openReport);
  openReport();
}

// Menus overlay the report instead of adding another row above it.
const toolbarMenus = [...document.querySelectorAll('.toolbar-menu')];
for (const menu of toolbarMenus) {
  menu.addEventListener('toggle', () => {
    if (menu.open) toolbarMenus.forEach(other => { if (other !== menu) other.open = false; });
  });
}
document.addEventListener('click', event => {
  toolbarMenus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    toolbarMenus.forEach(menu => {
      if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
    });
  }
});
if (toggle && window.matchMedia('(max-width: 700px)').matches) {
  document.querySelector('.viewer').classList.add('sidebar-hidden');
  toggle.setAttribute('aria-expanded', 'false');
}

const keyboardFrame = document.querySelector('#report-frame');
if (keyboardFrame) {
  const channel = 'hyperion-keyboard';
  let navigating = false;
  function navigateReport(direction) {
    if (!['previous', 'next'].includes(direction) || navigating) return;
    const link = document.querySelector(`a[data-report-direction="${direction}"]`);
    if (link) { navigating = true; link.click(); }
  }
  window.addEventListener('pageshow', () => { navigating = false; });
  window.addEventListener('message', event => {
    if (event.source !== keyboardFrame.contentWindow || event.origin !== keyboardFrame.dataset.reportOrigin) return;
    if (event.data?.channel === channel) navigateReport(event.data.direction);
  });
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target?.isContentEditable || event.target?.closest?.('input, textarea, select, button, summary, [contenteditable], [role="dialog"], [role="slider"], [role="textbox"]')) return;
    if (toolbarMenus.some(menu => menu.open) || document.querySelector('#about-dialog')?.open) return;
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (!event.repeat) navigateReport(event.key === 'ArrowLeft' ? 'previous' : 'next');
    } else if (keyboardFrame.dataset.reportOrigin) {
      keyboardFrame.contentWindow.postMessage({channel, scroll: event.key === 'ArrowUp' ? -1 : 1}, keyboardFrame.dataset.reportOrigin);
    }
  });
}

const aboutDialog = document.querySelector('#about-dialog');
const aboutButton = document.querySelector('.about-open');
if (aboutDialog && aboutButton) {
  aboutButton.addEventListener('click', () => {
    aboutButton.closest('details').open = false;
    aboutDialog.showModal();
  });
  aboutDialog.addEventListener('close', () => {
    document.querySelector('.account-menu summary').focus();
  });
  aboutDialog.addEventListener('click', event => {
    const box = aboutDialog.getBoundingClientRect();
    if (event.target === aboutDialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) aboutDialog.close();
  });
}

const adminTabs = document.querySelector('[data-admin-tabs]');
if (adminTabs) {
  const tabs = [...adminTabs.querySelectorAll('[role="tab"]')];
  function selectTab(name, focus = false) {
    const selected = tabs.find(tab => tab.dataset.tab === name) || tabs[0];
    tabs.forEach(tab => {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    });
    if (focus) selected.focus();
  }
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener('click', () => {
      selectTab(tab.dataset.tab);
      history.replaceState(null, '', '#' + tab.dataset.tab);
    });
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next === undefined) return;
      event.preventDefault();
      selectTab(tabs[next].dataset.tab, true);
      history.replaceState(null, '', '#' + tabs[next].dataset.tab);
    });
  }
  selectTab(adminTabs.dataset.defaultTab === 'accounts' ? 'accounts' : location.hash.slice(1) || 'projects');
  window.addEventListener('hashchange', () => selectTab(location.hash.slice(1)));
}

for (const form of document.querySelectorAll('[data-bulk-publication]')) {
  const rows = [...form.querySelectorAll('input[name="selected"]:not(:disabled)')];
  const all = form.querySelector('[data-select-all]');
  const buttons = [...form.querySelectorAll('button[name="mode"]')];
  function updateSelection() {
    const count = rows.filter(row => row.checked).length;
    form.querySelector('.selection-count').textContent = `${count} selected`;
    all.checked = count > 0 && count === rows.length;
    all.indeterminate = count > 0 && count < rows.length;
    all.disabled = rows.length === 0;
    buttons.forEach(button => { button.disabled = count === 0; });
  }
  all.addEventListener('change', () => {
    rows.forEach(row => { row.checked = all.checked; });
    updateSelection();
  });
  rows.forEach(row => row.addEventListener('change', updateSelection));
  form.addEventListener('submit', event => {
    if (!rows.some(row => row.checked)) event.preventDefault();
  });
  window.addEventListener('pageshow', updateSelection);
  updateSelection();
}
