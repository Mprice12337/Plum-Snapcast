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

type AirPlayEndpoint = {
  id: string;
  enabled: boolean;
  deviceName: string;
  port: number;
  udpPortBase: number;
};

type SpotifyEndpoint = {
  id: string;
  enabled: boolean;
  deviceName: string;
  zeroconfPort: number;
};

export const IntegrationsTab: React.FC<IntegrationsTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  // AirPlay endpoints state
  const [airplayEndpoints, setAirplayEndpoints] = useState<AirPlayEndpoint[]>([]);
  const [endpointNames, setEndpointNames] = useState<Record<string, string>>({});
  const [endpointNameStatuses, setEndpointNameStatuses] = useState<Record<string, ApplyStatus>>({});
  const [endpointNameMessages, setEndpointNameMessages] = useState<Record<string, string>>({});
  const [isTogglingEndpoint, setIsTogglingEndpoint] = useState<Record<string, boolean>>({});
  const [isAddingEndpoint, setIsAddingEndpoint] = useState(false);
  const [newEndpointName, setNewEndpointName] = useState('');
  const [showAddEndpoint, setShowAddEndpoint] = useState(false);

  // Spotify endpoints state
  const [spotifyEndpoints, setSpotifyEndpoints] = useState<SpotifyEndpoint[]>([]);
  const [spotifyEndpointNames, setSpotifyEndpointNames] = useState<Record<string, string>>({});
  const [spotifyEndpointNameStatuses, setSpotifyEndpointNameStatuses] = useState<Record<string, ApplyStatus>>({});
  const [spotifyEndpointNameMessages, setSpotifyEndpointNameMessages] = useState<Record<string, string>>({});
  const [isTogglingSpotifyEndpoint, setIsTogglingSpotifyEndpoint] = useState<Record<string, boolean>>({});
  const [isAddingSpotifyEndpoint, setIsAddingSpotifyEndpoint] = useState(false);
  const [newSpotifyEndpointName, setNewSpotifyEndpointName] = useState('');
  const [showAddSpotifyEndpoint, setShowAddSpotifyEndpoint] = useState(false);

  // Bluetooth device name state
  const [bluetoothDeviceName, setBluetoothDeviceName] = useState(settings.integrations.bluetooth.deviceName);
  const [bluetoothNameStatus, setBluetoothNameStatus] = useState<ApplyStatus>('idle');
  const [bluetoothNameMessage, setBluetoothNameMessage] = useState('');
  const [isTogglingBluetooth, setIsTogglingBluetooth] = useState(false);

  // DLNA device name state
  const [dlnaDeviceName, setDlnaDeviceName] = useState(settings.integrations.dlna.deviceName);
  const [dlnaNameStatus, setDlnaNameStatus] = useState<ApplyStatus>('idle');
  const [dlnaNameMessage, setDlnaNameMessage] = useState('');
  const [isTogglingDlna, setIsTogglingDlna] = useState(false);

  // Plexamp state
  const [isTogglingPlexamp, setIsTogglingPlexamp] = useState(false);

  // Load AirPlay endpoints on mount
  useEffect(() => {
    const loadEndpoints = async () => {
      try {
        const result = await airplayService.listEndpoints();
        if (result.success && result.endpoints) {
          setAirplayEndpoints(result.endpoints);
          // Initialize endpoint name states
          const names: Record<string, string> = {};
          result.endpoints.forEach(ep => {
            names[ep.id] = ep.deviceName;
          });
          setEndpointNames(names);
        }
      } catch (error) {
        console.error('Failed to load AirPlay endpoints:', error);
      }
    };
    loadEndpoints();
  }, []);

  // Load Spotify endpoints on mount
  useEffect(() => {
    const loadSpotifyEndpoints = async () => {
      try {
        const result = await spotifyService.listEndpoints();
        if (result.success && result.endpoints) {
          setSpotifyEndpoints(result.endpoints);
          // Initialize endpoint name states
          const names: Record<string, string> = {};
          result.endpoints.forEach(ep => {
            names[ep.id] = ep.deviceName;
          });
          setSpotifyEndpointNames(names);
        }
      } catch (error) {
        console.error('Failed to load Spotify endpoints:', error);
      }
    };
    loadSpotifyEndpoints();
  }, []);

  useEffect(() => {
    setBluetoothDeviceName(settings.integrations.bluetooth.deviceName);
  }, [settings.integrations.bluetooth.deviceName]);

  useEffect(() => {
    setDlnaDeviceName(settings.integrations.dlna.deviceName);
  }, [settings.integrations.dlna.deviceName]);

  // Check if device name has changed
  const bluetoothNameChanged = bluetoothDeviceName !== settings.integrations.bluetooth.deviceName;
  const dlnaNameChanged = dlnaDeviceName !== settings.integrations.dlna.deviceName;

  const toggleSection = (section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  // AirPlay endpoint handlers
  const handleEndpointToggle = async (endpointId: string, enabled: boolean) => {
    setIsTogglingEndpoint({...isTogglingEndpoint, [endpointId]: true});
    try {
      const result = await airplayService.updateEndpoint(endpointId, undefined, enabled);

      if (result.success) {
        // Update local state
        setAirplayEndpoints(airplayEndpoints.map(ep =>
          ep.id === endpointId ? {...ep, enabled} : ep
        ));
      } else {
        alert(`Failed to ${enabled ? 'enable' : 'disable'} endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error ${enabled ? 'enabling' : 'disabling'} endpoint: ${error.message}`);
    } finally {
      setIsTogglingEndpoint({...isTogglingEndpoint, [endpointId]: false});
    }
  };

  const handleEndpointNameChange = async (endpointId: string) => {
    const newName = endpointNames[endpointId];
    const endpoint = airplayEndpoints.find(ep => ep.id === endpointId);

    if (!endpoint || newName === endpoint.deviceName) return;

    setEndpointNameStatuses({...endpointNameStatuses, [endpointId]: 'applying'});
    setEndpointNameMessages({...endpointNameMessages, [endpointId]: 'Applying...'});

    try {
      const result = await airplayService.updateEndpoint(endpointId, newName, undefined);

      if (result.success) {
        setEndpointNameStatuses({...endpointNameStatuses, [endpointId]: 'success'});
        setEndpointNameMessages({...endpointNameMessages, [endpointId]: 'Applied'});

        // Update local state
        setAirplayEndpoints(airplayEndpoints.map(ep =>
          ep.id === endpointId ? {...ep, deviceName: newName} : ep
        ));

        setTimeout(() => {
          setEndpointNameStatuses({...endpointNameStatuses, [endpointId]: 'idle'});
          setEndpointNameMessages({...endpointNameMessages, [endpointId]: ''});
        }, 3000);
      } else {
        setEndpointNameStatuses({...endpointNameStatuses, [endpointId]: 'error'});
        setEndpointNameMessages({...endpointNameMessages, [endpointId]: result.message || 'Failed'});
      }
    } catch (error: any) {
      setEndpointNameStatuses({...endpointNameStatuses, [endpointId]: 'error'});
      setEndpointNameMessages({...endpointNameMessages, [endpointId]: error.message || 'Error'});
    }
  };

  const handleAddEndpoint = async () => {
    if (!newEndpointName.trim()) {
      alert('Please enter a device name');
      return;
    }

    setIsAddingEndpoint(true);
    try {
      const result = await airplayService.addEndpoint(newEndpointName, true);

      if (result.success && result.endpoint) {
        // Update local state
        setAirplayEndpoints([...airplayEndpoints, result.endpoint]);
        setEndpointNames({...endpointNames, [result.endpoint.id]: result.endpoint.deviceName});
        setNewEndpointName('');
        setShowAddEndpoint(false);
      } else {
        alert(`Failed to add endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error adding endpoint: ${error.message}`);
    } finally {
      setIsAddingEndpoint(false);
    }
  };

  const handleRemoveEndpoint = async (endpointId: string) => {
    if (airplayEndpoints.length <= 1) {
      alert('Cannot remove the last AirPlay endpoint');
      return;
    }

    const endpoint = airplayEndpoints.find(ep => ep.id === endpointId);
    if (!endpoint) return;

    if (!confirm(`Remove AirPlay endpoint "${endpoint.deviceName}"?`)) {
      return;
    }

    try {
      const result = await airplayService.removeEndpoint(endpointId);

      if (result.success) {
        // Update local state
        setAirplayEndpoints(airplayEndpoints.filter(ep => ep.id !== endpointId));
        const newNames = {...endpointNames};
        delete newNames[endpointId];
        setEndpointNames(newNames);
      } else {
        alert(`Failed to remove endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error removing endpoint: ${error.message}`);
    }
  };

  // Spotify endpoint handlers
  const handleSpotifyEndpointToggle = async (endpointId: string, enabled: boolean) => {
    setIsTogglingSpotifyEndpoint({...isTogglingSpotifyEndpoint, [endpointId]: true});
    try {
      const result = await spotifyService.updateEndpoint(endpointId, undefined, enabled);

      if (result.success) {
        // Update local state
        setSpotifyEndpoints(spotifyEndpoints.map(ep =>
          ep.id === endpointId ? {...ep, enabled} : ep
        ));
      } else {
        alert(`Failed to ${enabled ? 'enable' : 'disable'} Spotify endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error ${enabled ? 'enabling' : 'disabling'} Spotify endpoint: ${error.message}`);
    } finally {
      setIsTogglingSpotifyEndpoint({...isTogglingSpotifyEndpoint, [endpointId]: false});
    }
  };

  const handleSpotifyEndpointNameChange = async (endpointId: string) => {
    const newName = spotifyEndpointNames[endpointId];
    const endpoint = spotifyEndpoints.find(ep => ep.id === endpointId);

    if (!endpoint || newName === endpoint.deviceName) return;

    setSpotifyEndpointNameStatuses({...spotifyEndpointNameStatuses, [endpointId]: 'applying'});
    setSpotifyEndpointNameMessages({...spotifyEndpointNameMessages, [endpointId]: 'Applying...'});

    try {
      const result = await spotifyService.updateEndpoint(endpointId, newName, undefined);

      if (result.success) {
        setSpotifyEndpointNameStatuses({...spotifyEndpointNameStatuses, [endpointId]: 'success'});
        setSpotifyEndpointNameMessages({...spotifyEndpointNameMessages, [endpointId]: 'Applied'});

        // Update local state
        setSpotifyEndpoints(spotifyEndpoints.map(ep =>
          ep.id === endpointId ? {...ep, deviceName: newName} : ep
        ));

        setTimeout(() => {
          setSpotifyEndpointNameStatuses({...spotifyEndpointNameStatuses, [endpointId]: 'idle'});
          setSpotifyEndpointNameMessages({...spotifyEndpointNameMessages, [endpointId]: ''});
        }, 3000);
      } else {
        setSpotifyEndpointNameStatuses({...spotifyEndpointNameStatuses, [endpointId]: 'error'});
        setSpotifyEndpointNameMessages({...spotifyEndpointNameMessages, [endpointId]: result.message || 'Failed'});
      }
    } catch (error: any) {
      setSpotifyEndpointNameStatuses({...spotifyEndpointNameStatuses, [endpointId]: 'error'});
      setSpotifyEndpointNameMessages({...spotifyEndpointNameMessages, [endpointId]: error.message || 'Error'});
    }
  };

  const handleAddSpotifyEndpoint = async () => {
    if (!newSpotifyEndpointName.trim()) {
      alert('Please enter a device name');
      return;
    }

    setIsAddingSpotifyEndpoint(true);
    try {
      const result = await spotifyService.addEndpoint(newSpotifyEndpointName, true);

      if (result.success && result.endpoint) {
        // Update local state
        setSpotifyEndpoints([...spotifyEndpoints, result.endpoint]);
        setSpotifyEndpointNames({...spotifyEndpointNames, [result.endpoint.id]: result.endpoint.deviceName});
        setNewSpotifyEndpointName('');
        setShowAddSpotifyEndpoint(false);
      } else {
        alert(`Failed to add Spotify endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error adding Spotify endpoint: ${error.message}`);
    } finally {
      setIsAddingSpotifyEndpoint(false);
    }
  };

  const handleRemoveSpotifyEndpoint = async (endpointId: string) => {
    if (spotifyEndpoints.length <= 1) {
      alert('Cannot remove the last Spotify endpoint');
      return;
    }

    const endpoint = spotifyEndpoints.find(ep => ep.id === endpointId);
    if (!endpoint) return;

    if (!confirm(`Remove Spotify endpoint "${endpoint.deviceName}"?`)) {
      return;
    }

    try {
      const result = await spotifyService.removeEndpoint(endpointId);

      if (result.success) {
        // Update local state
        setSpotifyEndpoints(spotifyEndpoints.filter(ep => ep.id !== endpointId));
        const newNames = {...spotifyEndpointNames};
        delete newNames[endpointId];
        setSpotifyEndpointNames(newNames);
      } else {
        alert(`Failed to remove Spotify endpoint: ${result.message}`);
      }
    } catch (error: any) {
      alert(`Error removing Spotify endpoint: ${error.message}`);
    }
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
                AirPlay audio streaming (AirPlay 1 & 2) - {airplayEndpoints.length} endpoint{airplayEndpoints.length !== 1 ? 's' : ''}
              </p>
            </div>

            {/* Right: Chevron */}
            <div className="flex items-center flex-shrink-0">
              <button
                onClick={() => toggleSection('airplay')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'airplay' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'airplay' && (
            <div className="mt-4 ml-14 space-y-4">
              {/* Endpoints list */}
              {airplayEndpoints.map((endpoint) => {
                const nameChanged = endpointNames[endpoint.id] !== endpoint.deviceName;
                return (
                  <div key={endpoint.id} className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--border-color)]">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="text-sm font-medium text-[var(--text-secondary)]">
                        Endpoint #{endpoint.id}
                      </span>
                      <div className="flex items-center gap-2">
                        <div className="relative">
                          <input
                            type="checkbox"
                            className="sr-only"
                            checked={endpoint.enabled}
                            onChange={(e) => handleEndpointToggle(endpoint.id, e.target.checked)}
                            disabled={isTogglingEndpoint[endpoint.id]}
                            id={`endpoint-${endpoint.id}-toggle`}
                          />
                          <label
                            htmlFor={`endpoint-${endpoint.id}-toggle`}
                            className={`block w-10 h-5 rounded-full transition cursor-pointer ${endpoint.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingEndpoint[endpoint.id] ? 'opacity-50 cursor-not-allowed' : ''}`}
                          >
                            <div className={`dot absolute left-0.5 top-0.5 bg-white w-4 h-4 rounded-full transition-transform ${endpoint.enabled ? 'translate-x-5' : ''}`}></div>
                          </label>
                        </div>
                        {airplayEndpoints.length > 1 && (
                          <button
                            onClick={() => handleRemoveEndpoint(endpoint.id)}
                            className="text-red-500 hover:text-red-400 text-xs"
                            title="Remove endpoint"
                          >
                            <Icon name="trash" className="text-sm" style={{ color: 'inherit' }} />
                          </button>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-[var(--text-muted)] mb-1">
                        Device Name
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          value={endpointNames[endpoint.id] || endpoint.deviceName}
                          onChange={(e) => setEndpointNames({...endpointNames, [endpoint.id]: e.target.value})}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && nameChanged) {
                              handleEndpointNameChange(endpoint.id);
                            }
                          }}
                          className="w-full px-2 py-1.5 pr-16 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                          placeholder="Plum Audio"
                          disabled={endpointNameStatuses[endpoint.id] === 'applying'}
                        />
                        {nameChanged && (
                          <button
                            onClick={() => handleEndpointNameChange(endpoint.id)}
                            disabled={endpointNameStatuses[endpoint.id] === 'applying'}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 px-2 py-0.5 text-xs bg-[var(--accent-color)] accent-button-text rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {endpointNameStatuses[endpoint.id] === 'applying' ? 'Applying...' : 'Apply'}
                          </button>
                        )}
                      </div>
                      {endpointNameMessages[endpoint.id] && (
                        <p className={`text-xs mt-1 ${
                          endpointNameStatuses[endpoint.id] === 'success'
                            ? 'text-green-500'
                            : endpointNameStatuses[endpoint.id] === 'error'
                            ? 'text-red-500'
                            : 'text-[var(--text-muted)]'
                        }`}>
                          {endpointNameMessages[endpoint.id]}
                        </p>
                      )}
                      {nameChanged && !endpointNameMessages[endpoint.id] && (
                        <p className="text-xs text-amber-500 mt-1">
                          Pending changes
                        </p>
                      )}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] mt-2">
                      Port: {endpoint.port}, UDP: {endpoint.udpPortBase}-{endpoint.udpPortBase + 9}
                    </div>
                  </div>
                );
              })}

              {/* Add endpoint button/form */}
              {!showAddEndpoint && airplayEndpoints.length < 10 && (
                <button
                  onClick={() => setShowAddEndpoint(true)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary-hover)] border border-[var(--border-color)] rounded text-sm text-[var(--text-secondary)] transition-colors"
                >
                  + Add Endpoint
                </button>
              )}

              {showAddEndpoint && (
                <div className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--accent-color)]">
                  <label className="block text-xs text-[var(--text-secondary)] mb-1">
                    New Endpoint Name
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newEndpointName}
                      onChange={(e) => setNewEndpointName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleAddEndpoint()}
                      className="flex-1 px-2 py-1.5 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                      placeholder="Living Room"
                      disabled={isAddingEndpoint}
                    />
                    <button
                      onClick={handleAddEndpoint}
                      disabled={isAddingEndpoint}
                      className="px-3 py-1.5 bg-[var(--accent-color)] accent-button-text rounded text-xs hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isAddingEndpoint ? 'Adding...' : 'Add'}
                    </button>
                    <button
                      onClick={() => {setShowAddEndpoint(false); setNewEndpointName('');}}
                      disabled={isAddingEndpoint}
                      className="px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-tertiary-hover)] rounded text-xs text-[var(--text-secondary)] disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {airplayEndpoints.length >= 10 && (
                <p className="text-xs text-[var(--text-muted)] italic">
                  Maximum of 10 endpoints reached
                </p>
              )}
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
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs bg-[var(--accent-color)] accent-button-text rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
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
                Stream music directly from Spotify - {spotifyEndpoints.length} endpoint{spotifyEndpoints.length !== 1 ? 's' : ''}
              </p>
            </div>

            {/* Right: Chevron */}
            <div className="flex items-center flex-shrink-0">
              <button
                onClick={() => toggleSection('spotify')}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <Icon name={expandedSection === 'spotify' ? 'chevron-up' : 'chevron-down'} className="text-lg" style={{ color: 'inherit' }} />
              </button>
            </div>
          </div>

          {expandedSection === 'spotify' && (
            <div className="mt-4 ml-14 space-y-4">
              {/* Endpoints list */}
              {spotifyEndpoints.map((endpoint) => {
                const nameChanged = spotifyEndpointNames[endpoint.id] !== endpoint.deviceName;
                return (
                  <div key={endpoint.id} className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--border-color)]">
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="text-sm font-medium text-[var(--text-secondary)]">
                        Endpoint #{endpoint.id}
                      </span>
                      <div className="flex items-center gap-2">
                        <div className="relative">
                          <input
                            type="checkbox"
                            className="sr-only"
                            checked={endpoint.enabled}
                            onChange={(e) => handleSpotifyEndpointToggle(endpoint.id, e.target.checked)}
                            disabled={isTogglingSpotifyEndpoint[endpoint.id]}
                            id={`spotify-endpoint-${endpoint.id}-toggle`}
                          />
                          <label
                            htmlFor={`spotify-endpoint-${endpoint.id}-toggle`}
                            className={`block w-10 h-5 rounded-full transition cursor-pointer ${endpoint.enabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'} ${isTogglingSpotifyEndpoint[endpoint.id] ? 'opacity-50 cursor-not-allowed' : ''}`}
                          >
                            <div className={`dot absolute left-0.5 top-0.5 bg-white w-4 h-4 rounded-full transition-transform ${endpoint.enabled ? 'translate-x-5' : ''}`}></div>
                          </label>
                        </div>
                        {spotifyEndpoints.length > 1 && (
                          <button
                            onClick={() => handleRemoveSpotifyEndpoint(endpoint.id)}
                            className="text-red-500 hover:text-red-400 text-xs"
                            title="Remove endpoint"
                          >
                            <Icon name="trash" className="text-sm" style={{ color: 'inherit' }} />
                          </button>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-[var(--text-muted)] mb-1">
                        Device Name
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          value={spotifyEndpointNames[endpoint.id] || endpoint.deviceName}
                          onChange={(e) => setSpotifyEndpointNames({...spotifyEndpointNames, [endpoint.id]: e.target.value})}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && nameChanged) {
                              handleSpotifyEndpointNameChange(endpoint.id);
                            }
                          }}
                          className="w-full px-2 py-1.5 pr-16 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                          placeholder="Plum Audio"
                          disabled={spotifyEndpointNameStatuses[endpoint.id] === 'applying'}
                        />
                        {nameChanged && (
                          <button
                            onClick={() => handleSpotifyEndpointNameChange(endpoint.id)}
                            disabled={spotifyEndpointNameStatuses[endpoint.id] === 'applying'}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 px-2 py-0.5 text-xs bg-[var(--accent-color)] accent-button-text rounded hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {spotifyEndpointNameStatuses[endpoint.id] === 'applying' ? 'Applying...' : 'Apply'}
                          </button>
                        )}
                      </div>
                      {spotifyEndpointNameMessages[endpoint.id] && (
                        <p className={`text-xs mt-1 ${
                          spotifyEndpointNameStatuses[endpoint.id] === 'success'
                            ? 'text-green-500'
                            : spotifyEndpointNameStatuses[endpoint.id] === 'error'
                            ? 'text-red-500'
                            : 'text-[var(--text-muted)]'
                        }`}>
                          {spotifyEndpointNameMessages[endpoint.id]}
                        </p>
                      )}
                      {nameChanged && !spotifyEndpointNameMessages[endpoint.id] && (
                        <p className="text-xs text-amber-500 mt-1">
                          Pending changes
                        </p>
                      )}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] mt-2">
                      Zeroconf Port: {endpoint.zeroconfPort}
                    </div>
                  </div>
                );
              })}

              {/* Add endpoint button/form */}
              {!showAddSpotifyEndpoint && spotifyEndpoints.length < 10 && (
                <button
                  onClick={() => setShowAddSpotifyEndpoint(true)}
                  className="w-full px-3 py-2 bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary-hover)] border border-[var(--border-color)] rounded text-sm text-[var(--text-secondary)] transition-colors"
                >
                  + Add Endpoint
                </button>
              )}

              {showAddSpotifyEndpoint && (
                <div className="p-3 bg-[var(--bg-secondary)] rounded border border-[var(--accent-color)]">
                  <label className="block text-xs text-[var(--text-secondary)] mb-1">
                    New Endpoint Name
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newSpotifyEndpointName}
                      onChange={(e) => setNewSpotifyEndpointName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleAddSpotifyEndpoint()}
                      className="flex-1 px-2 py-1.5 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                      placeholder="Living Room"
                      disabled={isAddingSpotifyEndpoint}
                    />
                    <button
                      onClick={handleAddSpotifyEndpoint}
                      disabled={isAddingSpotifyEndpoint}
                      className="px-3 py-1.5 bg-[var(--accent-color)] accent-button-text rounded text-xs hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isAddingSpotifyEndpoint ? 'Adding...' : 'Add'}
                    </button>
                    <button
                      onClick={() => {setShowAddSpotifyEndpoint(false); setNewSpotifyEndpointName('');}}
                      disabled={isAddingSpotifyEndpoint}
                      className="px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-tertiary-hover)] rounded text-xs text-[var(--text-secondary)] disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {spotifyEndpoints.length >= 10 && (
                <p className="text-xs text-[var(--text-muted)] italic">
                  Maximum of 10 endpoints reached
                </p>
              )}
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
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 bg-[var(--accent-color)] accent-button-text rounded-md text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
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
