import type { CSSProperties } from 'react';

// Import all SVG icons
import playIcon from '../src/assets/icons/play.svg';
import pauseIcon from '../src/assets/icons/pause.svg';
import forwardStepIcon from '../src/assets/icons/forward-step.svg';
import backwardStepIcon from '../src/assets/icons/backward-step.svg';
import volumeHighIcon from '../src/assets/icons/volume-high.svg';
import volumeLowIcon from '../src/assets/icons/volume-low.svg';
import volumeXmarkIcon from '../src/assets/icons/volume-xmark.svg';
import chevronDownIcon from '../src/assets/icons/chevron-down.svg';
import chevronUpIcon from '../src/assets/icons/chevron-up.svg';
import xmarkIcon from '../src/assets/icons/xmark.svg';
import gearIcon from '../src/assets/icons/gear.svg';
import spinnerIcon from '../src/assets/icons/spinner.svg';
import musicIcon from '../src/assets/icons/music.svg';
import triangleExclamationIcon from '../src/assets/icons/triangle-exclamation.svg';
import desktopIcon from '../src/assets/icons/desktop.svg';
import towerBroadcastIcon from '../src/assets/icons/tower-broadcast.svg';
import networkWiredIcon from '../src/assets/icons/network-wired.svg';
import sunIcon from '../src/assets/icons/sun.svg';
import moonIcon from '../src/assets/icons/moon.svg';
import paletteIcon from '../src/assets/icons/palette.svg';
import headphonesIcon from '../src/assets/icons/headphones.svg';
import plusIcon from '../src/assets/icons/plus.svg';
import trashIcon from '../src/assets/icons/trash.svg';
import eyeIcon from '../src/assets/icons/eye.svg';
import circleInfoIcon from '../src/assets/icons/circle-info.svg';
import puzzlePieceIcon from '../src/assets/icons/puzzle-piece.svg';
import bookIcon from '../src/assets/icons/book.svg';
import githubIcon from '../src/assets/icons/github.svg';
import spotifyIcon from '../src/assets/icons/spotify.svg';
import appleIcon from '../src/assets/icons/apple.svg';
import bluetoothIcon from '../src/assets/icons/bluetooth.svg';
import wifiIcon from '../src/assets/icons/wifi.svg';
import waveformIcon from '../src/assets/icons/waveform.svg';

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

const iconMap: Record<IconName, string> = {
  'play': playIcon,
  'pause': pauseIcon,
  'forward-step': forwardStepIcon,
  'backward-step': backwardStepIcon,
  'volume-high': volumeHighIcon,
  'volume-low': volumeLowIcon,
  'volume-xmark': volumeXmarkIcon,
  'chevron-down': chevronDownIcon,
  'chevron-up': chevronUpIcon,
  'xmark': xmarkIcon,
  'gear': gearIcon,
  'spinner': spinnerIcon,
  'music': musicIcon,
  'triangle-exclamation': triangleExclamationIcon,
  'desktop': desktopIcon,
  'tower-broadcast': towerBroadcastIcon,
  'network-wired': networkWiredIcon,
  'sun': sunIcon,
  'moon': moonIcon,
  'palette': paletteIcon,
  'headphones': headphonesIcon,
  'plus': plusIcon,
  'trash': trashIcon,
  'eye': eyeIcon,
  'circle-info': circleInfoIcon,
  'puzzle-piece': puzzlePieceIcon,
  'book': bookIcon,
  'github': githubIcon,
  'spotify': spotifyIcon,
  'apple': appleIcon,
  'bluetooth': bluetoothIcon,
  'wifi': wifiIcon,
  'waveform': waveformIcon,
};

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
  const iconSrc = iconMap[name];
  const combinedClassName = `icon${spin ? ' icon-spin' : ''}${className ? ` ${className}` : ''}`;

  return (
    <img
      src={iconSrc}
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
