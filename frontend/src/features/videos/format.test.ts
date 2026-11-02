import { describe, expect, it } from 'vitest';
import { languageName, searchPath, snippetParts } from './format';

describe('snippetParts', () => {
  it('splits marked matches from the text around them', () => {
    expect(snippetParts('we [[roast]] the [[beans]] today')).toEqual([
      { text: 'we ', match: false },
      { text: 'roast', match: true },
      { text: ' the ', match: false },
      { text: 'beans', match: true },
      { text: ' today', match: false },
    ]);
  });

  it('keeps markup from a transcript as plain text', () => {
    expect(snippetParts('<img src=x> [[bean]]')).toEqual([
      { text: '<img src=x> ', match: false },
      { text: 'bean', match: true },
    ]);
  });

  it('copes with unbalanced markers said in the transcript', () => {
    expect(snippetParts('array[[0 is first')).toEqual([{ text: 'array[[0 is first', match: false }]);
  });
});

describe('languageName', () => {
  it('names a known language and falls back to the code', () => {
    expect(languageName('en')).toMatch(/English/);
    expect(languageName('not a code')).toBe('not a code');
  });
});

describe('searchPath', () => {
  it('encodes the query', () => {
    expect(searchPath('rock & roll')).toBe('/search?q=rock%20%26%20roll');
  });
});
