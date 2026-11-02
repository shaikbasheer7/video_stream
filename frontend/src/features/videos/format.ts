export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

/** The API marks search matches with [[ and ]]: plain text, so a transcript can't inject markup. */
export function snippetParts(snippet: string): { text: string; match: boolean }[] {
  return snippet
    .split(/\[\[(.*?)\]\]/)
    .map((text, index) => ({ text, match: index % 2 === 1 }))
    .filter((part) => part.text);
}

export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(undefined, { type: 'language' }).of(code) ?? code;
  } catch {
    return code; // not a language code the browser knows
  }
}

export function searchPath(query: string): string {
  return `/search?q=${encodeURIComponent(query)}`;
}
