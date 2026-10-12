(() => {
  const portalOrigin = PORTAL_ORIGIN_VALUE;
  if (window.parent === window) return;
  const channel = 'hyperion-keyboard';
  const interactive = target => target?.isContentEditable || target?.closest?.(
    'input, textarea, select, button, summary, [contenteditable], [role="slider"], [role="textbox"], [role="combobox"], [role="listbox"], [role="grid"], [role="tablist"], [role="menu"], [role="tree"], [role="spinbutton"], [role="application"], canvas, svg, audio, video'
  );
  function page(direction) {
    window.scrollBy({top: direction * window.innerHeight * 0.9, behavior: 'instant'});
  }
  window.addEventListener('message', event => {
    if (event.origin !== portalOrigin || event.source !== window.parent) return;
    if (event.data?.channel === channel && [-1, 1].includes(event.data.scroll)) page(event.data.scroll);
  });
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || interactive(event.target)) return;
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      page(event.key === 'ArrowUp' ? -1 : 1);
    } else if (!event.repeat) {
      window.parent.postMessage({channel, direction: event.key === 'ArrowLeft' ? 'previous' : 'next'}, portalOrigin);
    }
  });
})();
