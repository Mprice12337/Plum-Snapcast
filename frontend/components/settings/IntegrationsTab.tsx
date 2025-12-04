import React, {useState} from 'react';
import type {Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';

interface IntegrationsTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

export const IntegrationsTab: React.FC<IntegrationsTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  const handleAirplayChange = (field: string, value: boolean | string) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        airplay: {
          ...settings.integrations.airplay,
          [field]: value,
        },
      },
    });
  };

  const handleBluetoothChange = (field: string, value: boolean | string) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        bluetooth: {
          ...settings.integrations.bluetooth,
          [field]: value,
        },
      },
    });
  };

  const handleSpotifyChange = (field: string, value: boolean | string | number) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        spotify: {
          ...settings.integrations.spotify,
          [field]: value,
        },
      },
    });
  };

  const handleDlnaChange = (field: string, value: boolean | string) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        dlna: {
          ...settings.integrations.dlna,
          [field]: value,
        },
      },
    });
  };

  const handleSimpleChange = (key: 'snapcast' | 'visualizer', value: boolean) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        [key]: value,
      },
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          Audio Sources
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Configure audio sources and their settings. Changes require service restart.
        </p>
      </div>

      <div className="space-y-4">
        {/* AirPlay */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <div className="flex items-center justify-between">
            <Switch
              label="AirPlay"
              checked={settings.integrations.airplay.enabled}
              onChange={(val) => handleAirplayChange('enabled', val)}
              icon="fa-apple"
            />
            <button
              onClick={() => toggleSection('airplay')}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <i className={`fa ${expandedSection === 'airplay' ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
            </button>
          </div>
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            AirPlay audio streaming (AirPlay 1 & 2)
          </p>

          {expandedSection === 'airplay' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.airplay.deviceName}
                  onChange={(e) => handleAirplayChange('deviceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="Plum Audio"
                />
              </div>
            </div>
          )}
        </div>

        {/* Bluetooth */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <div className="flex items-center justify-between">
            <Switch
              label="Bluetooth"
              checked={settings.integrations.bluetooth.enabled}
              onChange={(val) => handleBluetoothChange('enabled', val)}
              icon="fa-bluetooth"
            />
            <button
              onClick={() => toggleSection('bluetooth')}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <i className={`fa ${expandedSection === 'bluetooth' ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
            </button>
          </div>
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            Bluetooth A2DP audio streaming
          </p>

          {expandedSection === 'bluetooth' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.bluetooth.deviceName}
                  onChange={(e) => handleBluetoothChange('deviceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="Plum Audio"
                />
              </div>
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Adapter
                </label>
                <input
                  type="text"
                  value={settings.integrations.bluetooth.adapter}
                  onChange={(e) => handleBluetoothChange('adapter', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="hci0"
                />
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="bt-autopair"
                  checked={settings.integrations.bluetooth.autoPair}
                  onChange={(e) => handleBluetoothChange('autoPair', e.target.checked)}
                  className="mr-2"
                />
                <label htmlFor="bt-autopair" className="text-sm text-[var(--text-secondary)]">
                  Auto-pair with devices
                </label>
              </div>
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="bt-discoverable"
                  checked={settings.integrations.bluetooth.discoverable}
                  onChange={(e) => handleBluetoothChange('discoverable', e.target.checked)}
                  className="mr-2"
                />
                <label htmlFor="bt-discoverable" className="text-sm text-[var(--text-secondary)]">
                  Always discoverable
                </label>
              </div>
            </div>
          )}
        </div>

        {/* Spotify Connect */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <div className="flex items-center justify-between">
            <Switch
              label="Spotify Connect"
              checked={settings.integrations.spotify.enabled}
              onChange={(val) => handleSpotifyChange('enabled', val)}
              icon="fa-brands fa-spotify"
            />
            <button
              onClick={() => toggleSection('spotify')}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <i className={`fa ${expandedSection === 'spotify' ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
            </button>
          </div>
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            Stream music directly from Spotify
          </p>

          {expandedSection === 'spotify' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Source Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.spotify.sourceName}
                  onChange={(e) => handleSpotifyChange('sourceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="Spotify"
                />
              </div>
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.spotify.deviceName}
                  onChange={(e) => handleSpotifyChange('deviceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="Plum Audio"
                />
              </div>
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Bitrate (kbps)
                </label>
                <select
                  value={settings.integrations.spotify.bitrate}
                  onChange={(e) => handleSpotifyChange('bitrate', parseInt(e.target.value))}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                >
                  <option value="96">96</option>
                  <option value="160">160</option>
                  <option value="320">320</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* DLNA/UPnP */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <div className="flex items-center justify-between">
            <Switch
              label="DLNA/UPnP"
              checked={settings.integrations.dlna.enabled}
              onChange={(val) => handleDlnaChange('enabled', val)}
              icon="fa-network-wired"
            />
            <button
              onClick={() => toggleSection('dlna')}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            >
              <i className={`fa ${expandedSection === 'dlna' ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
            </button>
          </div>
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            DLNA/UPnP media renderer
          </p>

          {expandedSection === 'dlna' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Source Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.dlna.sourceName}
                  onChange={(e) => handleDlnaChange('sourceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="DLNA"
                />
              </div>
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <input
                  type="text"
                  value={settings.integrations.dlna.deviceName}
                  onChange={(e) => handleDlnaChange('deviceName', e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                  placeholder="Plum Audio"
                />
              </div>
            </div>
          )}
        </div>

        {/* Snapcast Stream */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <Switch
            label="Snapcast Stream"
            checked={settings.integrations.snapcast}
            onChange={(val) => handleSimpleChange('snapcast', val)}
            icon="fa-stream"
          />
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            Built-in Snapcast audio stream source
          </p>
        </div>
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <p className="text-xs text-[var(--text-muted)] italic">
          Note: Plexamp configuration remains in environment variables (.env file).
          Changes to these integration settings will be applied after container restart.
        </p>
      </div>
    </div>
  );
};
