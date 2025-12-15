import React, {useState, useEffect} from 'react';
import type {Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';
import {airplayService, bluetoothService, spotifyService, dlnaService, plexampService} from '../../services/integrationsService';
import { Icon } from '../Icon';

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

  // Spotify device name state
  const [spotifyDeviceName, setSpotifyDeviceName] = useState(settings.integrations.spotify.deviceName);
  const [spotifyNameStatus, setSpotifyNameStatus] = useState<ApplyStatus>('idle');
  const [spotifyNameMessage, setSpotifyNameMessage] = useState('');
  const [isTogglingSpotify, setIsTogglingSpotify] = useState(false);

  // DLNA device name state
  const [dlnaDeviceName, setDlnaDeviceName] = useState(settings.integrations.dlna.deviceName);
  const [dlnaNameStatus, setDlnaNameStatus] = useState<ApplyStatus>('idle');
  const [dlnaNameMessage, setDlnaNameMessage] = useState('');
  const [isTogglingDlna, setIsTogglingDlna] = useState(false);

  // Plexamp state
  const [isTogglingPlexamp, setIsTogglingPlexamp] = useState(false);

  // Update local state when settings change externally
  useEffect(() => {
    setAirplayDeviceName(settings.integrations.airplay.deviceName);
  }, [settings.integrations.airplay.deviceName]);

  useEffect(() => {
    setBluetoothDeviceName(settings.integrations.bluetooth.deviceName);
  }, [settings.integrations.bluetooth.deviceName]);

  useEffect(() => {
    setSpotifyDeviceName(settings.integrations.spotify.deviceName);
  }, [settings.integrations.spotify.deviceName]);

  useEffect(() => {
    setDlnaDeviceName(settings.integrations.dlna.deviceName);
  }, [settings.integrations.dlna.deviceName]);

  // Check if device name has changed
  const airplayNameChanged = airplayDeviceName !== settings.integrations.airplay.deviceName;
  const bluetoothNameChanged = bluetoothDeviceName !== settings.integrations.bluetooth.deviceName;
  const spotifyNameChanged = spotifyDeviceName !== settings.integrations.spotify.deviceName;
  const dlnaNameChanged = dlnaDeviceName !== settings.integrations.dlna.deviceName;

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

  const handleBluetoothChange = async (field: string, value: boolean | string) => {
    // For discoverable, call API to apply immediately
    if (field === 'discoverable' && typeof value === 'boolean') {
      try {
        await bluetoothService.updateSettings({ discoverable: value });

        // Update local state after successful API call
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
      } catch (error: any) {
        console.error(`Failed to update Bluetooth ${field}:`, error);
        alert(`Failed to update ${field}: ${error.message}`);
      }
    } else {
      // For other fields (like adapter), just update local state
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
    }
  };

  const handleSpotifyToggle = async (enabled: boolean) => {
    setIsTogglingSpotify(true);
    try {
      const result = enabled
        ? await spotifyService.enable()
        : await spotifyService.disable();

      if (result.success) {
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            spotify: {
              ...settings.integrations.spotify,
              enabled,
            },
          },
        });
      } else {
        console.error('Failed to toggle Spotify:', result.message);
        alert(`Failed to ${enabled ? 'enable' : 'disable'} Spotify: ${result.message}`);
      }
    } catch (error) {
      console.error('Error toggling Spotify:', error);
      alert(`Error ${enabled ? 'enabling' : 'disabling'} Spotify`);
    } finally {
      setIsTogglingSpotify(false);
    }
  };

  const handleApplySpotifyDeviceName = async () => {
    if (!spotifyNameChanged) return;

    setSpotifyNameStatus('applying');
    setSpotifyNameMessage('Applying changes... this may take up to 60 seconds');

    try {
      const result = await spotifyService.updateDeviceName(spotifyDeviceName);

      if (result.success) {
        setSpotifyNameStatus('success');
        setSpotifyNameMessage('Applied');

        // Update settings - restarting service enables Spotify
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            spotify: {
              ...settings.integrations.spotify,
              deviceName: spotifyDeviceName,
              enabled: true,
            },
          },
        });

        // Clear success message after 3 seconds
        setTimeout(() => {
          setSpotifyNameStatus('idle');
          setSpotifyNameMessage('');
        }, 3000);
      } else {
        setSpotifyNameStatus('error');
        setSpotifyNameMessage(result.message || 'Failed to apply');
      }
    } catch (error: any) {
      setSpotifyNameStatus('error');
      setSpotifyNameMessage(error.message || 'Error applying changes');
    }
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

  const handleDlnaToggle = async (enabled: boolean) => {
    setIsTogglingDlna(true);
    try {
      const result = enabled
        ? await dlnaService.enable()
        : await dlnaService.disable();

      if (result.success) {
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            dlna: {
              ...settings.integrations.dlna,
              enabled,
            },
          },
        });
      } else {
        alert(`Failed to ${enabled ? 'enable' : 'disable'} DLNA: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error ${enabled ? 'enabling' : 'disabling'} DLNA: ${error.message}`);
    } finally {
      setIsTogglingDlna(false);
    }
  };

  const handleApplyDlnaDeviceName = async () => {
    if (!dlnaNameChanged) return;

    setDlnaNameStatus('applying');
    setDlnaNameMessage('Applying changes...');

    try {
      const result = await dlnaService.updateDeviceName(dlnaDeviceName);

      if (result.success) {
        setDlnaNameStatus('success');
        setDlnaNameMessage('Applied');

        // Update parent settings
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            dlna: {
              ...settings.integrations.dlna,
              deviceName: dlnaDeviceName,
              enabled: true,
            },
          },
        });

        // Clear success message after 3 seconds
        setTimeout(() => {
          setDlnaNameStatus('idle');
          setDlnaNameMessage('');
        }, 3000);
      }
    } catch (error: any) {
      setDlnaNameStatus('error');
      setDlnaNameMessage(error.message || 'Error applying changes');
    }
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

  const handlePlexampToggle = async (enabled: boolean) => {
    setIsTogglingPlexamp(true);
    try {
      const result = enabled
        ? await plexampService.enable()
        : await plexampService.disable();

      if (result.success) {
        onSettingsChange({
          ...settings,
          integrations: {
            ...settings.integrations,
            plexamp: {
              ...settings.integrations.plexamp,
              enabled,
            },
          },
        });
      } else {
        alert(`Failed to ${enabled ? 'enable' : 'disable'} Plexamp: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error ${enabled ? 'enabling' : 'disabling'} Plexamp: ${error.message}`);
    } finally {
      setIsTogglingPlexamp(false);
    }
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
          <div className="flex items-start justify-between gap-4">
            {/* Left: Icon */}
            <div className="w-12 flex justify-center items-center flex-shrink-0">
              <Icon name="apple" className="text-[2.5rem] text-[var(--text-secondary)]" style={{ color: 'inherit' }} aria-hidden />
            </div>

            {/* Middle: Title + Description */}
            <div className="flex flex-col flex-1">
              <span className="text-base font-semibold text-[var(--text-secondary)]">AirPlay</span>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                AirPlay audio streaming (AirPlay 1 & 2)
              </p>
              {isTogglingAirplay && (
                <p className="text-xs text-amber-500 mt-1">
                  Processing... this may take up to 60 seconds
                </p>
              )}
            </div>

            {/* Right: Toggle + Chevron */}
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.integrations.airplay.enabled}
                  onChange={(e) => handleAirplayToggle(e.target.checked)}
                  disabled={isTogglingAirplay}
                  id="airplay-toggle"
                />
                <label
                  htmlFor="airplay-toggle"
                  className={`block w-12 h-6 rounded-full transition cursor-pointer ${settings.integrations.airplay.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingAirplay ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${settings.integrations.airplay.enabled ? 'translate-x-6' : ''}`}></div>
                </label>
              </div>
              <button
                onClick={() => toggleSection('airplay')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'airplay' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'airplay' && (
            <div className="mt-4 ml-14 space-y-3">
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
          <div className="flex items-start justify-between gap-4">
            {/* Left: Icon */}
            <div className="w-12 flex justify-center items-center flex-shrink-0">
              <Icon name="bluetooth" className="text-[2.5rem] text-[var(--text-secondary)]" style={{ color: 'inherit' }} aria-hidden />
            </div>

            {/* Middle: Title + Description */}
            <div className="flex flex-col flex-1">
              <span className="text-base font-semibold text-[var(--text-secondary)]">Bluetooth</span>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                Bluetooth A2DP audio streaming
              </p>
              {isTogglingBluetooth && (
                <p className="text-xs text-amber-500 mt-1">
                  Processing... this may take up to 60 seconds
                </p>
              )}
            </div>

            {/* Right: Toggle + Chevron */}
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.integrations.bluetooth.enabled}
                  onChange={(e) => handleBluetoothToggle(e.target.checked)}
                  disabled={isTogglingBluetooth}
                  id="bluetooth-toggle"
                />
                <label
                  htmlFor="bluetooth-toggle"
                  className={`block w-12 h-6 rounded-full transition cursor-pointer ${settings.integrations.bluetooth.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingBluetooth ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${settings.integrations.bluetooth.enabled ? 'translate-x-6' : ''}`}></div>
                </label>
              </div>
              <button
                onClick={() => toggleSection('bluetooth')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'bluetooth' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'bluetooth' && (
            <div className="mt-4 ml-14 space-y-3">
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
          <div className="flex items-start justify-between gap-4">
            {/* Left: Icon */}
            <div className="w-12 flex justify-center items-center flex-shrink-0">
              <Icon name="spotify" className="text-[2.5rem] text-[var(--text-secondary)]" style={{ color: 'inherit' }} aria-hidden />
            </div>

            {/* Middle: Title + Description */}
            <div className="flex flex-col flex-1">
              <span className="text-base font-semibold text-[var(--text-secondary)]">Spotify Connect</span>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                Stream music directly from Spotify
              </p>
              {isTogglingSpotify && (
                <p className="text-xs text-amber-500 mt-1">
                  Processing... this may take up to 60 seconds
                </p>
              )}
            </div>

            {/* Right: Toggle + Chevron */}
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.integrations.spotify.enabled}
                  onChange={(e) => handleSpotifyToggle(e.target.checked)}
                  disabled={isTogglingSpotify}
                  id="spotify-toggle"
                />
                <label
                  htmlFor="spotify-toggle"
                  className={`block w-12 h-6 rounded-full transition cursor-pointer ${settings.integrations.spotify.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingSpotify ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${settings.integrations.spotify.enabled ? 'translate-x-6' : ''}`}></div>
                </label>
              </div>
              <button
                onClick={() => toggleSection('spotify')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'spotify' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'spotify' && (
            <div className="mt-4 ml-14 space-y-3">
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
                <div className="relative">
                  <input
                    type="text"
                    value={spotifyDeviceName}
                    onChange={(e) => setSpotifyDeviceName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && spotifyNameChanged) {
                        handleApplySpotifyDeviceName();
                      }
                    }}
                    className="w-full px-3 py-2 pr-20 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                    placeholder="Plum Audio"
                    disabled={spotifyNameStatus === 'applying'}
                  />
                  {spotifyNameChanged && (
                    <button
                      onClick={handleApplySpotifyDeviceName}
                      disabled={spotifyNameStatus === 'applying'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs bg-[var(--accent-color)] text-white rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
                    >
                      {spotifyNameStatus === 'applying' ? 'Applying...' : 'Apply'}
                    </button>
                  )}
                </div>
                {spotifyNameMessage && (
                  <p className={`text-xs mt-1 ${
                    spotifyNameStatus === 'success'
                      ? 'text-green-500'
                      : spotifyNameStatus === 'error'
                      ? 'text-red-500'
                      : 'text-[var(--text-muted)]'
                  }`}>
                    {spotifyNameMessage}
                  </p>
                )}
                {spotifyNameChanged && !spotifyNameMessage && (
                  <p className="text-xs text-amber-500 mt-1">
                    Pending changes - press Enter or click Apply
                  </p>
                )}
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
          <div className="flex items-start justify-between gap-4">
            {/* Left: Icon */}
            <div className="w-12 flex justify-center items-center flex-shrink-0">
              <Icon name="network-wired" className="text-[2.5rem] text-[var(--text-secondary)]" style={{ color: 'inherit' }} aria-hidden />
            </div>

            {/* Middle: Title + Description */}
            <div className="flex flex-col flex-1">
              <span className="text-base font-semibold text-[var(--text-secondary)]">DLNA/UPnP</span>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                DLNA/UPnP media renderer
              </p>
              {isTogglingDlna && (
                <p className="text-xs text-amber-500 mt-1">
                  Processing... this may take up to 60 seconds
                </p>
              )}
            </div>

            {/* Right: Toggle + Chevron */}
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.integrations.dlna.enabled}
                  onChange={(e) => handleDlnaToggle(e.target.checked)}
                  disabled={isTogglingDlna}
                  id="dlna-toggle"
                />
                <label
                  htmlFor="dlna-toggle"
                  className={`block w-12 h-6 rounded-full transition cursor-pointer ${settings.integrations.dlna.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingDlna ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${settings.integrations.dlna.enabled ? 'translate-x-6' : ''}`}></div>
                </label>
              </div>
              <button
                onClick={() => toggleSection('dlna')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'dlna' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'dlna' && (
            <div className="mt-4 ml-14 space-y-3">
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
                <div className="relative">
                  <input
                    type="text"
                    value={dlnaDeviceName}
                    onChange={(e) => setDlnaDeviceName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && dlnaNameChanged) {
                        handleApplyDlnaDeviceName();
                      }
                    }}
                    placeholder="Plum Audio"
                    className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)] pr-20"
                    disabled={dlnaNameStatus === 'applying'}
                  />
                  {dlnaNameChanged && (
                    <button
                      onClick={handleApplyDlnaDeviceName}
                      disabled={dlnaNameStatus === 'applying'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 bg-[var(--accent-color)] text-white rounded-md text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {dlnaNameStatus === 'applying' ? 'Applying...' : 'Apply'}
                    </button>
                  )}
                </div>

                {/* Status feedback */}
                {dlnaNameMessage && (
                  <p className={`text-xs mt-1 ${
                    dlnaNameStatus === 'success'
                      ? 'text-green-500'
                      : dlnaNameStatus === 'error'
                      ? 'text-red-500'
                      : 'text-[var(--text-muted)]'
                  }`}>
                    {dlnaNameMessage}
                  </p>
                )}

                {/* Pending changes indicator */}
                {dlnaNameChanged && !dlnaNameMessage && (
                  <p className="text-xs text-amber-500 mt-1">
                    Pending changes - press Enter or click Apply
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Plexamp */}
        <div className={`p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)] ${!settings.integrations.plexamp.available ? 'opacity-50' : ''}`}>
          <div className="flex items-start justify-between gap-4">
            {/* Left: Icon */}
            <div className="w-12 flex justify-center items-center flex-shrink-0">
              <Icon name="plexamp" className="text-[2.5rem] text-[var(--text-secondary)]" style={{ color: 'inherit' }} aria-hidden />
            </div>

            {/* Middle: Title + Description */}
            <div className="flex flex-col flex-1">
              <span className="text-base font-semibold text-[var(--text-secondary)]">Plexamp</span>
              <p className="text-sm text-[var(--text-muted)] mt-1">
                Plex music player integration
              </p>
              {!settings.integrations.plexamp.available && (
                <p className="text-xs text-amber-500 mt-1">
                  Not configured - set PLEXAMP_ENABLED in .env file
                </p>
              )}
              {isTogglingPlexamp && (
                <p className="text-xs text-amber-500 mt-1">
                  Processing... this may take up to 60 seconds
                </p>
              )}
            </div>

            {/* Right: Toggle */}
            <div className="flex items-center flex-shrink-0">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={settings.integrations.plexamp.enabled}
                  onChange={(e) => handlePlexampToggle(e.target.checked)}
                  disabled={!settings.integrations.plexamp.available || isTogglingPlexamp}
                  id="plexamp-toggle"
                />
                <label
                  htmlFor="plexamp-toggle"
                  className={`block w-12 h-6 rounded-full transition ${!settings.integrations.plexamp.available || isTogglingPlexamp ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'} ${settings.integrations.plexamp.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'}`}
                >
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${settings.integrations.plexamp.enabled ? 'translate-x-6' : ''}`}></div>
                </label>
              </div>
            </div>
          </div>
        </div>

        {/* Snapcast Stream */}
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <Switch
            label="Snapcast Stream"
            checked={settings.integrations.snapcast}
            onChange={(val) => handleSimpleChange('snapcast', val)}
            icon="tower-broadcast"
          />
          <p className="text-sm text-[var(--text-muted)] ml-8 mt-2">
            Built-in Snapcast audio stream source
          </p>
        </div>
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <p className="text-xs text-[var(--text-muted)] italic">
          Note: Changes to integration settings will be applied after service restart.
        </p>
      </div>
    </div>
  );
};
