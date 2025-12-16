/**
 * Color Contrast Utilities
 * Calculate relative luminance and determine optimal text color for backgrounds
 */

/**
 * Calculate relative luminance of a color (WCAG formula)
 * https://www.w3.org/TR/WCAG20-TECHS/G17.html
 */
export function getRelativeLuminance(hex: string): number {
  // Remove # if present
  const color = hex.replace('#', '');

  // Parse RGB values
  const r = parseInt(color.substring(0, 2), 16) / 255;
  const g = parseInt(color.substring(2, 4), 16) / 255;
  const b = parseInt(color.substring(4, 6), 16) / 255;

  // Apply gamma correction
  const rLinear = r <= 0.03928 ? r / 12.92 : Math.pow((r + 0.055) / 1.055, 2.4);
  const gLinear = g <= 0.03928 ? g / 12.92 : Math.pow((g + 0.055) / 1.055, 2.4);
  const bLinear = b <= 0.03928 ? b / 12.92 : Math.pow((b + 0.055) / 1.055, 2.4);

  // Calculate relative luminance
  return 0.2126 * rLinear + 0.7152 * gLinear + 0.0722 * bLinear;
}

/**
 * Determine if a color is light or dark
 * Returns true if the color is light (needs dark text)
 * Returns false if the color is dark (needs light text)
 *
 * Uses WCAG threshold of 0.5 for relative luminance
 */
export function isLightColor(hex: string): boolean {
  const luminance = getRelativeLuminance(hex);
  // Threshold of 0.5 gives good results for most colors
  // Above 0.5 = light color (use dark text)
  // Below 0.5 = dark color (use light text)
  return luminance > 0.5;
}

/**
 * Get the optimal text color (white or black) for a given background color
 */
export function getTextColorForBackground(backgroundColor: string): string {
  return isLightColor(backgroundColor) ? '#000000' : '#ffffff';
}

/**
 * Calculate contrast ratio between two colors
 * Used for WCAG compliance checking
 */
export function getContrastRatio(color1: string, color2: string): number {
  const l1 = getRelativeLuminance(color1);
  const l2 = getRelativeLuminance(color2);

  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);

  return (lighter + 0.05) / (darker + 0.05);
}
