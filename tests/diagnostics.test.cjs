const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('diagnostic filters combine PI, project and reason and clear incompatible projects', () => {
  const control = () => ({value: '', addEventListener(type, fn) { this[type] = fn; }});
  const pi = control(), project = control(), reason = control(), clear = control();
  project.options = ['', 'alpha/shared', 'beta/shared'].map(value => ({
    value, dataset: {pi: value.split('/')[0]},
    get selected() { return project.value === value; }
  }));
  const rows = [
    {dataset: {pi: 'alpha', project: 'alpha/shared', reason: 'File size limit'}},
    {dataset: {pi: 'alpha', project: 'alpha/shared', reason: 'Hidden files'}},
    {dataset: {pi: 'beta', project: 'beta/shared', reason: 'File size limit'}},
    {dataset: {pi: '', project: '', reason: 'Other errors'}}
  ];
  const count = {}, empty = {};
  const controls = {'[data-diagnostic-pi]': pi, '[data-diagnostic-project]': project,
    '[data-diagnostic-reason]': reason, '[data-diagnostic-clear]': clear,
    '[data-diagnostic-count]': count, '[data-diagnostic-empty]': empty};
  const panel = {querySelector: key => controls[key], querySelectorAll: () => rows};
  const code = fs.readFileSync('portal/static/portal/app.js', 'utf8').split("const diagnostics = document.querySelector")[1];
  vm.runInNewContext('const diagnostics = document.querySelector' + code, {
    document: {querySelector: () => panel}, window: {addEventListener() {}}
  });
  assert.equal(count.textContent, 'Showing 4 of 4 retained entries');
  pi.value = 'alpha'; pi.change();
  assert.equal(project.options[2].disabled, true);
  project.value = 'alpha/shared'; reason.value = 'File size limit'; reason.change();
  assert.equal(count.textContent, 'Showing 1 of 4 retained entries');
  assert.equal(rows[0].hidden, false);
  pi.value = 'beta'; pi.change();
  assert.equal(project.value, '');
  assert.equal(rows[2].hidden, false);
  reason.value = 'Hidden files'; reason.change();
  assert.equal(empty.hidden, false);
  clear.click();
  assert.equal(count.textContent, 'Showing 4 of 4 retained entries');
  assert.equal(empty.hidden, true);
});
