import type { CSSProperties } from 'react';

// Import all SVG icons
import playIcon from '../assets/icons/play.svg';
import pauseIcon from '../assets/icons/pause.svg';
import forwardStepIcon from '../assets/icons/forward-step.svg';
import backwardStepIcon from '../assets/icons/backward-step.svg';
import volumeHighIcon from '../assets/icons/volume-high.svg';
import volumeLowIcon from '../assets/icons/volume-low.svg';
import volumeXmarkIcon from '../assets/icons/volume-xmark.svg';
import chevronDownIcon from '../assets/icons/chevron-down.svg';
import chevronUpIcon from '../assets/icons/chevron-up.svg';
import xmarkIcon from '../assets/icons/xmark.svg';
import gearIcon from '../assets/icons/gear.svg';
import spinnerIcon from '../assets/icons/spinner.svg';
import musicIcon from '../assets/icons/music.svg';
import triangleExclamationIcon from '../assets/icons/triangle-exclamation.svg';
import desktopIcon from '../assets/icons/desktop.svg';
import towerBroadcastIcon from '../assets/icons/tower-broadcast.svg';
import networkWiredIcon from '../assets/icons/network-wired.svg';
import sunIcon from '../assets/icons/sun.svg';
import moonIcon from '../assets/icons/moon.svg';
import paletteIcon from '../assets/icons/palette.svg';
import headphonesIcon from '../assets/icons/headphones.svg';
import plusIcon from '../assets/icons/plus.svg';
import trashIcon from '../assets/icons/trash.svg';
import eyeIcon from '../assets/icons/eye.svg';
import circleInfoIcon from '../assets/icons/circle-info.svg';
import puzzlePieceIcon from '../assets/icons/puzzle-piece.svg';
import bookIcon from '../assets/icons/book.svg';
import githubIcon from '../assets/icons/github.svg';
import spotifyIcon from '../assets/icons/spotify.svg';
import appleIcon from '../assets/icons/apple.svg';
import bluetoothIcon from '../assets/icons/bluetooth.svg';
import wifiIcon from '../assets/icons/wifi.svg';
import waveformIcon from '../assets/icons/waveform.svg';

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
