const {test} = require('node:test');
const assert = require('node:assert/strict');
const {runInNewContext} = require('node:vm');
const {readFileSync} = require('node:fs');
const source = readFileSync('portal/static/portal/report-keys.js', 'utf8').replace('PORTAL_ORIGIN_VALUE', '"https://portal.test"');
function setup() {
  const handlers = {}, messages = [], scrolls = [];
  const parent = {postMessage: (data, origin) => messages.push({data, origin})};
  runInNewContext(source, {window: {parent, innerHeight: 1000, scrollBy: options => scrolls.push(options.top), addEventListener: (type, fn) => handlers[type] = fn}, document: {addEventListener: (type, fn) => handlers[type] = fn}});
  return {handlers, parent, messages, scrolls};
}
test('report keys navigate horizontally and page vertically', () => {
  const s = setup();
  for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']) s.handlers.keydown({key, preventDefault() {}});
  assert.equal(s.messages[0].data.direction, 'previous');
  assert.equal(s.messages[1].data.direction, 'next');
  assert.equal(s.messages[0].origin, 'https://portal.test');
  assert.deepEqual(s.scrolls, [-900, 900]);
});
test('editing, handled events and modifier shortcuts are untouched', () => {
  const s = setup();
  for (const props of [{target: {isContentEditable: true}}, {target: {closest: () => ({})}}, {defaultPrevented: true}, {ctrlKey: true}, {isComposing: true}]) {
    s.handlers.keydown({key: 'ArrowRight', preventDefault() {throw Error('must not intercept');}, ...props});
  }
  assert.equal(s.messages.length, 0);
});
test('scroll requests require portal origin, parent window and allowed direction', () => {
  const s = setup();
  const valid = {origin: 'https://portal.test', source: s.parent, data: {channel: 'hyperion-keyboard', scroll: 1}};
  s.handlers.message({...valid, origin: 'https://other.test'});
  s.handlers.message({...valid, source: {}});
  s.handlers.message({...valid, data: {channel: 'hyperion-keyboard', scroll: 100}});
  assert.equal(s.scrolls.length, 0);
  s.handlers.message(valid);
  assert.deepEqual(s.scrolls, [900]);
});
