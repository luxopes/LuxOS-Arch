const results = document.querySelector('#address-results');

window.vela.onSuggestions(({ rows, selected, generation, theme }) => {
  document.documentElement.dataset.theme = theme;
  results.replaceChildren();
  for (const [index, row] of rows.entries()) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'address-result';
    button.classList.toggle('highlighted', index === selected);
    const icon = document.createElement('i');
    icon.className = 'icon ' + (row.kind === 'search' ? 'search' : 'history');
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    const title = document.createElement('bdi');
    title.textContent = row.title;
    text.append(title);
    if (row.subtitle) {
      const subtitle = document.createElement('bdi');
      subtitle.className = 'result-url';
      subtitle.textContent = row.subtitle;
      text.append(subtitle);
    }
    button.append(icon, text);
    button.addEventListener('pointerdown', event => event.preventDefault());
    button.addEventListener('click', () => window.vela.action('suggestion-clicked', { index, generation }));
    results.append(button);
  }
});
