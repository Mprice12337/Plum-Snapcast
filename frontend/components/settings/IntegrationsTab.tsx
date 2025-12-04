import React, {useState, useEffect} from 'react';
import type {Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';
import {airplayService, bluetoothService} from '../../services/integrationsService';

interface IntegrationsTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

type ApplyStatus = 'idle' | 'pending' | 'applying' | 'success' | 'error';

export const IntegrationsTab: React.FC<IntegrationsTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  // AirPlay device name state
  const [airplayDeviceName, setAirplayDeviceName] = useState(settings.integrations.airplay.deviceName);
  const [airplayNameStatus, setAirplayNameStatus] = useState<ApplyStatus>('idle');
  const [airplayNameMessage, setAirplayNameMessage] = useState('');
  const [isTogglingAirplay, setIsTogglingAirplay] = useState(false);

  // Bluetooth device name state
  const [bluetoothDeviceName, setBluetoothDeviceName] = useState(settings.integrations.bluetooth.deviceName);
  const [bluetoothNameStatus, setBluetoothNameStatus] = useState<ApplyStatus>('idle');
  const [bluetoothNameMessage, setBluetoothNameMessage] = useState('');
  const [isTogglingBluetooth, setIsTogglingBluetooth] = useState(false);

  // Update local state when settings change externally
  useEffect(() => {
    setAirplayDeviceName(settings.integrations.airplay.deviceName);
  }, [settings.integrations.airplay.deviceName]);

  useEffect(() => {
    setBluetoothDeviceName(settings.integrations.bluetooth.deviceName);
  }, [settings.integrations.bluetooth.deviceName]);

  // Check if device name has changed
  const airplayNameChanged = airplayDeviceName !== settings.integrations.airplay.deviceName;
  const bluetoothNameChanged = bluetoothDeviceName !== settings.integrations.bluetooth.deviceName;

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  const handleAirplayToggle = async (enabled: boolean) => {
    setIsTogglingAirplay(true);
    try {
      const result = enabled
        ? await airplayService.enable()
        : await airplayService.disable();

      if (result.success) {
        // Update settings in state
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            airplay: {
              ...settings.integrations.airplay,
              enabled,
            },
          },
        });
      } else {
        console.error('Failed to toggle AirPlay:', result.message);
        alert(`Failed to ${enabled ? 'enable' : 'disable'} AirPlay: ${result.message}`);
      }
    } catch (error) {
      console.error('Error toggling AirPlay:', error);
      alert(`Error ${enabled ? 'enabling' : 'disabling'} AirPlay`);
    } finally {
      setIsTogglingAirplay(false);
    }
  };

  const handleApplyAirplayDeviceName = async () => {
    if (!airplayNameChanged) return;

    setAirplayNameStatus('applying');
    setAirplayNameMessage('Applying changes... this may take up to 60 seconds');

    try {
      const result = await airplayService.updateDeviceName(airplayDeviceName);

      if (result.success) {
        setAirplayNameStatus('success');
        setAirplayNameMessage('Applied');

        // Update settings - note: restarting service enables AirPlay
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            airplay: {
              ...settings.integrations.airplay,
              deviceName: airplayDeviceName,
              enabled: true,
            },
          },
        });

        // Clear success message after 3 seconds
        setTimeout(() => {
          setAirplayNameStatus('idle');
          setAirplayNameMessage('');
        }, 3000);
      } else {
        setAirplayNameStatus('error');
        setAirplayNameMessage(result.message || 'Failed to apply');
      }
    } catch (error: any) {
      setAirplayNameStatus('error');
      setAirplayNameMessage(error.message || 'Error applying changes');
    }
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

  const handleBluetoothToggle = async (enabled: boolean) => {
    setIsTogglingBluetooth(true);
    try {
      const result = enabled
        ? await bluetoothService.enable()
        : await bluetoothService.disable();

      if (result.success) {
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            bluetooth: {
              ...settings.integrations.bluetooth,
              enabled,
            },
          },
        });
      } else {
        console.error('Failed to toggle Bluetooth:', result.message);
        alert(`Failed to ${enabled ? 'enable' : 'disable'} Bluetooth: ${result.message}`);
      }
    } catch (error) {
      console.error('Error toggling Bluetooth:', error);
      alert(`Error ${enabled ? 'enabling' : 'disabling'} Bluetooth`);
    } finally {
      setIsTogglingBluetooth(false);
    }
  };

  const handleApplyBluetoothDeviceName = async () => {
    if (!bluetoothNameChanged) return;

    // Track if Bluetooth was disabled before applying
    const wasDisabled = !settings.integrations.bluetooth.enabled;

    setBluetoothNameStatus('applying');
    setBluetoothNameMessage('Applying changes... this may take up to 60 seconds');

    try {
      const result = await bluetoothService.updateDeviceName(bluetoothDeviceName);

      if (result.success) {
        setBluetoothNameStatus('success');
        setBluetoothNameMessage('Applied');

        // Update settings - if Bluetooth was disabled, it's now enabled
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            bluetooth: {
              ...settings.integrations.bluetooth,
              deviceName: bluetoothDeviceName,
              enabled: wasDisabled ? true : settings.integrations.bluetooth.enabled,
            },
          },
        });

        // Clear success message after 3 seconds
        setTimeout(() => {
          setBluetoothNameStatus('idle');
          setBluetoothNameMessage('');
        }, 3000);
      } else {
        setBluetoothNameStatus('error');
        setBluetoothNameMessage(result.message || 'Failed to apply');
      }
    } catch (error: any) {
      setBluetoothNameStatus('error');
      setBluetoothNameMessage(error.message || 'Error applying changes');
    }
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
              onChange={handleAirplayToggle}
              icon="fa-apple"
              disabled={isTogglingAirplay}
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
          {isTogglingAirplay && (
            <p className="text-xs text-amber-500 ml-8 mt-1">
              Processing... this may take up to 60 seconds
            </p>
          )}

          {expandedSection === 'airplay' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={airplayDeviceName}
                    onChange={(e) => setAirplayDeviceName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && airplayNameChanged) {
                        handleApplyAirplayDeviceName();
                      }
                    }}
                    className="w-full px-3 py-2 pr-20 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                    placeholder="Plum Audio"
                    disabled={airplayNameStatus === 'applying'}
                  />
                  {airplayNameChanged && (
                    <button
                      onClick={handleApplyAirplayDeviceName}
                      disabled={airplayNameStatus === 'applying'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs bg-[var(--accent-color)] text-white rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
                    >
                      {airplayNameStatus === 'applying' ? 'Applying...' : 'Apply'}
                    </button>
                  )}
                </div>
                {airplayNameMessage && (
                  <p className={`text-xs mt-1 ${
                    airplayNameStatus === 'success'
                      ? 'text-green-500'
                      : airplayNameStatus === 'error'
                      ? 'text-red-500'
                      : 'text-[var(--text-muted)]'
                  }`}>
                    {airplayNameMessage}
                  </p>
                )}
                {airplayNameChanged && !airplayNameMessage && (
                  <p className="text-xs text-amber-500 mt-1">
                    Pending changes - press Enter or click Apply
                  </p>
                )}
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
              onChange={handleBluetoothToggle}
              icon="fa-bluetooth"
              disabled={isTogglingBluetooth}
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
          {isTogglingBluetooth && (
            <p className="text-xs text-amber-500 ml-8 mt-1">
              Processing... this may take up to 60 seconds
            </p>
          )}

          {expandedSection === 'bluetooth' && (
            <div className="mt-4 ml-8 space-y-3">
              <div>
                <label className="block text-sm text-[var(--text-secondary)] mb-1">
                  Device Name
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={bluetoothDeviceName}
                    onChange={(e) => setBluetoothDeviceName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleApplyBluetoothDeviceName()}
                    disabled={bluetoothNameStatus === 'applying'}
                    className="w-full px-3 py-2 pr-20 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)] disabled:opacity-50"
                    placeholder="Plum Audio"
                  />
                  {bluetoothNameChanged && (
                    <button
                      onClick={handleApplyBluetoothDeviceName}
                      disabled={bluetoothNameStatus === 'applying'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs bg-[var(--accent-color)] text-white rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {bluetoothNameStatus === 'applying' ? 'Applying...' : 'Apply'}
                    </button>
                  )}
                </div>
                {bluetoothNameMessage && (
                  <p className={`text-xs mt-1 ${
                    bluetoothNameStatus === 'success'
                      ? 'text-green-500'
                      : bluetoothNameStatus === 'error'
                      ? 'text-red-500'
                      : 'text-[var(--text-muted)]'
                  }`}>
                    {bluetoothNameMessage}
                  </p>
                )}
                {bluetoothNameChanged && !bluetoothNameMessage && (
                  <p className="text-xs text-amber-500 mt-1">
                    Pending changes - press Enter or click Apply
                  </p>
                )}
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
