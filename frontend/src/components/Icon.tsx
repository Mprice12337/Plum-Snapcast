import type { CSSProperties } from 'react';

export type IconName =
  | 'play'
  | 'pause'
  | 'forward-step'
  | 'backward-step'
  | 'volume-high'
  | 'volume-low'
  | 'volume-xmark'
  | 'chevron-down'
  | 'chevron-up'
  | 'xmark'
  | 'gear'
  | 'spinner'
  | 'music'
  | 'triangle-exclamation'
  | 'desktop'
  | 'tower-broadcast'
  | 'network-wired'
  | 'sun'
  | 'moon'
  | 'palette'
  | 'headphones'
  | 'plus'
  | 'trash'
  | 'eye'
  | 'circle-info'
  | 'puzzle-piece'
  | 'book'
  | 'github'
  | 'spotify'
  | 'apple'
  | 'bluetooth'
  | 'wifi'
  | 'waveform';

interface IconProps {
  name: IconName;
  className?: string;
  style?: CSSProperties;
  spin?: boolean;
  'aria-hidden'?: boolean;
  'aria-label'?: string;
}

export function Icon({
  name,
  className = '',
  style,
  spin = false,
  'aria-hidden': ariaHidden,
  'aria-label': ariaLabel
}: IconProps) {
  const iconPath = `/src/assets/icons/${name}.svg`;

  const combinedClassName = `icon${spin ? ' icon-spin' : ''}${className ? ` ${className}` : ''}`;

  return (
    <img
      src={iconPath}
      alt={ariaLabel || ''}
      className={combinedClassName}
      style={{
        display: 'inline-block',
        width: '1em',
        height: '1em',
        verticalAlign: '-0.125em',
        ...style
      }}
      aria-hidden={ariaHidden}
      aria-label={ariaLabel}
    />
  );
}
