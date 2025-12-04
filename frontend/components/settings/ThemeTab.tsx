import React from 'react';
import type {AccentColor, Settings as SettingsType, ThemeMode} from '../../types';
import {Switch} from '../Switch';

interface ThemeTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

const themeModes: { value: ThemeMode; label: string; icon: string }[] = [
  {value: 'light', label: 'Light', icon: 'fa-sun'},
  {value: 'dark', label: 'Dark', icon: 'fa-moon'},
  {value: 'system', label: 'System', icon: 'fa-desktop'},
];

const accentColors: { name: AccentColor; className: string }[] = [
  {name: 'purple', className: 'bg-[#aa5cc3]'},
  {name: 'blue', className: 'bg-[#3b82f6]'},
  {name: 'green', className: 'bg-[#22c55e]'},
  {name: 'orange', className: 'bg-[#f97316]'},
  {name: 'red', className: 'bg-[#ef4444]'},
];

export const ThemeTab: React.FC<ThemeTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const handleThemeModeChange = (mode: ThemeMode) => {
    onSettingsChange({
      ...settings,
      theme: {
        ...settings.theme,
        mode,
      },
    });
  };

  const handleAccentChange = (accent: AccentColor) => {
    onSettingsChange({
      ...settings,
      theme: {
        ...settings.theme,
        accent,
      },
    });
  };

  const handleDisplayChange = (key: keyof SettingsType['display'], value: boolean) => {
    onSettingsChange({
      ...settings,
      display: {
        ...settings.display,
        [key]: value,
      },
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          Appearance
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Customize the look and feel of your interface
        </p>
      </div>

      <div className="space-y-6">
        <div>
          <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Theme Mode</h4>
          <div className="grid grid-cols-3 gap-2 p-1 rounded-lg bg-[var(--bg-tertiary)]">
            {themeModes.map((mode) => (
              <button
                key={mode.value}
                onClick={() => handleThemeModeChange(mode.value)}
                className={`
                  px-3 py-2 text-sm font-semibold rounded-md flex items-center justify-center gap-2 transition-colors
                  ${
                    settings.theme.mode === mode.value
                      ? 'bg-[var(--accent-color)] text-white'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary-hover)]'
                  }
                `}
              >
                <i className={`fas ${mode.icon}`}></i>
                {mode.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-2">
            System mode automatically switches between light and dark based on your device settings
          </p>
        </div>

        <div>
          <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Accent Color</h4>
          <div className="flex items-center gap-4">
            {accentColors.map((color) => (
              <button
                key={color.name}
                onClick={() => handleAccentChange(color.name)}
                className={`
                  w-10 h-10 rounded-full ${color.className} transition-transform hover:scale-110
                  ${
                    settings.theme.accent === color.name
                      ? 'ring-2 ring-offset-2 ring-offset-[var(--bg-secondary)] ring-[var(--accent-color)]'
                      : ''
                  }
                `}
                aria-label={`Set accent color to ${color.name}`}
              />
            ))}
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-2">
            Choose a color that highlights active elements and buttons
          </p>
        </div>

      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <p className="text-xs text-[var(--text-muted)] italic">
          Note: Theme and display preferences are saved per-browser. Different devices can have
          different theme settings while sharing the same server configuration.
        </p>
      </div>
    </div>
  );
};
