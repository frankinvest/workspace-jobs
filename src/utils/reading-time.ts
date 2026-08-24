/**
 * Estimate reading time in minutes from text content.
 *
 * CJK characters (Chinese/Japanese/Korean) are counted as 1 char = 1 word.
 * Non-CJK text is split by whitespace for English/other word count.
 * Default reading speed: 300 words/minute (general-purpose average).
 *
 * Examples:
 *   estimateReadingTime("")                                       => 1
 *   estimateReadingTime("hello world")                             => 1
 *   estimateReadingTime("字".repeat(600))                          => 2
 *   estimateReadingTime("word ".repeat(600).trim())                => 2
 *   estimateReadingTime("字".repeat(300) + " word".repeat(300))     => 2
 *   estimateReadingTime("word ".repeat(600).trim(), 100)           => 6
 *
 * @param text  Raw text content (markdown / plain text)
 * @param wordsPerMinute  Reading speed in words per minute (default 300)
 * @returns Estimated reading time in minutes (minimum 1 for non-empty)
 */
export function estimateReadingTime(text: string, wordsPerMinute: number = 300): number {
  if (!text || text.trim().length === 0) return 1;

  // Count CJK characters (CJK Unified Ideographs + Extension A)
  const cjkChars = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;

  // Strip CJK chars (counted above) and split remainder by whitespace
  const textWithoutCJK = text.replace(/[\u4e00-\u9fff\u3400-\u4dbf]/g, ' ');
  const englishWords = textWithoutCJK.split(/\s+/).filter((w) => w.length > 0).length;

  const totalWords = cjkChars + englishWords;

  // Floor at 1 min for non-empty content; ceil for partial minutes
  return Math.max(1, Math.ceil(totalWords / wordsPerMinute));
}