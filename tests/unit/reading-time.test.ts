import { describe, it, expect } from 'vitest';
import { estimateReadingTime } from '../../src/utils/reading-time';

describe('estimateReadingTime', () => {
  it('returns 1 for empty string', () => {
    expect(estimateReadingTime('')).toBe(1);
  });

  it('returns 1 for whitespace-only string', () => {
    expect(estimateReadingTime('   \n\t  ')).toBe(1);
  });

  it('returns 1 for very short English content', () => {
    expect(estimateReadingTime('hello world')).toBe(1);
  });

  it('returns 1 for very short Chinese content', () => {
    expect(estimateReadingTime('你好世界')).toBe(1);
  });

  it('counts CJK characters as words (600 chars @ 300wpm = 2 min)', () => {
    const text = '字'.repeat(600);
    expect(estimateReadingTime(text)).toBe(2);
  });

  it('counts English words by whitespace (600 words @ 300wpm = 2 min)', () => {
    const text = 'word '.repeat(600).trim();
    expect(estimateReadingTime(text)).toBe(2);
  });

  it('handles mixed CJK and English (300+300 = 600 total = 2 min)', () => {
    const cjk = '字'.repeat(300);
    const eng = 'word '.repeat(300).trim();
    expect(estimateReadingTime(cjk + ' ' + eng)).toBe(2);
  });

  it('respects custom wordsPerMinute (600 words @ 100wpm = 6 min)', () => {
    const text = 'word '.repeat(600).trim();
    expect(estimateReadingTime(text, 100)).toBe(6);
  });

  it('respects faster reading speed (600 words @ 600wpm = 1 min)', () => {
    const text = 'word '.repeat(600).trim();
    expect(estimateReadingTime(text, 600)).toBe(1);
  });

  it('rounds up partial minutes (301 words @ 300wpm = 2 min)', () => {
    const text = 'word '.repeat(301).trim();
    expect(estimateReadingTime(text)).toBe(2);
  });

  it('handles real-world article length (3000 words = 10 min)', () => {
    const text = 'word '.repeat(3000).trim();
    expect(estimateReadingTime(text)).toBe(10);
  });

  it('handles long-form Chinese content (5000 chars = 17 min)', () => {
    const text = '字'.repeat(5000);
    expect(estimateReadingTime(text)).toBe(17);
  });
});